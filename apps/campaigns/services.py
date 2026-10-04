import os
import json
import logging
import re
from typing import List, Optional, Set
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Models & Validation
# ---------------------------------------------------------------------------
class TargetCompany(BaseModel):
    name: str = Field(description="Official company name")
    job_title: str = Field(description="Active hiring title or position")
    hr_email: str = Field(description="Verified recruiter, careers, or HR email")
    careers_url: str = Field(description="Direct URL to career portal or job post")
    city: str = Field(description="Job location or Remote")

 

INVALID_EMAIL_DOMAINS = {
    "example.com", "company.com", "email.com", "yourcompany.com",
    "domain.com", "test.com", "google.com", "linkedin.com"
}

def is_valid_hr_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    if domain in INVALID_EMAIL_DOMAINS:
        return False
    return True


# ---------------------------------------------------------------------------
# 2. Resilient JSON Extractor
# ---------------------------------------------------------------------------
def extract_json_from_response(raw_text: str) -> list:
    """Parses JSON arrays from plain text or markdown code fences."""
    if not raw_text or not isinstance(raw_text, str):
        return []
    clean_text = raw_text.strip()
    if clean_text.startswith("```"):
        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.MULTILINE)
        clean_text = re.sub(r"\s*```$", "", clean_text, flags=re.MULTILINE)
        clean_text = clean_text.strip()

    match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", clean_text)
    if match:
        clean_text = match.group(1)

    # Clean trailing commas inside JSON
    clean_text = re.sub(r",\s*([\]}])", r"\1", clean_text)

    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError:
        objs = re.findall(r"\{[^{}]*\}", clean_text)
        parsed = []
        for obj_str in objs:
            try:
                obj_str_clean = re.sub(r",\s*([\]}])", r"\1", obj_str)
                parsed.append(json.loads(obj_str_clean))
            except Exception:
                continue

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("targets", parsed.get("companies", parsed.get("jobs", [])))
    return []


# ---------------------------------------------------------------------------
# 3. Grounded Discovery Service
# ---------------------------------------------------------------------------
class CampaignGeneratorService:
    def __init__(self, api_key: Optional[str] = None):
        active_api_key = (
            api_key
            or getattr(settings, "GEMINI_API_KEY_PAID", None)
            or getattr(settings, "GEMINI_API_KEY", None)
            or os.getenv("GEMINI_API_KEY_PAID")
            or os.getenv("GEMINI_API_KEY")
        )
        if not active_api_key:
            raise ValueError("GEMINI_API_KEY environment variable or Django setting is not configured.")
        self.client = genai.Client(api_key=active_api_key)
        self.model = getattr(settings, "GEMINI_MODEL_NAME", None) or os.getenv("GEMINI_MODEL_NAME", "gemini-3.8-flash")

    def _get_search_angle(self, angle_idx: int, tech_stack: str, city: str) -> str:
        angles = [
            f"active job postings and LinkedIn hiring announcements for {tech_stack} in {city} with recruiter HR contact email careers jobs hr",
            f"software startups and tech firms hiring {tech_stack} in {city} listing talent acquisition application email",
        ]
        return angles[angle_idx % len(angles)]

    def _fetch_grounded_batch(
        self,
        tech_stack: str,
        city: str,
        experience_tier: str,
        batch_size: int,
        exclusions: Set[str],
        angle_idx: int,
    ) -> tuple[List[dict], dict]:
        excluded_str = ", ".join(list(exclusions)[:25]) if exclusions else "None"
        angle_keyword = self._get_search_angle(angle_idx, tech_stack, city)

        prompt = f"""
Search Google live web index to find active job openings using this focus: {angle_keyword}

TARGET:
Find {batch_size} different companies actively hiring for '{tech_stack}' in '{city}' (or Remote) suitable for '{experience_tier}' experience.
Do NOT include any of these companies: {excluded_str}.

RULES:
1. Every company MUST include a real recruiter or hiring email (e.g., careers@..., hr@..., jobs@..., or recruiter personal email).
2. Skip companies without a real email; do not invent or guess fake emails like recruiter@company.com or example.com.
3. Provide the direct link to the posting or career page.
4. Output ONLY a valid raw JSON array in this exact schema:
[
  {{
    "name": "Company Name",
    "job_title": "Position Title",
    "hr_email": "recruiter@company.com",
    "careers_url": "https://company.com/careers/job",
    "city": "{city}"
  }}
]
"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=1.0,
                max_output_tokens=2048,
            ),
        )

        raw_text = None
        if getattr(response, "text", None):
            raw_text = response.text
        elif getattr(response, "candidates", None) and response.candidates and getattr(response.candidates[0], "content", None):
            parts = getattr(response.candidates[0].content, "parts", None)
            if parts:
                for part in parts:
                    if getattr(part, "text", None):
                        raw_text = part.text
                        break

        if not raw_text or not raw_text.strip():
            raise ValueError("Grounding returned empty text candidate.")

        raw_items = extract_json_from_response(raw_text)
        validated: List[dict] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            hr_email = item.get("hr_email", "")
            if not is_valid_hr_email(str(hr_email)):
                continue
            try:
                target = TargetCompany(**item)
                validated.append(target.model_dump())
            except Exception:
                continue

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        candidate_tokens = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        total_tokens = (getattr(usage, "total_token_count", 0) or (prompt_tokens + candidate_tokens)) if usage else 0

        metrics = {
            "prompt_tokens": prompt_tokens,
            "candidate_tokens": candidate_tokens,
            "total_tokens": total_tokens,
        }
        return validated, metrics

    def generate_targets(
        self,
        tech_stack: str = "",
        city: str = "",
        experience_tier: str = "",
        target_count: int = 12,
        exclusions: Optional[List[str]] = None,
        target_tech: Optional[str] = None,
        target_city: Optional[str] = None,
        max_companies: Optional[int] = None,
        salary_threshold: str = "",
        user=None,
        campaign_name: str = None,
        additional_notes: str = "",
    ) -> List[dict]:
        actual_tech = tech_stack or target_tech or "Software Engineer"
        actual_city = city or target_city or "Remote"
        actual_count = target_count if target_count != 12 else (max_companies or 12)

        collected_targets: List[dict] = []
        seen_companies: Set[str] = {c.strip().lower() for c in (exclusions or [])}

        CHUNK_SIZE = 12
        MAX_LOOPS = 2  # Hard cap
        loop = 0

        while len(collected_targets) < actual_count and loop < MAX_LOOPS:
            needed = actual_count - len(collected_targets)
            batch_size = min(needed, CHUNK_SIZE)

            try:
                batch_results, _ = self._fetch_grounded_batch(
                    tech_stack=actual_tech,
                    city=actual_city,
                    experience_tier=experience_tier,
                    batch_size=batch_size,
                    exclusions=seen_companies,
                    angle_idx=loop,
                )

                new_leads = 0
                for lead in batch_results:
                    comp_key = lead["name"].strip().lower()
                    if comp_key not in seen_companies:
                        seen_companies.add(comp_key)
                        collected_targets.append(lead)
                        new_leads += 1
                        if len(collected_targets) >= actual_count:
                            break

                if new_leads == 0:
                    logger.info("Zero new leads returned; breaking early to prevent bill accumulation.")
                    break

            except Exception as err:
                logger.warning(f"Grounded discovery loop {loop + 1} issue: {err}")

            loop += 1

        return collected_targets
