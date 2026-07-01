import os
import requests
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Sets the Telegram Webhook to point to the production server URL.'

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='The base URL of your Railway application (e.g. https://snapit-production.up.railway.app)')

    def handle(self, *args, **options):
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            self.stderr.write(self.style.ERROR("Missing TELEGRAM_BOT_TOKEN environment variable."))
            return

        base_url = options['url'].rstrip('/')
        webhook_url = f"{base_url}/bot/webhook/"

        self.stdout.write(f"Setting webhook to: {webhook_url}")

        api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        response = requests.post(api_url, data={'url': webhook_url})
        
        if response.status_code == 200 and response.json().get('ok'):
            self.stdout.write(self.style.SUCCESS(f"Successfully set webhook: {response.json().get('description')}"))
        else:
            self.stderr.write(self.style.ERROR(f"Failed to set webhook: {response.text}"))
