# 📦 Installation Guide

Complete setup instructions for JARVIS development and deployment.

---

## System Requirements

- **Python:** 3.8 or higher
- **VS Code:** Latest version with Copilot extension
- **GitHub:** Account with Copilot subscription
- **Git:** 2.0+
- **Node.js:** 14+ (optional, for create_project)
- **macOS/Linux:** Recommended (Windows support via WSL2)

---

## Step 1: Environment Setup

### macOS
```bash
# Install Homebrew if not present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python3

# Install other dependencies
brew install git gh ngrok node
```

### Ubuntu/Debian
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
sudo apt install git curl nodejs npm

# Install gh CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
&& sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
&& sudo apt update \
&& sudo apt install gh

# Install ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip
unzip ngrok-v3-stable-linux-amd64.zip
sudo mv ngrok /usr/local/bin/
```

---

## Step 2: Clone the Project

```bash
# Navigate to desired location
cd ~/Projects  # or your preferred directory

# Clone
git clone https://github.com/your-repo/jarvis.git
cd jarvis
```

---

## Step 3: Create Virtual Environment

```bash
# Create venv
python3 -m venv venv

# Activate
source venv/bin/activate  # macOS/Linux
# or on Windows:
# venv\Scripts\activate
```

You should see `(venv)` in your terminal prompt.

---

## Step 4: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Main dependencies:**
- fastapi - Web framework
- uvicorn - ASGI server
- sqlalchemy - Database ORM
- pydantic - Data validation
- passlib - Password hashing
- python-jose - JWT handling
- pydantic-qr - QR code generation
- requests - HTTP client
- argon2-cffi - Argon2 hashing

---

## Step 5: GitHub Authentication

### Install GitHub CLI Copilot
```bash
gh copilot
# This will auto-install Copilot CLI if not present
```

### Login to GitHub
```bash
gh auth login
```

Follow the prompts:
- Choose: GitHub.com
- Protocol: HTTPS
- Authentication method: Web browser (recommended for OAuth)
- Scopes: Keep defaults (includes 'copilot')

This gives you an OAuth token (gho_) that Copilot CLI will use.

### Verify Installation
```bash
copilot -p "Say hello"
# Should respond: Hello!
```

---

## Step 6: Environment Configuration

```bash
# Copy example env file
cp .env.example .env

# Edit with your values
nano .env  # or use your editor
```

### .env Configuration

```env
# ========== Server ==========
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
DEBUG=False

# ========== Security ==========
SECRET_KEY=your-very-secure-random-key-here  # Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
SUPERUSER_PHONE=iPhone-16-Pro                # Device ID for superuser

# ========== GitHub ==========
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx  # Classic PAT from https://github.com/settings/tokens
COPILOT_MODEL=gpt-4o                           # Default model for ask_copilot tool

# ========== Workspace ==========
WORKSPACE_PATH=/Users/xxvirusxx/PY/SideHustle  # Your primary project directory
COMMAND_TIMEOUT=120                             # Seconds before command times out

# ========== Database ==========
DATABASE_URL=sqlite:///./vs_code_controller.db  # Auto-created on first run
```

### Generating SECRET_KEY
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Step 7: Create GitHub Token

Visit: https://github.com/settings/tokens

1. Click "Generate new token (classic)"
2. Name: "JARVIS API"
3. Select scopes:
   - `repo` - Full control of private repositories
   - `gist` - Create gists
   - `user` - Read user profile data
4. Generate and copy the token
5. Add to `.env` as `GITHUB_TOKEN`

---

## Step 8: Startup

### Start Server
```bash
# In project directory with venv activated
python3 main.py
```

You should see:
```
🚀 Starting FastAPI server...
📍 Server: http://0.0.0.0:8000
💻 Web UI: http://0.0.0.0:8000
```

### Access Local
Open browser: `http://localhost:8000`

---

## Step 9: Remote Access (Optional)

### Start ngrok
```bash
# In new terminal
ngrok http 8000
```

You'll see:
```
Session Status      online
Account             ...
Version             3.x.x
Region              us
Forwarding          https://xxxx-xx-xxx-xx-x.ngrok-free.app -> http://localhost:8000
```

Copy the `https://...` URL and access from your phone!

### Authenticate
1. Open public URL on phone
2. Create account or login
3. Use superuser device ID to become admin
4. Grant permissions to other accounts

---

## Troubleshooting

### Python not found
```bash
# Use python3 explicitly
python3 main.py

# Or add alias
alias python=python3
```

### Port 8000 already in use
```bash
# Find process using port
lsof -i :8000

# Kill it
kill -9 <PID>

# Or use different port
export SERVER_PORT=8001
python3 main.py
```

### Copilot CLI not found
```bash
# Install via gh
gh copilot

# Or check if in PATH
which copilot

# Add to PATH if needed
export PATH="/usr/local/bin:$PATH"
```

### "ModuleNotFoundError"
```bash
# Ensure venv is active (should see (venv) in prompt)
source venv/bin/activate

# Reinstall requirements
pip install -r requirements.txt
```

### Database locked
```bash
# Remove old database
rm vs_code_controller.db

# Restart server (will auto-create)
python3 main.py
```

### GitHub token rejected
- Verify classic PAT (starts with `ghp_`)
- Check token has required scopes
- Generate new token if expired

### Copilot agent timeout
```env
# Increase timeout in .env
COMMAND_TIMEOUT=600  # 10 minutes
```

---

## Development Mode

For local development with auto-reload:

```bash
pip install uvicorn[standard]
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Database Initialization

Database auto-initializes on first run with:
- `users` table
- `permissions` table
- `command_logs` table
- `conversation_history` table
- `access_requests` table

View database (requires SQLite viewer):
```bash
sqlite3 vs_code_controller.db ".tables"
```

---

## Production Deployment

### Using Gunicorn
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app.main:app
```

### Using Docker (future)
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

---

## Next Steps

1. ✅ Complete installation
2. Start the server
3. Access UI at `http://localhost:8000`
4. Register your account
5. Use Device ID matching `.env` SUPERUSER_PHONE to get admin
6. Grant yourself all permissions
7. Try the Copilot Agent tool
8. Share ngrok URL with team for remote access

---

## Quick Reference

| Task | Command |
|------|---------|
| Activate venv | `source venv/bin/activate` |
| Install deps | `pip install -r requirements.txt` |
| Start server | `python3 main.py` |
| Start ngrok | `ngrok http 8000` |
| Access local | `http://localhost:8000` |
| View logs | `tail -f /tmp/server.log` |
| Generate token | `gh auth login` |
| Check tools | `curl http://localhost:8000/api/tools` |

---

**Installation complete!** Proceed to [README.md](README.md) for usage guide.
