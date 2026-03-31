# DevPilot Deployment Requirements & Steps

## Requirements

### Server
- Ubuntu 22.04 LTS (or any modern Linux, or macOS for local)
- 2+ GB RAM, 1+ vCPU (for light use)
- Python 3.9+
- Node.js (optional, for future frontend builds)
- Root SSH access (for systemd/nginx setup)

### Software
- nginx (reverse proxy)
- certbot (for HTTPS, optional but recommended)
- systemd (for service management)
- git (for code updates)
- pip (Python package manager)

### Python Packages (see requirements.txt)
- fastapi, uvicorn, slowapi, gunicorn, sqlalchemy, pydantic, passlib, bcrypt, pyjwt, python-dotenv, requests, pyngrok, qrcode, pillow

### Files/Secrets
- .env file (edit for production: strong SECRET_KEY, correct DOMAIN, etc)
- .secret_key (auto-generated on first run)
- .github_token (if using Copilot CLI)

---

## Deployment Steps

### 1. Prepare the Server
- [ ] Provision a VPS (e.g., DigitalOcean, AWS, Hetzner)
- [ ] Set up DNS for your domain (e.g., devpilot.yourdomain.com)
- [ ] SSH into the server
- [ ] Update system: `sudo apt update && sudo apt upgrade -y`
- [ ] Install Python 3.9+, pip, git: `sudo apt install python3 python3-pip git -y`

### 2. Clone the Project
- [ ] `git clone <your-repo-url> /opt/devpilot`
- [ ] `cd /opt/devpilot`

### 3. Install Python Dependencies
- [ ] `python3 -m pip install -r requirements.txt`

### 4. Configure Environment
- [ ] Copy `.env` and edit:
    - Set `SECRET_KEY` to a strong random value
    - Set `HOST=0.0.0.0`, `PORT=8000`
    - Set `WORKSPACE_PATH` to your project root
    - Set `NGROK_ENABLED=false` (using nginx now)
    - Set `ALLOWED_ORIGINS` to your domain for CORS
- [ ] Ensure `.secret_key` and `.github_token` are in `.gitignore`

### 5. Set Up nginx
- [ ] `sudo apt install nginx certbot python3-certbot-nginx -y`
- [ ] Copy `deploy/nginx.conf` to `/etc/nginx/sites-available/devpilot`
- [ ] `sudo ln -s /etc/nginx/sites-available/devpilot /etc/nginx/sites-enabled/`
- [ ] `sudo rm /etc/nginx/sites-enabled/default`
- [ ] Edit paths in nginx.conf if needed (static dir, etc)
- [ ] `sudo nginx -t && sudo systemctl reload nginx`

### 6. Set Up systemd Service
- [ ] Copy `deploy/devpilot.service` to `/etc/systemd/system/`
- [ ] Edit `User`, `Group`, and paths if needed
- [ ] `sudo systemctl daemon-reload`
- [ ] `sudo systemctl enable devpilot`
- [ ] `sudo systemctl start devpilot`
- [ ] `sudo systemctl status devpilot` (check for errors)

### 7. Enable HTTPS (Recommended)
- [ ] `sudo certbot --nginx -d devpilot.yourdomain.com`
- [ ] Test HTTPS access

### 8. Test Everything
- [ ] Visit `http://devpilot.yourdomain.com` (or HTTPS)
- [ ] Login, run commands, check file ops, Copilot, etc
- [ ] Check logs: `journalctl -u devpilot -f` and `/var/log/nginx/devpilot_error.log`

### 9. (Optional) Local macOS Deploy
- [ ] `cd deploy && ./deploy.sh local`
- [ ] Access at `http://localhost`

---

## Notes
- For production, always use HTTPS and a strong SECRET_KEY
- Disable or restrict ngrok in production
- Keep your server and dependencies updated
- For support, see README or contact maintainer
