"""Email sending via Resend (https://resend.com).

If RESEND_API_KEY is not set, emails are logged to stdout instead of sent.
This lets the app run fully without email configured.
"""
import logging
from app.config import RESEND_API_KEY, FROM_EMAIL, APP_NAME, APP_BASE_URL

log = logging.getLogger(__name__)

try:
    import resend as _resend
    _resend.api_key = RESEND_API_KEY
    RESEND_AVAILABLE = bool(RESEND_API_KEY)
except ImportError:
    _resend = None
    RESEND_AVAILABLE = False


def _send(to: str, subject: str, html: str) -> bool:
    if not RESEND_AVAILABLE or not _resend:
        log.info("[EMAIL — not sent, no RESEND_API_KEY]\nTo: %s\nSubject: %s", to, subject)
        return False
    try:
        _resend.Emails.send({"from": FROM_EMAIL, "to": [to], "subject": subject, "html": html})
        return True
    except Exception as exc:
        log.error("Email send failed to %s: %s", to, exc)
        return False


def send_welcome(to_email: str, username: str) -> bool:
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#007acc">Welcome to {APP_NAME}, {username}!</h2>
      <p>Your account is ready. Open the app and set your workspace to get started.</p>
      <a href="{APP_BASE_URL}" style="display:inline-block;margin-top:16px;padding:10px 20px;
         background:#007acc;color:#fff;border-radius:6px;text-decoration:none">
        Open {APP_NAME}
      </a>
      <p style="color:#888;font-size:12px;margin-top:24px">
        If you didn't create this account, ignore this email.
      </p>
    </div>"""
    return _send(to_email, f"Welcome to {APP_NAME}", html)


def send_password_reset(to_email: str, reset_url: str) -> bool:
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#007acc">Reset your password</h2>
      <p>Click the button below to reset your {APP_NAME} password.
         This link expires in <strong>1 hour</strong>.</p>
      <a href="{reset_url}" style="display:inline-block;margin-top:16px;padding:10px 20px;
         background:#007acc;color:#fff;border-radius:6px;text-decoration:none">
        Reset Password
      </a>
      <p style="color:#888;font-size:12px;margin-top:24px">
        If you didn't request this, ignore this email. Your password won't change.
      </p>
    </div>"""
    return _send(to_email, f"{APP_NAME} — Password Reset", html)


def send_license_key(to_email: str, license_key: str, payment_type: str) -> bool:
    plan_label = "Lifetime" if payment_type == "one_time" else "Monthly"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto">
      <h2 style="color:#27ae60">{APP_NAME} Self-Hosted License ({plan_label})</h2>
      <p>Thank you for your purchase! Here is your license key:</p>
      <div style="background:#1e1e1e;color:#89d185;font-family:monospace;padding:14px;
                  border-radius:6px;word-break:break-all;margin:16px 0">
        {license_key}
      </div>
      <p>To activate: open {APP_NAME} → Plan tab → paste the key and click <strong>Activate</strong>.</p>
      <a href="{APP_BASE_URL}/billing" style="display:inline-block;margin-top:8px;padding:10px 20px;
         background:#27ae60;color:#fff;border-radius:6px;text-decoration:none">
        Activate License
      </a>
      <p style="color:#888;font-size:12px;margin-top:24px">
        Keep this key safe — it can be activated on up to 3 installations.
      </p>
    </div>"""
    return _send(to_email, f"{APP_NAME} — Your License Key", html)
