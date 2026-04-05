"""Intégration Google Calendar — OAuth2 et synchronisation des événements."""
import base64
import hashlib
import secrets
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.config import settings
from app.models.calendar_account import CalendarAccount
from app.models.event import Event
from app.services.crypto import decrypt, encrypt

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "email",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
    }
}


def generate_pkce() -> tuple[str, str]:
    """Retourne (code_verifier, code_challenge) pour PKCE S256."""
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def get_auth_url(state: str, code_challenge: str) -> str:
    """Génère l'URL d'autorisation Google. Le code_challenge PKCE va dans l'URL."""
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, state=state)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return auth_url


def exchange_code(code: str, code_verifier: str) -> dict:
    """Échange le code OAuth contre les tokens d'accès."""
    import requests as req_lib
    from datetime import timezone

    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code, code_verifier=code_verifier)

    # Récupère le token depuis la session OAuth (plus fiable que creds.token)
    token = flow.oauth2session.token
    access_token = token["access_token"]
    refresh_token = token.get("refresh_token")
    expiry = token.get("expires_at")
    token_expiry = datetime.fromtimestamp(expiry, tz=timezone.utc) if expiry else None

    account_email = _get_user_email(access_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,
        "account_email": account_email,
    }


def _get_user_email(access_token: str) -> str:
    import requests as req_lib
    resp = req_lib.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("email", "")


def _refresh_if_needed(account: CalendarAccount) -> Credentials:
    creds = Credentials(
        token=decrypt(account.access_token),
        refresh_token=decrypt(account.refresh_token) if account.refresh_token else None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        account.access_token = encrypt(creds.token)
        if creds.expiry:
            account.token_expiry = creds.expiry
    return creds


def sync_events(account: CalendarAccount, db: Session) -> int:
    """Synchronise les événements Google Calendar en base. Retourne le nombre d'événements."""
    creds = _refresh_if_needed(account)
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)

    db.query(Event).filter(Event.calendar_id == account.id).delete()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            maxResults=500,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    count = 0
    for item in events_result.get("items", []):
        start_raw = item["start"].get("dateTime") or item["start"].get("date")
        end_raw = item["end"].get("dateTime") or item["end"].get("date")
        is_all_day = "date" in item["start"] and "dateTime" not in item["start"]

        start = _parse_dt(start_raw, is_all_day)
        end = _parse_dt(end_raw, is_all_day)
        if start is None or end is None:
            continue

        db.add(Event(
            calendar_id=account.id,
            external_event_id=item["id"],
            start_time=start,
            end_time=end,
            is_all_day=is_all_day,
        ))
        count += 1

    account.last_synced = now
    db.commit()
    return count


def _parse_dt(value: str, is_all_day: bool) -> datetime | None:
    try:
        if is_all_day:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value)
    except Exception:
        return None
