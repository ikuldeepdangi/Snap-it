from django.core.management.base import BaseCommand
from apps.campaigns.services import CampaignGeneratorService

class Command(BaseCommand):
    help = 'Generate outreach campaign targets using Gemini.'

    def add_arguments(self, parser):
        parser.add_argument('--city', type=str, required=True, help='Target city (e.g. "Indore, Madhya Pradesh, India")')
        parser.add_argument('--tech', type=str, required=True, help='Target tech stack (e.g. "Python")')
        parser.add_argument('--salary', type=str, required=True, help='Salary threshold (e.g. "₹8 LPA")')
        parser.add_argument('--experience', type=str, required=True, help='Experience tier (e.g. "2 years")')
        parser.add_argument('--max-companies', type=int, default=10, help='Maximum number of companies to generate')

    def handle(self, *args, **options):
        self.stdout.write("Initializing Campaign Generator...")
        service = CampaignGeneratorService()
        
        self.stdout.write(f"Parameters: City={options['city']}, Tech={options['tech']}, "
                          f"Salary={options['salary']}, Experience={options['experience']}")
        
        results = service.generate_targets(
            target_city=options['city'],
            target_tech=options['tech'],
            salary_threshold=options['salary'],
            experience_tier=options['experience'],
            max_companies=options['max_companies']
        )
        
        self.stdout.write(self.style.SUCCESS(f"Successfully generated and saved {len(results)} valid campaign targets!"))
        for target in results:
            self.stdout.write(f" - {target.company_name} ({target.primary_recipient_hr})")
