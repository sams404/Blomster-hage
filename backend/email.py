"""Email delivery через Resend (бесплатно до 3000 писем/мес)."""
import os, requests

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL     = os.environ.get("FROM_EMAIL", "agents@blomsterhage.no")
OWNER_EMAIL    = os.environ.get("OWNER_EMAIL", "")  # твой email


def _send(to: str, subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        print(f"[email] SKIP (no key): {subject[:40]} → {to}")
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json={"from": FROM_EMAIL, "to": to, "subject": subject, "html": html},
            timeout=15,
        )
        ok = r.status_code == 200
        if not ok:
            print(f"[email] ERROR {r.status_code}: {r.text[:100]}")
        return ok
    except Exception as e:
        print(f"[email] EXCEPTION: {e}")
        return False


def send_content_delivery(to_email: str | None, subject: str,
                           content: str, agent_name: str = "") -> bool:
    to = to_email or OWNER_EMAIL
    if not to:
        return False
    html = f"""
    <div style="font-family:monospace;max-width:680px;margin:0 auto;background:#080808;color:#e6e2d8;padding:40px;">
      <p style="color:#c9a96e;font-size:11px;letter-spacing:0.2em;text-transform:uppercase;">
        {agent_name} · Blomster Hage
      </p>
      <h1 style="font-size:24px;font-weight:300;color:#e6e2d8;margin:16px 0;">{subject}</h1>
      <div style="color:rgba(230,226,216,0.75);line-height:1.8;white-space:pre-wrap;">{content}</div>
      <hr style="border-color:rgba(255,255,255,0.05);margin:32px 0;">
      <p style="font-size:10px;color:rgba(230,226,216,0.3);">
        Автоматически создано агентом {agent_name} | Blomster Hage AI
      </p>
    </div>"""
    return _send(to, f"🌸 {subject}", html)


def send_signal(to_email: str, signal_text: str) -> bool:
    html = f"""
    <div style="font-family:monospace;max-width:600px;margin:0 auto;background:#080808;color:#e6e2d8;padding:40px;">
      <p style="color:#c9a96e;font-size:11px;letter-spacing:0.2em;">📊 HELIANTHUS SIGNAL · BLOMSTER HAGE</p>
      <div style="margin:24px 0;padding:20px;border:1px solid rgba(201,169,110,0.2);white-space:pre-wrap;line-height:1.8;">
        {signal_text}
      </div>
      <p style="font-size:10px;color:rgba(230,226,216,0.3);">Не является финансовым советом. DYOR.</p>
    </div>"""
    return _send(to_email, "📊 Крипто-сигнал | Blomster Hage", html)


def send_outreach(to_email: str, pitch: str) -> bool:
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;color:#333;line-height:1.7;">
      {pitch.replace(chr(10), '<br>')}
    </div>"""
    subject = "En idé til deg 🌱"
    return _send(to_email, subject, html)


def send_waitlist_welcome(to_email: str, name: str, plan: str) -> bool:
    html = f"""
    <div style="font-family:monospace;max-width:600px;margin:0 auto;background:#080808;color:#e6e2d8;padding:40px;">
      <p style="color:#c9a96e;font-size:20px;">🌸 Välkommen til Blomster Hage, {name}!</p>
      <p>Du har registrert deg for <strong style="color:#c9a96e;">{plan}</strong>-planen.</p>
      <p>Agentene dine aktiveres innen 24 timer.</p>
      <p style="margin-top:24px;">Med vennlig hilsen,<br>Samson<br>Blomster Hage AI</p>
    </div>"""
    return _send(to_email, "🌸 Välkommen til Blomster Hage!", html)
