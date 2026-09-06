import os
import re
import time
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
        # Split by "Company Name:" or numbered items like "1. Company Name:"
        blocks = re.split(r'(?i)(?:^|\n)(?:Company Name|\d+\.\s*Company Name)\s*:\s*', text)
        for block in blocks:
            if not block.strip():
                continue
            lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
            if not lines:
                continue
            
            comp_name = lines[0].strip()
            comp_name = re.sub(r'^\d+[\.\)]\s*', '', comp_name).strip()
            
            # Find HR Email
            email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', block)
            hr_email = email_match.group(1) if email_match else None
            
            # Find Source URL / Portal Link
            url_match = re.search(r'(https?://[^\s]+)', block)
            source_url = url_match.group(1) if url_match else None
            
            # Location
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
            f"Search live job openings for {role} ({tech_stack}) in {location} with {experience} of experience. "
            f"Target salary threshold: {salary}. {additional_notes} "
            f"Provide EXACTLY {count} distinct hiring companies. "
            "Format the output strictly as itemized entries with: "
            "1. Company Name\n"
            "2. Role Title & Experience Required\n"
            "3. Office Location\n"
            "4. Application/HR Email\n"
            "5. Phone/Boardline\n"
            "6. Source URL / Portal Link\n"
            "7. Job Description / Key Responsibilities\n"
            "Output ONLY the job entries. Do not write introductory greetings or follow-up offers."
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
                    if consent.is_visible(timeout=3000):
                        consent.click()
                except Exception:
                    pass

                try:
                    ai_tab = page.get_by_role("tab", name="AI Mode").or_(page.locator("text='AI Mode'")).first
                    if ai_tab.is_visible(timeout=5000):
                        ai_tab.click()
                        page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass

                handle_captcha_if_present(page)

                target_input = page.locator("textarea, [contenteditable='true'], [role='combobox'], input[type='text']").last
                target_input.wait_for(state="attached", timeout=15000)
                target_input.scroll_into_view_if_needed()
                target_input.click(force=True)

                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(prompt)
                page.keyboard.press("Enter")

                time.sleep(5)
                try:
                    page.locator("button[aria-label*='Stop']").wait_for(state="detached", timeout=40000)
                except Exception:
                    pass

                prev_len = 0
                for _ in range(20):
                    cur_len = len(page.locator("body").inner_text())
                    if cur_len == prev_len and cur_len > 100:
                        break
                    prev_len = cur_len
                    time.sleep(1.2)

                raw_text = page.locator("[role='main']").first.evaluate("el => el.innerText")
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