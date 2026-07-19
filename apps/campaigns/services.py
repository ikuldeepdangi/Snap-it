import os
import json
import logging
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from typing import List
from .models import Company, Campaign

logger = logging.getLogger(__name__)

class JobOpening(BaseModel):
    company_name: str = Field(description="Exact legal or operating name of the hiring entity.")
    tech_park_location: str = Field(description="The specific IT park, SEZ, or corporate node in the city.")
    role_designation: str = Field(description="The formal corporate job title.")
    experience_required: str = Field(description="Required experience interval stated in the live posting.")
    inferred_ctc_lpa: str = Field(description="Salary range or 'Not Disclosed' explicitly mapped from the post.")
    core_technical_skills: List[str] = Field(description="List of primary technical stacks mentioned.")
    hr_or_hiring_email: str = Field(description="Direct corporate recruiter email, talent acquisition alias, or official careers email route. If explicitly missing, set value to 'None Found'.")
    source_reference_url: str = Field(description="A highly specific search query or job platform route string indicating where this live listing exists.")

class JobSearchPayload(BaseModel):
    active_listings: List[JobOpening]

class CampaignGeneratorService:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.paid_api_key = os.environ.get("GEMINI_API_KEY_PAID") or self.api_key
        self.model_name = "gemini-3.5-flash"
        self.normal_client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.paid_client = genai.Client(api_key=self.paid_api_key) if self.paid_api_key else None

    def generate_targets(self, target_city: str, target_tech: str, salary_threshold: str, experience_tier: str, max_companies: int = 10, use_grounding: bool = True, user=None, campaign_name: str = None, additional_notes: str = "") -> List[dict]:
        
        # Get previously targeted companies for this user to avoid duplicates
        existing_companies = []
        if user:
            existing_companies = list(Company.objects.filter(campaign__user=user).values_list('name', flat=True).distinct())
        
        exclusions_text = ""
        if existing_companies:
            # Pass up to 50 companies to avoid huge token usage
            exclusions_text = f"- EXCLUDE the following companies as they are already targeted: {', '.join(existing_companies[:50])}\n"

        new_campaign = Campaign.objects.create(
            user=user,
            name=campaign_name,
            city=target_city,
            tech=target_tech,
            experience=experience_tier,
            salary=salary_threshold
        )

        prompt = (
            f"You are a strict data-extraction engine connected to a live Google Search index. "
            f"Perform an exhaustive web search for active job vacancies matching the parameters below. "
            f"CRITICAL: Do not simulate, guess, or synthesize data. Only return actual, active job listings "
            f"found via web tracking that have been live or active recently.\n\n"
            f"Search parameters:\n"
            f"- Core Role/Tech: {target_tech}\n"
            f"- Geography: {target_city} (Focus strictly on tech parks if applicable)\n"
            f"- Target CTC Constraint: {salary_threshold}\n"
            f"- Experience Bracket: {experience_tier}\n"
            f"- Number of listings to find: At least {max_companies}\n"
            f"- Additional Search Constraints: {additional_notes if additional_notes else 'None'}\n"
            f"{exclusions_text}\n"
            f"For every single listing, extract their corporate talent acquisition or direct career contact email address. "
            f"If the email cannot be found on the public job posting page, output 'None Found' for that field."
        )

        logger.info(f"Querying Gemini API (using {self.model_name}), use_grounding={use_grounding}...")

        saved_objects = []

        try:
            # Choose client and tools based on whether we use grounding (paid) or not
            client = self.paid_client if use_grounding else self.normal_client
            if not client:
                raise ValueError("API key not configured for the requested operation.")

            config_args = {
                "response_mime_type": "application/json",
                "response_schema": JobSearchPayload,
                "temperature": 0.0,
                "max_output_tokens": 8192
            }
            if use_grounding:
                config_args["tools"] = [{"google_search": {}}]

            # Invoke content generator
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(**config_args)
            )

            raw_text = response.text
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()
            
            try:
                json_data = json.loads(raw_text)
            except json.JSONDecodeError as jde:
                logger.error(f"JSON decode failed. Raw response: {raw_text}")
                raise jde
            
            listings = json_data.get('active_listings', [])
            
            existing_lower = {c.lower() for c in existing_companies}
            added_count = 0
            
            for listing in listings:
                if added_count >= max_companies:
                    break
                    
                company_name = listing.get('company_name', 'Unknown')
                
                # Skip if already exists in DB
                if company_name.lower() in existing_lower:
                    continue
                    
                hr_email = listing.get('hr_or_hiring_email')
                if hr_email and hr_email.lower() == 'none found':
                    hr_email = None

                tech_skills = ", ".join(listing.get('core_technical_skills', []))
                
                campaign_obj = Company.objects.create(
                    campaign=new_campaign,
                    name=company_name,
                    website=listing.get('source_reference_url'),
                    hr_email=hr_email,
                    location=f"{target_city} - {listing.get('tech_park_location', '')}",
                    evidence_url=listing.get('source_reference_url'),
                    campaign_status='PENDING',
                    confidence_score=100, 
                    tech_score=100, 
                    is_hiring=True,
                    verification_reason=f"Role: {listing.get('role_designation')}, CTC: {listing.get('inferred_ctc_lpa')}, Exp: {listing.get('experience_required')}, Tech: {tech_skills}",
                    is_verified=True
                )
                saved_objects.append(campaign_obj)
                added_count += 1

        except Exception as e:
            logger.error(f"Operational pipeline execution failed: {e}")

        return saved_objects
