import os
import secrets
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./vs_code_controller.db")

# JWT — auto-generate a strong secret if not set (persisted per-run)
_secret_file = os.path.join(os.path.dirname(__file__), ".secret_key")
def _get_secret_key():
    env_key = os.getenv("SECRET_KEY", "")
    if env_key and env_key != "your-secret-key-change-in-production":
        return env_key
    # Generate and persist a random key so tokens survive restarts
    if os.path.exists(_secret_file):
        with open(_secret_file, 'r') as f:
            return f.read().strip()
    key = secrets.token_urlsafe(64)
    with open(_secret_file, 'w') as f:
        f.write(key)
    os.chmod(_secret_file, 0o600)
    return key

SECRET_KEY = _get_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))  # 1 hour default

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# GitHub Copilot API (via GitHub Models)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
COPILOT_MODEL = os.getenv("COPILOT_MODEL", "gpt-4o")

# Workspace (default working directory for all tools)
# Default to this project's root directory, NOT home ~
WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMAND_TIMEOUT = min(int(os.getenv("COMMAND_TIMEOUT", "120")), 300)  # Cap at 5 min

# Security limits
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE", str(10 * 1024 * 1024)))  # 10MB
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(5 * 1024 * 1024)))  # 5MB
RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
RATE_LIMIT_API = os.getenv("RATE_LIMIT_API", "30/minute")

# Ngrok
NGROK_ENABLED = os.getenv("NGROK_ENABLED", "false").lower() == "true"
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")

# Superuser phone (device ID)
SUPERUSER_PHONE = os.getenv("SUPERUSER_PHONE", "superuser-default-device")

# Billing — Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_PRO_MONTHLY = os.getenv("STRIPE_PRICE_PRO_MONTHLY", "")
STRIPE_PRICE_TEAM_MONTHLY = os.getenv("STRIPE_PRICE_TEAM_MONTHLY", "")
STRIPE_PRICE_SELF_HOSTED_MONTHLY = os.getenv("STRIPE_PRICE_SELF_HOSTED_MONTHLY", "")
STRIPE_PRICE_SELF_HOSTED_LIFETIME = os.getenv("STRIPE_PRICE_SELF_HOSTED_LIFETIME", "")

# Billing — License keys (self-hosted)
LICENSE_SIGNING_KEY = os.getenv("LICENSE_SIGNING_KEY", "change-this-to-a-random-32-char-secret")

# App public URL (used in Stripe redirect URLs)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

# Email (Resend — https://resend.com)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "VSCARS <noreply@yourdomain.com>")
APP_NAME = os.getenv("APP_NAME", "VSCARS")

# QR Code
QR_CODE_SIZE = 10

# File paths
# Get the project root (parent of app directory)
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
DB_DIR = os.path.dirname(__file__)
