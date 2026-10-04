from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.campaigns.models import Campaign, Company
from apps.campaigns.services import CampaignGeneratorService, extract_json_from_response, is_valid_hr_email
from apps.campaigns.tasks import generate_campaign_targets_task


class CampaignServiceTest(TestCase):
    def test_email_validation(self):
        self.assertTrue(is_valid_hr_email("careers@acme.com"))
        self.assertTrue(is_valid_hr_email("hr@techcorp.io"))
        self.assertFalse(is_valid_hr_email("recruiter@company.com"))
        self.assertFalse(is_valid_hr_email("invalid_email_format"))

    def test_extract_json_from_response(self):
        raw_markdown = """```json
        [
            {
                "name": "Acme Inc",
                "job_title": "Node.js Developer",
                "hr_email": "careers@acme.com",
                "careers_url": "https://acme.com/careers",
                "city": "Bangalore"
            }
        ]
        ```"""
        extracted = extract_json_from_response(raw_markdown)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["name"], "Acme Inc")

    @patch.object(CampaignGeneratorService, "_fetch_grounded_batch")
    def test_generate_targets(self, mock_batch):
        mock_batch.return_value = (
            [
                {
                    "name": "Acme Corp",
                    "job_title": "Node.js Developer",
                    "hr_email": "jobs@acme.com",
                    "careers_url": "https://acme.com/jobs",
                    "city": "Bangalore"
                }
            ],
            {"prompt_tokens": 100, "candidate_tokens": 50, "total_tokens": 150}
        )

        service = CampaignGeneratorService(api_key="mock_key")
        results = service.generate_targets(
            tech_stack="Node.js Developer",
            city="Bangalore",
            target_count=1
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Acme Corp")


class CampaignTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.campaign = Campaign.objects.create(
            user=self.user,
            name="Node.js Hiring",
            city="Bangalore",
            tech="Node.js",
            status="PENDING"
        )

    @patch.object(CampaignGeneratorService, "generate_targets")
    def test_generate_campaign_targets_task(self, mock_generate):
        mock_generate.return_value = [
            {
                "name": "Test Company",
                "job_title": "Node.js Developer",
                "hr_email": "careers@testcompany.com",
                "careers_url": "https://testcompany.com/careers",
                "city": "Bangalore"
            }
        ]

        success = generate_campaign_targets_task(self.campaign.id)
        self.assertTrue(success)

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, "READY")
        self.assertEqual(Company.objects.filter(campaign=self.campaign).count(), 1)


class CampaignViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client = Client()
        self.client.login(username="testuser", password="password")

    @patch("apps.campaigns.views.generate_campaign_targets_task")
    def test_generate_campaign_api(self, mock_task):
        response = self.client.post(
            reverse("campaigns:generate"),
            {
                "target_city": "Bangalore",
                "tech_stack": "Node.js Developer",
                "target_count": "5"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "PENDING")
        self.assertTrue(Campaign.objects.filter(id=data["campaign_id"]).exists())
