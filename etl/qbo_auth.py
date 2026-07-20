"""
qbo_auth.py
Handles QBO OAuth 2.0 token refresh.
Called at the start of every ETL run to obtain a fresh access token.
"""

import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

QBO_TOKEN_ENDPOINT = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

def get_access_token() -> str:
    """
    Exchange the refresh token for a fresh access token.
    Returns the access token string.
    Raises an exception with a clear message if the refresh fails.

    The access token is valid for 60 minutes.
    This function is called at the start of every ETL run —
    never cache the access token between runs.
    """
    client_id     = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")
    refresh_token = os.getenv("QBO_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise EnvironmentError(
            "QBO credentials not found in environment. "
            "Check QBO_CLIENT_ID, QBO_CLIENT_SECRET, and QBO_REFRESH_TOKEN in .env"
        )

    # Encode credentials as Base64 for Basic Auth header
    credentials = f"{client_id}:{client_secret}"
    encoded     = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type":  "application/x-www-form-urlencoded",
        "Accept":        "application/json",
    }

    payload = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }

    response = requests.post(QBO_TOKEN_ENDPOINT, headers=headers, data=payload)

    if response.status_code != 200:
        raise ConnectionError(
            f"Token refresh failed. Status: {response.status_code}. "
            f"Response: {response.text}\n"
            f"If status is 400 or 401, the refresh token may have expired. "
            f"Repeat the OAuth handshake (Workshop 5, Step 5.4) and update QBO_REFRESH_TOKEN."
        )

    token_data   = response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise ValueError(
            f"Token response did not contain access_token. Full response: {token_data}"
        )

    return access_token


if __name__ == "__main__":
    # Quick verification — run this file directly to test the token refresh
    print("Testing QBO token refresh...")
    token = get_access_token()
    print(f"Success. Access token obtained (first 40 chars): {token[:40]}...")