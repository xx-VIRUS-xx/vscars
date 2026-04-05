#!/bin/bash
# DevPilot Deployment Script
# Usage: ./deploy.sh [local|server]
#
# local  - Setup on macOS with Homebrew nginx (default)
# server - Setup on Linux with systemd + nginx

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="$PROJECT_DIR/deploy"
MODE="${1:-local}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

# ---------- Common Setup ----------
setup_python() {
    log "Installing Python dependencies..."
    cd "$PROJECT_DIR"
    python3 -m pip install -r requirements.txt -q
    python3 -m pip install slowapi -q
    log "Python deps installed."
}

check_prod_env_safety() {
    # Prevent accidentally deploying local/dev .env into production.
    if [[ "$MODE" == "server" && -f "$PROJECT_DIR/.env" ]]; then
        err "Refusing server deploy: '$PROJECT_DIR/.env' exists. Remove it and use system-level env vars (EnvironmentFile) instead."
    fi
}

check_app_starts() {
    log "Testing app startup..."
    cd "$PROJECT_DIR"
    timeout 5 python3 -c "from app.main import app; print('App imports OK')" || err "App failed to import. Fix errors first."
    log "App import check passed."
}

# ---------- macOS Local (Homebrew) ----------
deploy_local() {
    log "Deploying locally on macOS with Homebrew nginx..."

    # Check nginx
    if ! command -v nginx &>/dev/null; then
        warn "nginx not found. Installing via Homebrew..."
        brew install nginx
    fi

    NGINX_DIR="$(brew --prefix)/etc/nginx"
    SERVERS_DIR="$NGINX_DIR/servers"
    mkdir -p "$SERVERS_DIR"

    # Adjust paths in config for spaces
    log "Copying nginx config..."
    cp "$DEPLOY_DIR/nginx.conf" "$SERVERS_DIR/devpilot.conf"

    # Test nginx config
    if nginx -t 2>&1; then
        log "nginx config valid."
    else
        err "nginx config test failed!"
    fi

    # Restart nginx
    brew services restart nginx
    log "nginx restarted."

    # Start the app in background
    log "Starting DevPilot server..."
    cd "$PROJECT_DIR"
    pkill -f "python3 -u main.py" 2>/dev/null || true
    sleep 1
    nohup python3 -u main.py > /tmp/devpilot.log 2>&1 &
    APP_PID=$!
    sleep 3

    if curl -s http://localhost:8000/api/health | grep -q '"ok"'; then
        log "Server running (PID: $APP_PID)"
        log "Access at: http://localhost (nginx) or http://localhost:8000 (direct)"
    else
        err "Server failed to start. Check /tmp/devpilot.log"
    fi
}

# ---------- Linux Server (systemd) ----------
deploy_server() {
    log "Deploying on Linux server with systemd + nginx..."

    # Check we're on Linux
    [[ "$(uname)" == "Linux" ]] || err "Server mode requires Linux. Use './deploy.sh local' for macOS."

    # Check root
    [[ "$EUID" -eq 0 ]] || err "Server deploy requires root. Run: sudo ./deploy.sh server"

    # Install nginx if needed
    if ! command -v nginx &>/dev/null; then
        warn "Installing nginx..."
        apt-get update -qq && apt-get install -y -qq nginx certbot python3-certbot-nginx
    fi

    # Copy configs
    log "Installing nginx site config..."
    cp "$DEPLOY_DIR/nginx.conf" /etc/nginx/sites-available/devpilot
    ln -sf /etc/nginx/sites-available/devpilot /etc/nginx/sites-enabled/devpilot

    # Remove default site if present
    rm -f /etc/nginx/sites-enabled/default

    # Test + reload nginx
    nginx -t || err "nginx config test failed!"
    systemctl reload nginx
    log "nginx configured and reloaded."

    # Install systemd service
    log "Installing systemd service..."
    cp "$DEPLOY_DIR/devpilot.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable devpilot
    systemctl restart devpilot

    sleep 3
    if systemctl is-active --quiet devpilot; then
        log "DevPilot service is running."
    else
        err "Service failed to start. Check: journalctl -u devpilot -n 50"
    fi

    log "Deployment complete!"
    echo ""
    echo "  Access:  http://$(hostname -I | awk '{print $1}')"
    echo "  Status:  sudo systemctl status devpilot"
    echo "  Logs:    journalctl -u devpilot -f"
    echo ""
    warn "For HTTPS: sudo certbot --nginx -d yourdomain.com"
}

# ---------- Main ----------
echo ""
echo "=========================================="
echo "  DevPilot Deployment"
echo "=========================================="
echo ""

setup_python
check_prod_env_safety
check_app_starts

case "$MODE" in
    local)  deploy_local ;;
    server) deploy_server ;;
    *)      err "Usage: ./deploy.sh [local|server]" ;;
esac
