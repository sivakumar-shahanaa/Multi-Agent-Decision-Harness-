"""Email the applicant their decision + a link to join the feedback meeting (Resend).

Adapted from the team's viz-tools notify pattern: best-effort and graceful — never
raises, returns a small status dict the endpoint includes in its response. So a mail
failure can't break the request.

Trigger: once the decision engine has written a verdict, an operator sends the invite
(the /admin page or POST /meeting/invite). The email states the outcome (declined /
conditional / accepted) and links to `<base>/?meeting_id=<session_id>`, where the
applicant joins the AI-jury meeting to hear why and ask follow-ups.
"""
from __future__ import annotations

import html as _html
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

RESEND_URL = "https://api.resend.com/emails"
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Decision Harness <onboarding@resend.dev>")

# How each verdict reads to the applicant: (subject lead, headline, accent color).
_VERDICT_COPY = {
    "ELIMINATE": ("Update on your application", "We won't be moving forward — here's why", "#D6322E"),
    "CONDITIONAL": ("Your application — conditional next steps", "A conditional decision on your application", "#E8920C"),
    "PICK": ("Good news about your application", "We'd like to move forward", "#1B7A3D"),
}


def _render_html(record: dict, join_url: str) -> str:
    verdict = (record.get("verdict") or "").upper()
    _, headline, accent = _VERDICT_COPY.get(verdict, ("Your application", "A decision on your application", "#5B6770"))
    title = _html.escape(record.get("subject", {}).get("title", "your application"))
    summary = _html.escape(record.get("summary") or "")
    score = record.get("overall_score")
    score_line = f" · weighted score {score}/10" if isinstance(score, (int, float)) else ""

    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto">
  <p style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#7A8590;margin:0 0 4px">Decision Harness</p>
  <span style="display:inline-block;padding:4px 10px;border-radius:6px;background:{accent};color:#fff;font-weight:700;font-size:13px">{_html.escape(verdict or "DECISION")}{score_line}</span>
  <h2 style="margin:14px 0 6px">{headline}</h2>
  <p style="color:#48535C;margin:0 0 16px"><strong>{title}</strong></p>
  {f'<p style="color:#11181C;line-height:1.5;margin:0 0 20px">{summary}</p>' if summary else ''}
  <p style="margin:0 0 20px;color:#48535C;line-height:1.5">You're invited to a short meeting with the review panel. They'll walk you through the
  decision out loud and you can ask them anything — by voice — live.</p>
  <a href="{_html.escape(join_url)}" style="display:inline-block;padding:12px 22px;border-radius:999px;background:#11181C;color:#fff;text-decoration:none;font-weight:600">Join the feedback meeting →</a>
  <p style="color:#99a;font-size:12px;margin:22px 0 0">Or paste this link: {_html.escape(join_url)}</p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#99a;font-size:12px;margin:0">Every part of this decision is weighted, evaluated, and inspectable.</p>
</div>"""


async def send_invite(record: dict, to_email: str, join_url: str) -> dict:
    """Email `to_email` their decision + the meeting join link. Never raises."""
    if not RESEND_API_KEY:
        return {"sent": False, "skipped": True, "reason": "RESEND_API_KEY not set"}
    if not to_email:
        return {"sent": False, "skipped": True, "reason": "no recipient email"}

    verdict = (record.get("verdict") or "").upper()
    subject_lead, _, _ = _VERDICT_COPY.get(verdict, ("A decision on your application", "", ""))
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject_lead,
        "html": _render_html(record, join_url),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if r.is_success:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return {"sent": True, "to": to_email, "id": data.get("id"), "join_url": join_url}
        return {"sent": False, "status_code": r.status_code, "error": r.text[:300]}
    except Exception as e:  # noqa: BLE001 — mail must never break the request
        return {"sent": False, "error": f"{type(e).__name__}: {e}"}
