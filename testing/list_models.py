import os
from dotenv import load_dotenv
from google import genai

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env')))
client = genai.Client()
for m in client.models.list():
    print(m.name)
