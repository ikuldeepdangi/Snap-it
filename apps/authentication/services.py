import os
import urllib.parse
import requests

def get_google_auth_url() -> str:
    """Construct the authorization URL requesting gmail.send scope."""
    client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
    redirect_uri = "http://localhost:8000/auth/callback/"
    scope = "https://www.googleapis.com/auth/gmail.send email profile"
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return url

def exchange_code_for_tokens(auth_code: str) -> dict:
    """Deliver POST handshake to trade the redirect code for Google refresh tokens."""
    client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')
    redirect_uri = "http://localhost:8000/auth/callback/"
    
    data = {
        "code": auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    response = requests.post("https://oauth2.googleapis.com/token", data=data)
    response.raise_for_status()
    return response.json()
