import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN")
ngrok_url = os.getenv("BASE_URL")

if not token:
    print("No token")
    exit()

if not ngrok_url:
    # Use the one the user provided recently
    ngrok_url = "nonvacant-yu-intervertebrally.ngrok-free.dev"

if not ngrok_url.startswith("http"):
    ngrok_url = "https://" + ngrok_url

webhook_url = f"{ngrok_url}/telegram-integration/webhook/"

r = requests.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url": webhook_url})
print(r.json())
