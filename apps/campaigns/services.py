import os
import json
import logging
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from typing import List, Optional
from .models import Company, Campaign

logger = logging.getLogger(__name__)

class JobOpening(BaseModel):
    company_name: str = Field(description="Company name")
    verified_hr_email: Optional[str] = Field(description="CRITICAL: Direct corporate recruiter, HR, or careers email address. Must search deeply.")
    source_url: str = Field(description="Source URL of job listing")

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
            f"You are a strict data parser connected to a live Google Search index. "
            f"Search for active {target_tech} roles in {target_city} focusing on listings that explicitly display contact emails. "
            f"CRITICAL: Do not write conversational prose, notes, or explanations. "
            f"Only return a raw, compressed JSON block containing exactly three fields: "
            f"company_name, verified_hr_email, and source_url. "
            f"STRICT RULE: If you cannot find a verified HR or careers email for a company, YOU MUST EXCLUDE that company from the list entirely. ONLY return companies where you successfully extracted an email address.\n\n"
            f"Search parameters:\n"
            f"- Target CTC Constraint: {salary_threshold}\n"
            f"- Experience Bracket: {experience_tier}\n"
            f"- Number of listings to find: At least {max_companies}\n"
            f"- Additional Search Constraints: {additional_notes if additional_notes else 'None'}\n"
            f"{exclusions_text}\n"
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
            new_campaign.ai_response_payload = raw_text
            new_campaign.save()

            print("\n" + "=" * 60)
            print("       PAID AI MODE RESPONSE PAYLOAD RECEIVED")
            print("=" * 60)
            print(raw_text)
            print("=" * 60 + "\n")

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
                    
                hr_email = listing.get('verified_hr_email')
                
                campaign_obj = Company.objects.create(
                    campaign=new_campaign,
                    name=company_name,
                    website=listing.get('source_url'),
                    hr_email=hr_email,
                    location=target_city,
                    evidence_url=listing.get('source_url'),
                    campaign_status='PENDING',
                    confidence_score=100, 
                    tech_score=100, 
                    is_hiring=True,
                    verification_reason=f"Matched: {target_tech} role in {target_city}",
                    is_verified=True
                )
                saved_objects.append(campaign_obj)
                added_count += 1

        except Exception as e:
            logger.error(f"Operational pipeline execution failed: {e}")

        return saved_objects
