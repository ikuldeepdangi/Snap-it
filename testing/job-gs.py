import os
import sys
import json
from dotenv import load_dotenv
from google import genai  
from google.genai import types  
from pydantic import BaseModel, Field

# Ensure standard terminal output handles special characters smoothly on Windows
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# 1. ENHANCED: Pydantic schema enforcing email extraction alongside metadata
class JobOpening(BaseModel):
    company_name: str = Field(description="Exact legal or operating name of the hiring entity.")
    tech_park_location: str = Field(description="The specific IT park, SEZ, or corporate node in Mumbai (e.g., Nesco, Mindspace, Hiranandani, MBP).")
    role_designation: str = Field(description="The formal corporate job title.")
    experience_required: str = Field(description="Required experience interval stated in the live posting.")
    inferred_ctc_lpa: str = Field(description="Salary range or 'Not Disclosed' explicitly mapped from the post.")
    core_technical_skills: list[str] = Field(description="List of primary technical stacks mentioned (e.g., FastAPI, Django, LLM, AWS).")
    hr_or_hiring_email: str = Field(description="Direct corporate recruiter email, talent acquisition alias, or official careers email route (e.g. careers@company.com). Do not leave blank.")
    source_reference_url: str = Field(description="A highly specific search query or job platform route string indicating where this live listing exists.")

class JobSearchPayload(BaseModel):
    active_listings: list[JobOpening]

def fetch_strict_live_jobs(user_data):
    if not os.environ.get("GEMINI_API_KEY"):
        print("Fatal Error: GEMINI_API_KEY is missing from environment.", file=sys.stderr)
        sys.exit(1)

    print("Initializing Strict Gemini Grounded Client...")
    client = genai.Client()

    role, city, ctc, experience = user_data

    # 2. ENHANCED: Explicitly instructing the tool to fetch direct corporate emails
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
        f"Extract all parameters cleanly into the requested structural JSON object."
    )

    # Pointing to the current active stable production model
    target_model = "gemini-3.5-flash"
    print(f"Querying Gemini API (using {target_model}) with live web grounding enabled...")

    try:
        # 3. Invoke the content generator using optimal deterministic parameters
        response = client.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # Enable Google Search Grounding for live web queries
                tools=[types.Tool(google_search=types.GoogleSearch())],
                # Force structured JSON parsing matching our strict schema
                response_mime_type="application/json",
                response_schema=JobSearchPayload,
                # Force zero randomness for high factual precision
                temperature=0.0,
                max_output_tokens=2000
            )
        )

        # 4. Handle and print the strictly formatted JSON data payload
        json_data = json.loads(response.text)
        print(f"\n=== STRICT LIVE DATA DETECTED FOR: {role} in {city} ===")
        print(json.dumps(json_data, indent=2))
        print("=================================================================")

        # Trace the specific source strings utilized to populate the response
        if response.candidates[0].grounding_metadata.web_search_queries:
            print("\nVerified Search Grounding Routes Utilized:")
            for query in response.candidates[0].grounding_metadata.web_search_queries:
                print(f" -> {query}")

    except Exception as e:
        print(f"Operational pipeline execution failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    # Parameters defining execution payload
    target_role = "Python Developer"
    target_city = "Mumbai"
    target_ctc = "4-8 LPA"
    target_experience = "2-3 years"

    execution_data = [target_role, target_city, target_ctc, target_experience]
    fetch_strict_live_jobs(execution_data)