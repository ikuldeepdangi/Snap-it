import os
import json
import logging
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from typing import List, Optional
from .models import TargetCompanyCampaign

logger = logging.getLogger(__name__)

class OptionalCcRouting(BaseModel):
    founder_or_c_level: Optional[str] = None
    engineering_manager_or_lead: Optional[str] = None
    senior_dev_or_team_node: Optional[str] = None

class ExactEvidenceUrls(BaseModel):
    hr_email_source_url: str
    cc_emails_source_url: Optional[str] = None

class CompanyTarget(BaseModel):
    company_name: str
    indore_office_location: Optional[str] = Field(default=None, alias="office_location") # alias for flexibility
    primary_recipient_to_hr: str
    optional_cc_routing: Optional[OptionalCcRouting] = None
    exact_evidence_urls: ExactEvidenceUrls
    proven_python_use_case: Optional[str] = None

class CampaignGeneratorService:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model_name = "gemini-3.5-flash"
        try:
            self.temperature = float(os.environ.get("GEMINI_API_TEMPERATURE", "0.0"))
        except ValueError:
            self.temperature = 0.0
            
        self.client = genai.Client(api_key=self.api_key)

    def _get_active_exclusions(self) -> List[str]:
        # Extract unique root domains
        return list(TargetCompanyCampaign.objects.values_list('root_domain', flat=True).distinct())

    def generate_targets(self, target_city: str, target_tech: str, salary_threshold: str, experience_tier: str, max_companies: int = 10, use_grounding: bool = True, user=None, campaign_name: str = None, campaign_inputs: dict = None) -> List[dict]:
        exclusions = self._get_active_exclusions()
        exclusion_string = ", ".join([f'"{domain}"' for domain in exclusions])

        system_instruction = f"""You are a precision web-scraping and data-verification engine operating with zero-tolerance for hallucinations or generic placeholders. Your single objective is to build a high-deliverability email outreach array for premium IT firms and software product houses operating in {target_city} that can support a minimum salary tier of {salary_threshold} for a {experience_tier} engineering profile matching the stack: {target_tech}.

        CRITICAL GROUNDING & VERIFICATION PROTOCOLS:
        1. TALENT ACQUISITION PRIORITY: You must aggressively prioritize specific hiring/recruiting mailboxes (look for prefixes like 'ta@', 'careers@', 'jobs@', or 'hiring@') over generic company footers (like 'contact@' or 'info@'). Search deeper into sub-career portals, active regional job postings (LinkedIn, Naukri company hubs), or press releases to extract human-resourced mailboxes.
        2. ZERO AUTO-GENERATION: Never guess or assemble email addresses based on patterns. If an address is not explicitly printed on a crawlable webpage, do not provide it. 
        3. OPTIONAL CC INTEGRITY: If individual executive emails (Founder, Tech Manager, or Engineering Lead) are not explicitly indexed on a public page, set those specific schema keys to null. Do not use generic fallbacks for CC fields. At minimum, each company object must contain at least one verified active HR or Hiring Team mailbox.
        4. DEEP-LINK EVIDENCE REQUIREMENT: The 'evidence_url' fields must provide the absolute, direct link (e.g., the specific job post, team layout page, or company directory node) where that exact email address text was extracted so the user can verify it. Do not just link to the main homepage root.
        5. CRITICAL DUPLICATION RESTRAINTS: You are strictly FORBIDDEN from including any companies that operate on the following root web domains: [{exclusion_string}]. Verify the root domain of every company you find during your live Google Search. If its domain matches any entry in this exclusion list, drop it immediately and look for an alternative company.
        6. FORMATTING: Output a pure JSON array starting with '[' and ending with ']'. No markdown codeblock wrappers (do not include ```json) or conversational prose."""

        user_prompt = f"""Generate a precision-verified JSON array of premium IT companies located in or around {target_city} that actively employ developers specialized in {target_tech}. 

        CRITICAL: You MUST output exactly {max_companies} objects matching the structural JSON schema below. Do not stop early. Do not default to 10. You must generate all {max_companies} items. Every email must be real, and you must include the exact deep-link proof URL where the contact network details or company domain information was found. Do not truncate the array with ellipses. Start directly with the opening bracket '['.

        [
        {{
            "company_name": "Exact Legal / Trade Name",
            "indore_office_location": "Verified Building Name, Tower, or IT Park Zone",
            "primary_recipient_to_hr": "real_talent_acquisition_or_careers_email",
            "optional_cc_routing": {{
            "founder_or_c_level": "only_if_explicitly_found_on_webpage_otherwise_null",
            "engineering_manager_or_lead": "only_if_explicitly_found_on_webpage_otherwise_null",
            "senior_dev_or_team_node": "only_if_explicitly_found_on_webpage_otherwise_null"
            }},
            "exact_evidence_urls": {{
            "hr_email_source_url": "https://domain.com/exact-deep-link-where-hr-email-is-printed",
            "cc_emails_source_url": "https://domain.com/exact-deep-link-or-public-directory-where-cc-found-or-null"
            }},
            "proven_python_use_case": "Specific framework or data architecture verified for this firm"
        }}
        ]"""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self.temperature,
            response_mime_type="application/json",
            tools=[{"google_search": {}}] if use_grounding else None,
        )

        target_model = self.model_name if use_grounding else "gemini-3.1-flash-lite"
        
        response = self.client.models.generate_content(
            model=target_model,
            contents=[user_prompt],
            config=config,
        )

        try:
            # Strip markdown just in case the model ignores the instruction
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            
            data = json.loads(raw_text.strip())
            saved_objects = []
            
            # Create the parent campaign
            from .models import Campaign
            new_campaign = Campaign.objects.create(
                user=user,
                campaign_name=campaign_name,
                campaign_inputs=campaign_inputs
            )
            
            for item in data:
                hr_email = item.get("primary_recipient_to_hr")
                if not hr_email:
                    logger.warning(f"Deduplication/Quality Triggered: Primary HR email is missing for {item.get('company_name')}.")
                    continue
                
                extracted_domain = hr_email.split('@')[-1].lower()
                
                # Check for fictional emails
                if "example.com" in extracted_domain or "domain.com" in extracted_domain:
                    logger.warning(f"Fictional data detected: {hr_email}. Dropping object.")
                    continue
                
                # Deduplication logic
                if TargetCompanyCampaign.objects.filter(root_domain=extracted_domain).exists():
                    logger.warning(f"Deduplication Triggered: Removed {extracted_domain} from active generation batch.")
                    continue
                
                optional_cc = item.get("optional_cc_routing", {})
                evidence_urls = item.get("exact_evidence_urls", {})
                
                campaign_obj = TargetCompanyCampaign.objects.create(
                    campaign=new_campaign,
                    company_name=item.get("company_name", "Unknown"),
                    root_domain=extracted_domain,
                    primary_recipient_hr=hr_email,
                    cc_founder=optional_cc.get("founder_or_c_level") if optional_cc else None,
                    cc_engineering_lead=optional_cc.get("engineering_manager_or_lead") if optional_cc else None,
                    cc_senior_dev=optional_cc.get("senior_dev_or_team_node") if optional_cc else None,
                    office_location=item.get("indore_office_location", ""),
                    target_tech_stack=target_tech,
                    evidence_url_hr=evidence_urls.get("hr_email_source_url", ""),
                    evidence_url_cc=evidence_urls.get("cc_emails_source_url"),
                    campaign_status='PENDING'
                )
                saved_objects.append(campaign_obj)
            
            return saved_objects
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Gemini: {e}. Raw response: {response.text}")
            return []
        except Exception as e:
            logger.error(f"Error processing Gemini response: {e}")
            return []
