import os
import json
import re
import base64
from pathlib import Path
from typing import Dict, Any
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from PIL import Image

from pypdf import PdfReader
from apps.core.models import Resume

load_dotenv()

def extract_text_from_pdf(resume_instance: Resume) -> str:
    """
    Reads and concatenates text from all PDF pages, then saves it to the model.
    """
    try:
        reader = PdfReader(resume_instance.file.path)
        text = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text.append(extracted)
        
        full_text = "\n".join(text)
        resume_instance.extracted_text = full_text
        resume_instance.save()
        return full_text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def get_genai_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")
    return genai.Client(api_key=api_key)

def analyze_screenshot_with_gemini(screenshot_path: str, resume_content: str, model: str = "gemini-3.1-flash-lite") -> Dict[str, Any]:
    """
    Uses Gemini's Vision capabilities to extract structured parameters from job screenshots
    and generate a personalized email.
    """
    print("new way  -")
    
    client = get_genai_client()
    path = Path(screenshot_path)
    pil_image = Image.open(path)
    
    prompt = f"""
    You are an elite hiring strategist. Look at the ATTACHED IMAGE (a job posting) and use the CANDIDATE RESUME below.

    CANDIDATE RESUME:
    {resume_content if resume_content else "No resume provided"}

    TASK:
    1. Extract: Company name, Job Role, and HR Email from the image.
    2. Write a HIGH-CONVERSION application email (220-320 words) based on the matched resume context.
    3. Generate a professional and catchy subject line tailored to the job description.

    RETURN ONLY VALID JSON:
    {{
      "company": "",
      "role": "",
      "hr_email": "",
      "email_subject": "",
      "email_body": ""
    }}
    """
    
    response = client.models.generate_content(
        model=model,
        contents=[prompt, pil_image],
        config={'response_mime_type': 'application/json'}
    )
    
    try:
        clean_json = re.search(r"\{.*\}", response.text, re.DOTALL).group()
        return json.loads(clean_json)
    except Exception as e:
        print(f"Error parsing Gemini response: {e}")
        return {"error": "AI could not read image clearly", "raw": response.text}

def send_user_email(profile, payload: Dict[str, Any], attachment_path: str) -> bool:
    """
    Connect to Gmail API and dispatch personalized emails with resume attachments.
    """
    if not profile.google_access_token and not profile.google_refresh_token:
        print("No Google tokens available.")
        raise ValueError("User has no Google credentials linked.")
        
    creds = Credentials(
        token=profile.google_access_token,
        refresh_token=profile.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
    )
    
    try:
        service = build('gmail', 'v1', credentials=creds)
        
        # Build MIME message
        message = MIMEMultipart()
        message['To'] = payload.get('hr_email')
        message['Subject'] = payload.get('email_subject', 'Application')
        
        # Add body
        body = payload.get('email_body', '')
        message.attach(MIMEText(body, 'plain'))
        
        # Add attachment
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                part = MIMEBase('application', 'pdf')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{filename}"',
            )
            message.attach(part)
            
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
        return True
    except Exception as e:
        print(f"Failed to send email via Gmail API: {e}")
        raise ValueError(f"Gmail API Error: {e}")
