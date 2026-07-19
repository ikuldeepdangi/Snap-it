import os
import sys
import json
from typing import List  # Added for strict Pydantic compatibility
from dotenv import load_dotenv
from google import genai  
from google.genai import types  
from pydantic import BaseModel, Field

# Ensure standard terminal output handles special characters smoothly on Windows
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Adjusted to load .env safely relative to this script file
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# 1. FIXED & ENHANCED: Cross-compatible Pydantic schema
class JobOpening(BaseModel):
    company_name: str = Field(description="Exact legal or operating name of the hiring entity.")
    tech_park_location: str = Field(description="The specific IT park, SEZ, or corporate node in Mumbai (e.g., Nesco, Mindspace, Hiranandani, MBP).")
    role_designation: str = Field(description="The formal corporate job title.")
    experience_required: str = Field(description="Required experience interval stated in the live posting.")
    inferred_ctc_lpa: str = Field(description="Salary range or 'Not Disclosed' explicitly mapped from the post.")
    core_technical_skills: List[str] = Field(description="List of primary technical stacks mentioned (e.g., FastAPI, Django, LLM, AWS).")
    hr_or_hiring_email: str = Field(description="Direct corporate recruiter email, talent acquisition alias, or official careers email route (e.g. careers@company.com). If explicitly missing from the public webpage, set value to 'None Found'.")
    source_reference_url: str = Field(description="A highly specific search query or job platform route string indicating where this live listing exists.")

class JobSearchPayload(BaseModel):
    active_listings: List[JobOpening]

def fetch_strict_live_jobs(user_data):
    if not os.environ.get("GEMINI_API_KEY"):
        print("Fatal Error: GEMINI_API_KEY is missing from environment.", file=sys.stderr)
        sys.exit(1)

    print("Initializing Strict Gemini Grounded Client...")
    client = genai.Client()

    role, city, ctc, experience = user_data

    # 2. OPTIMIZED PROMPT: Allowing 'None Found' fallback prevents total output suppression
    prompt = (
        f"You are a strict data-extraction engine connected to a live Google Search index. "
        f"Perform an exhaustive web search for active job vacancies matching the parameters below. "
        f"CRITICAL: Do not simulate, guess, or synthesize data. Only return actual, active job listings "
        f"found via web tracking that have been live or active recently.\n\n"
        f"Search parameters:\n"
        f"- Core Role: {role}\n"
        f"- Geography: {city} (Focus strictly on tech parks: Nesco Goregaon, Hiranandani Powai, Mindspace Malad/Airoli, Millennium Business Park Mahape, RCP Ghansoli)\n"
        f"- Target CTC Constraint: {ctc}\n"
        f"- Experience Bracket: {experience}\n\n"
        f"For every single listing, extract their corporate talent acquisition or direct career contact email address. "
        f"If the email cannot be found on the public job posting page, output 'None Found' for that field."
    )

    target_model = "gemini-3.5-flash"
    print(f"Querying Gemini API (using {target_model}) with live web grounding enabled...\n")

    try:
        # 3. Invoke content generator with the updated 'google_search' tool key
        response = client.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # Correct tool initialization syntax
                tools=[{"google_search": {}}],
                response_mime_type="application/json",
                response_schema=JobSearchPayload,
                temperature=0.0,
                max_output_tokens=2500 # Slightly bumped to avoid broken JSON chops
            )
        )

        # 4. Handle and print the strictly formatted JSON data payload
        json_data = json.loads(response.text)
        print(f"=== STRICT LIVE DATA DETECTED FOR: {role} in {city} ===")
        print(json.dumps(json_data, indent=2))
        print("=================================================================")

        # 5. FIXED: Correctly pathing candidate array index to fetch metadata safely
        if response.candidates and len(response.candidates) > 0:
            first_candidate = response.candidates[0]
            if hasattr(first_candidate, 'grounding_metadata') and first_candidate.grounding_metadata:
                metadata = first_candidate.grounding_metadata
                if hasattr(metadata, 'web_search_queries') and metadata.web_search_queries:
                    print("\nVerified Search Grounding Routes Utilized:")
                    for query in metadata.web_search_queries:
                        print(f" -> {query}")

    except Exception as e:
        print(f"Operational pipeline execution failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    target_role = "Python Developer"
    target_city = "Mumbai"
    target_ctc = "4-8 LPA"
    target_experience = "2-3 years"
    taget_number_toappy in comapnyt = "10"# data of 10 comapnitng liting --
    addtion_note="" # optional here user can provide additional note data relalted to serach waht he want to gibe

# we need vary close or eact what user want job to be applied on baesed on user sharead data 

    execution_data = [target_role, target_city, target_ctc, target_experience]
    fetch_strict_live_jobs(execution_data)
