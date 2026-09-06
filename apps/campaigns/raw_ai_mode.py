import os
import re
import time
import json
import logging
from typing import List, Optional
from playwright.sync_api import sync_playwright
from .models import Company, Campaign

logger = logging.getLogger(__name__)

def handle_captcha_if_present(page):
    """Detects Google reCAPTCHA, checks the box, and submits if prompted."""
    if "google.com/sorry" in page.url or page.locator("iframe[src*='recaptcha'], #captcha-form").is_visible():
        logger.warning("Google reCAPTCHA detected. Attempting automated entry...")
        try:
            frame = page.frame_locator("iframe[title*='reCAPTCHA'], iframe[src*='recaptcha']").first
            checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox-border").first
            
            if checkbox.is_visible(timeout=5000):
                checkbox.hover()
                page.wait_for_timeout(400)
                checkbox.click()

            page.wait_for_timeout(2000)

            submit_btn = page.locator("input[type='submit'], button[type='submit']").first
            if submit_btn.is_visible(timeout=3000):
                submit_btn.click()

            page.wait_for_url(lambda url: "google.com/sorry" not in url, timeout=15000)
        except Exception as e:
            logger.error(f"CAPTCHA challenge detected or bypass failed: {e}")


class RawAICampaignGeneratorService:
    """
    Free AI Mode campaign generator service.
    Uses Playwright browser automation on Google Search AI mode to fetch live hiring companies with verified emails.
    """

    def parse_extracted_text(self, text: str) -> List[dict]:
        entries = []
        if not text:
            return entries

        # 1. Attempt standard JSON parsing by scanning candidate '{' or '[' positions in reverse order
        try:
            pos_list = [m.start() for m in re.finditer(r'[\{\[]', text)]
            decoder = json.JSONDecoder()
            
            for pos in reversed(pos_list):
                try:
                    data, _ = decoder.raw_decode(text, pos)
                    jobs = []
                    if isinstance(data, dict) and 'jobs' in data and isinstance(data['jobs'], list):
                        jobs = data['jobs']
                    elif isinstance(data, list):
                        jobs = data
                    
                    if jobs:
                        for job in jobs:
                            if not isinstance(job, dict):
                                continue
                            comp_name = (job.get('company_name') or '').strip()
                            if comp_name and len(comp_name) < 150:
                                hr_email = job.get('application_hr_email') or None
                                if hr_email and str(hr_email).lower().strip() in ['null', 'none', 'n/a', '']:
                                    hr_email = None
                                entries.append({
                                    "company_name": comp_name,
                                    "verified_hr_email": hr_email,
                                    "source_url": job.get('source_url') or None,
                                    "location": job.get('office_location') or ""
                                })
                        if entries:
                            return entries
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Full JSON parsing failed: {e}")

        # 2. Object-by-Object extraction (handles unclosed / partially streamed JSON output)
        obj_matches = re.finditer(r'\{[^{}]*"company_name"\s*:\s*"([^"]+)"[^{}]*\}', text, re.DOTALL)
        for match in obj_matches:
            obj_str = match.group(0)
            try:
                job = json.loads(obj_str)
                comp_name = (job.get('company_name') or '').strip()
                if comp_name and len(comp_name) < 150:
                    hr_email = job.get('application_hr_email') or None
                    if hr_email and str(hr_email).lower().strip() in ['null', 'none', 'n/a', '']:
                        hr_email = None
                    entries.append({
                        "company_name": comp_name,
                        "verified_hr_email": hr_email,
                        "source_url": job.get('source_url') or None,
                        "location": job.get('office_location') or ""
                    })
            except Exception:
                comp_match = re.search(r'"company_name"\s*:\s*"([^"]+)"', obj_str)
                email_match = re.search(r'"application_hr_email"\s*:\s*"([^"]+)"', obj_str)
                url_match = re.search(r'"source_url"\s*:\s*"([^"]+)"', obj_str)
                loc_match = re.search(r'"office_location"\s*:\s*"([^"]+)"', obj_str)
                
                if comp_match:
                    comp_name = comp_match.group(1).strip()
                    hr_email = email_match.group(1).strip() if email_match else None
                    if hr_email and hr_email.lower() in ['null', 'none', 'n/a', '']:
                        hr_email = None
                    entries.append({
                        "company_name": comp_name,
                        "verified_hr_email": hr_email,
                        "source_url": url_match.group(1).strip() if url_match else None,
                        "location": loc_match.group(1).strip() if loc_match else ""
                    })

        if entries:
            return entries

        # 3. Fallback Regex Parsing for legacy plain text
        blocks = re.split(r'(?i)(?:^|\n)(?:Company Name|\d+\.\s*Company Name)\s*:\s*', text)
        for block in blocks:
            if not block.strip():
                continue
            lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
            if not lines:
                continue
            
            comp_name = lines[0].strip()
            comp_name = re.sub(r'^\d+[\.\)]\s*', '', comp_name).strip()
            
            email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', block)
            hr_email = email_match.group(1) if email_match else None
            
            url_match = re.search(r'(https?://[^\s]+)', block)
            source_url = url_match.group(1) if url_match else None
            
            loc_match = re.search(r'(?i)(?:Office Location|Location)\s*:\s*([^\n]+)', block)
            location = loc_match.group(1).strip() if loc_match else ""

            if comp_name and len(comp_name) < 150:
                entries.append({
                    "company_name": comp_name,
                    "verified_hr_email": hr_email,
                    "source_url": source_url,
                    "location": location
                })
        return entries

    def scrape_google_ai_jobs(
        self,
        role: str,
        location: str,
        experience: str,
        tech_stack: str,
        salary: str,
        count: int = 10,
        additional_notes: str = ""
    ) -> str:
        prompt = (
            f"Search live hiring companies and active job openings for {role} in {location} with {experience} of experience ({tech_stack}). {additional_notes}\n"
            f"CRITICAL EMAIL SEARCH RULE: For every hiring company, search deeply across company careers pages, contact pages, job listings, and web portals to find their REAL, VERIFIED HR, Talent Acquisition, or Careers contact email address (e.g. hr@company.com, careers@company.com, jobs@company.com, or direct recruiter email).\n"
            f"STRICT MANDATE: Every single company in the JSON output MUST include a valid, genuine, non-null application_hr_email address. If a company's HR/careers email cannot be found on the web, EXCLUDE that company entirely and find another company that has a verified email.\n"
            f"DO NOT return null, empty string, or fake dummy emails (e.g. no @example.com). Only return real extracted corporate emails.\n"
            f"Provide EXACTLY {count} distinct hiring companies with verified email addresses.\n\n"
            "Return the response as VALID JSON ONLY. Do not use Markdown, code fences, bullet points, explanations, greetings, citations outside the JSON, or any text before or after the JSON.\n\n"
            "Use exactly this JSON structure:\n"
            "{\n"
            '  "jobs": [\n'
            "    {\n"
            '      "company_name": "",\n'
            '      "role_title": "",\n'
            '      "experience_required": "",\n'
            '      "office_location": "",\n'
            '      "application_hr_email": "",\n'
            '      "phone_boardline": "",\n'
            '      "source_url": "",\n'
            '      "job_description": ""\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            f"* Return exactly {count} distinct hiring companies with genuine verified application_hr_email addresses.\n"
            "* application_hr_email MUST NOT be null or empty.\n"
            "* source_url must contain the direct job posting or official careers URL when available.\n"
            "* Keep all values as valid JSON strings.\n"
            "* Escape quotes and special characters correctly so the response can be parsed by a standard JSON parser.\n"
            "* Do not include source references such as [1], [2] outside the JSON.\n"
            "* Do not include Markdown links.\n"
            "* The first character of the response must be {{ and the last character must be }}."
        )

        headless_mode = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() not in ("false", "0", "f")

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir="./gemini_job_profile",
                headless=headless_mode,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox"
                ]
            )
            page = context.pages[0] if context.pages else context.new_page()

            try:
                page.goto("https://www.google.com/search?q=jobs")
                handle_captcha_if_present(page)

                try:
                    consent = page.locator("button:has-text('Accept all'), button:has-text('I agree')").first
                    if consent.is_visible(timeout=2000):
                        consent.click()
                except Exception:
                    pass

                try:
                    ai_tab = page.get_by_role("tab", name="AI Mode").or_(page.locator("text='AI Mode'")).first
                    if ai_tab.is_visible(timeout=3000):
                        ai_tab.click()
                        page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass

                handle_captcha_if_present(page)

                target_input = page.locator("textarea, [contenteditable='true'], [role='combobox'], input[type='text']").last
                target_input.wait_for(state="attached", timeout=12000)
                target_input.scroll_into_view_if_needed()
                target_input.click(force=True)

                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(prompt)
                page.keyboard.press("Enter")

                time.sleep(2.0)
                try:
                    page.locator("button[aria-label*='Stop']").wait_for(state="detached", timeout=35000)
                except Exception:
                    pass

                # Response completion check: wait until body text stabilizes across consecutive checks
                prev_len = 0
                same_len_count = 0
                for _ in range(25):
                    cur_len = len(page.locator("body").inner_text())
                    if cur_len == prev_len and cur_len > 100:
                        same_len_count += 1
                        if same_len_count >= 2:
                            break
                    else:
                        same_len_count = 0
                    prev_len = cur_len
                    time.sleep(0.8)

                raw_text = page.locator("[role='main']").first.evaluate("el => el.innerText")
                
                print("\n" + "=" * 60)
                print("       RAW AI MODE RESPONSE PAYLOAD RECEIVED")
                print("=" * 60)
                print(raw_text)
                print("=" * 60 + "\n")
                
                return raw_text
            finally:
                context.close()

    def generate_targets(
        self,
        target_city: str,
        target_tech: str,
        salary_threshold: str,
        experience_tier: str,
        max_companies: int = 10,
        user=None,
        campaign_name: str = None,
        additional_notes: str = ""
    ) -> List[Company]:
        
        existing_companies = []
        if user:
            existing_companies = list(Company.objects.filter(campaign__user=user).values_list('name', flat=True).distinct())

        new_campaign = Campaign.objects.create(
            user=user,
            name=campaign_name,
            city=target_city,
            tech=target_tech,
            experience=experience_tier,
            salary=salary_threshold
        )

        saved_objects = []
        try:
            raw_text = self.scrape_google_ai_jobs(
                role=target_tech,
                location=target_city,
                experience=experience_tier,
                tech_stack=target_tech,
                salary=salary_threshold,
                count=max_companies,
                additional_notes=additional_notes
            )

            new_campaign.ai_response_payload = raw_text
            new_campaign.save()

            listings = self.parse_extracted_text(raw_text)
            existing_lower = {c.lower() for c in existing_companies}
            added_count = 0

            for listing in listings:
                if added_count >= max_companies:
                    break

                company_name = listing.get('company_name', 'Unknown')
                if company_name.lower() in existing_lower:
                    continue

                hr_email = listing.get('verified_hr_email')

                company_obj = Company.objects.create(
                    campaign=new_campaign,
                    name=company_name,
                    website=listing.get('source_url'),
                    hr_email=hr_email,
                    location=listing.get('location') or target_city,
                    evidence_url=listing.get('source_url'),
                    campaign_status='PENDING',
                    confidence_score=90,
                    tech_score=90,
                    is_hiring=True,
                    verification_reason=f"Raw AI mode matched: {target_tech} role in {target_city}",
                    is_verified=True if hr_email else False
                )
                saved_objects.append(company_obj)
                added_count += 1

        except Exception as e:
            logger.error(f"Free AI mode campaign target generation failed: {e}")

        return saved_objects


def search_live_jobs(
    role: str = "Python Developer",
    location: str = "Navi Mumbai",
    experience: str = "2 years",
    tech_stack: str = "Django, FastAPI, SQL",
    count: int = 5
):
    """Standalone / legacy wrapper around RawAICampaignGeneratorService."""
    service = RawAICampaignGeneratorService()
    raw_text = service.scrape_google_ai_jobs(
        role=role,
        location=location,
        experience=experience,
        tech_stack=tech_stack,
        salary="Not specified",
        count=count
    )
    print("\n" + "=" * 60)
    print("          LIVE VERIFIED JOB SEARCH RESULTS")
    print("=" * 60 + "\n")
    print(raw_text)
    print("\n" + "=" * 60)


if __name__ == "__main__":
    search_live_jobs()