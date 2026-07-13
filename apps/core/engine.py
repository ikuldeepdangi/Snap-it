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
    if not resume_instance.resume_storage_path:
        print("Resume storage path is empty.")
        return ""

    temp_path = None
    try:
        from utils.storage import download_to_temp
        temp_path = download_to_temp(resume_instance.resume_storage_path)
        
        reader = PdfReader(temp_path)
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
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                print(f"Cleaned up temporary file: {temp_path}")
            except Exception as e:
                print(f"Failed to delete temp file {temp_path}: {e}")


def get_genai_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")
    return genai.Client(api_key=api_key)

def analyze_screenshot_with_gemini(screenshot_path: str, resume_content: str, model: str = "gemini-3.1-flash-lite", prompt_template: str = None) -> Dict[str, Any]:
    """
    Uses Gemini's Vision capabilities to extract structured parameters from job screenshots
    and generate a personalized email.
    """
    print("new way  -")
    
    client = get_genai_client()
    path = Path(screenshot_path)
    pil_image = Image.open(path)
    
    if prompt_template is None:
        from apps.authentication.models import UserProfile
        prompt_template = UserProfile().get_email_prompt()
        
    prompt = prompt_template.format(
        resume_content=resume_content if resume_content else "No resume provided"
    )
    
    response = client.models.generate_content(
        model=model,
        contents=[prompt, pil_image],
        config={'response_mime_type': 'application/json'}
    )
    
    try:
        return json.loads(response.text)
    except Exception as e:
        print(f"Error parsing Gemini response: {e}")
        return {"error": "AI could not read image clearly", "raw": response.text}

def send_user_email(profile, payload: Dict[str, Any], attachment_path: str, original_filename: str = None) -> bool:
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
        
        # Build message using modern EmailMessage API
        message = EmailMessage()
        message['To'] = payload.get('hr_email')
        message['Subject'] = payload.get('email_subject', 'Application')
        message.set_content(payload.get('email_body', ''))
        
        # Add attachment
        if attachment_path:
            if not os.path.exists(attachment_path):
                raise ValueError(f"Resume attachment not found at path: {attachment_path}")
                
            with open(attachment_path, 'rb') as f:
                pdf_data = f.read()
            filename = original_filename if original_filename else os.path.basename(attachment_path)
            message.add_attachment(
                pdf_data, 
                maintype='application', 
                subtype='pdf', 
                filename=filename
            )
            
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
        return True
    except Exception as e:
        print(f"Failed to send email via Gmail API: {e}")
        raise ValueError(f"Gmail API Error: {e}")

def generate_email_draft_from_text(company: str, role: str, hr_email: str, resume_content: str, model: str = "gemini-3.1-flash-lite", prompt_template: str = None) -> Dict[str, Any]:
    """
    Uses Gemini to generate a personalized email draft based on extracted campaign data.
    """
    client = get_genai_client()
    
    if prompt_template is None:
        from apps.authentication.models import UserProfile
        prompt_template = UserProfile().get_email_prompt()
        
    prompt = prompt_template.format(
        resume_content=resume_content if resume_content else "No resume provided"
    )
    
    # We simulate what the OCR would have done but with explicit text inputs
    input_text = f"Company: {company}\nRole: {role}\nHR Email: {hr_email}\n\nPlease generate the email."
    
    response = client.models.generate_content(
        model=model,
        contents=[prompt, input_text],
        config={'response_mime_type': 'application/json'}
    )
    
    try:
        data = json.loads(response.text)
        # Ensure the hr_email is correct since the model might hallucinate it
        data['hr_email'] = hr_email
        data['company'] = company
        data['role'] = role
        return data
    except Exception as e:
        print(f"Error parsing Gemini response: {e}")
        return {"error": "AI could not generate draft from text", "raw": response.text}


import asyncio
from telegram import Bot

def send_async_telegram_alert(chat_id: int, message_text: str):
    """Synchronous thread-safe bridge letting the worker cluster push alerts back to Telegram chat."""
    if not chat_id:
        return
        
    async def _send():
        bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
        async with bot:
            await bot.send_message(chat_id=chat_id, text=message_text)
            
    try:
        asyncio.run(_send())
    except Exception as e:
        print(f"Failed to transmit background telegram alert log: {e}")
