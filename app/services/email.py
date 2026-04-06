"""Envoi d'emails via Resend avec invitation .ics en pièce jointe."""
import base64
from datetime import datetime

from app.config import settings
from app.services.ics_export import generate_ics


def send_invite(
    to_emails: list[str],
    organizer_email: str,
    start: datetime,
    end: datetime,
    title: str = "Réunion",
) -> bool:
    """
    Envoie une invitation calendrier par email avec le .ics en pièce jointe.
    Retourne True si l'envoi a réussi.
    """
    if not settings.RESEND_API_KEY:
        return False

    import resend
    resend.api_key = settings.RESEND_API_KEY

    ics_content = generate_ics(start, end, title, organizer_email)
    ics_b64 = base64.b64encode(ics_content.encode()).decode()

    date_str = start.strftime("%A %d %B %Y")
    time_str = f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}"

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; background: #f9f9f9; border-radius: 12px;">
      <h2 style="font-size: 20px; color: #111; margin-bottom: 8px;">{title}</h2>
      <p style="color: #555; font-size: 15px; margin-bottom: 24px;">
        {organizer_email} vous invite à une réunion.
      </p>
      <div style="background: #fff; border-radius: 8px; padding: 20px 24px; border: 1px solid #e5e5e5; margin-bottom: 24px;">
        <div style="font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">Date</div>
        <div style="font-size: 17px; font-weight: 600; color: #111; text-transform: capitalize;">{date_str}</div>
        <div style="font-size: 15px; color: #555; margin-top: 4px;">{time_str}</div>
      </div>
      <p style="color: #888; font-size: 13px;">
        Ouvrez la pièce jointe <strong>.ics</strong> pour ajouter cet événement à votre calendrier.
      </p>
    </div>
    """

    try:
        params = {
            "from": f"Calendar Sync <noreply@{settings.RESEND_FROM_DOMAIN}>",
            "to": to_emails,
            "subject": f"Invitation : {title} — {date_str}",
            "html": html_body,
            "attachments": [{
                "filename": "invitation.ics",
                "content": ics_b64,
            }],
        }
        resend.Emails.send(params)
        return True
    except Exception:
        return False
