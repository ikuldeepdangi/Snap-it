import os
import urllib.parse
import requests

def get_google_auth_url(redirect_uri: str, request_gmail: bool = False) -> str:
    """Construct the authorization URL."""
    client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
    scope = "email profile"
    if request_gmail:
        scope += " https://www.googleapis.com/auth/gmail.send"
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    }
    if request_gmail:
        params["include_granted_scopes"] = "true"
        
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return url

def exchange_code_for_tokens(auth_code: str, redirect_uri: str) -> dict:
    """Deliver POST handshake to trade the redirect code for Google refresh tokens."""
    client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')
    
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

def refresh_access_token(refresh_token: str) -> dict:
    """Use the refresh token to get a new access token."""
    client_id = os.getenv('GOOGLE_OAUTH_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')
    
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    
    response = requests.post("https://oauth2.googleapis.com/token", data=data)
    response.raise_for_status()
    return response.json()
