#!/usr/bin/env bash
# VSCARS deployment script — EC2 Ubuntu + Cloudflare Tunnel
# No nginx needed. Tunnel handles SSL + routing directly to uvicorn.
#
# Run as: sudo bash deploy.sh
#
# Prerequisites (do these ONCE before running this script):
#   1. Create a Cloudflare Tunnel in the dashboard (Zero Trust → Networks → Tunnels)
#   2. Copy the tunnel token — you'll need it for the cloudflared service
#   3. Point vscars.latenightstack.com → this tunnel in the Cloudflare DNS panel

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
info() { echo -e "${CYAN}[·]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[[ "$EUID" -eq 0 ]] || fail "Run as root: sudo bash deploy.sh"
[[ "$(uname)" == "Linux" ]] || fail "This script targets Linux (Ubuntu)."

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
APP_DIR="/opt/vscars"
APP_USER="ubuntu"
ENV_FILE="/etc/vscars/vscars.env"
DB_DIR="/var/lib/vscars"

echo ""
echo -e "${CYAN}  VSCARS — Cloudflare Tunnel Deploy${NC}"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
log "Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv curl

# ── 2. cloudflared ────────────────────────────────────────────────────────────
if ! command -v cloudflared &>/dev/null; then
    log "Installing cloudflared..."
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
        | gpg --dearmor > /usr/share/keyrings/cloudflare-main.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/cloudflared.list
    apt-get update -qq
    apt-get install -y -qq cloudflared
    log "cloudflared installed: $(cloudflared --version)"
else
    info "cloudflared already installed: $(cloudflared --version)"
fi

# ── 3. App directory ──────────────────────────────────────────────────────────
log "Syncing app to $APP_DIR..."
if [[ "$PROJECT_DIR" != "$APP_DIR" ]]; then
    rsync -a \
        --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='.env' --exclude='*.db' --exclude='.git' \
        "$PROJECT_DIR/" "$APP_DIR/"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── 4. Database directory ─────────────────────────────────────────────────────
log "Setting up database directory..."
mkdir -p "$DB_DIR"
chown "$APP_USER:$APP_USER" "$DB_DIR"

# ── 5. Python venv ────────────────────────────────────────────────────────────
log "Creating Python venv..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
log "Installing Python dependencies..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# ── 6. Env file ───────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    log "Creating env file at $ENV_FILE..."
    mkdir -p /etc/vscars
    cp "$DEPLOY_DIR/vscars.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    chown root:root "$ENV_FILE"
    warn "→ Edit $ENV_FILE: set SECRET_KEY and APP_BASE_URL"
    warn "→ Then: sudo systemctl restart vscars"
else
    info "Env file exists at $ENV_FILE — not overwriting"
fi

# ── 7. Verify app imports ─────────────────────────────────────────────────────
log "Verifying app imports..."
cd "$APP_DIR"
sudo -u "$APP_USER" \
    env $(cat "$ENV_FILE" | grep -v '^#' | xargs) \
    "$APP_DIR/.venv/bin/python" -c "from app.main import app; print('  ✅ App imports OK')" \
    2>/dev/null || warn "App import check skipped (env not fully configured yet)"

# ── 8. VSCARS systemd service ─────────────────────────────────────────────────
log "Installing vscars systemd service..."
cp "$DEPLOY_DIR/vscars.service" /etc/systemd/system/vscars.service
systemctl daemon-reload
systemctl enable vscars
systemctl restart vscars
sleep 3
if systemctl is-active --quiet vscars; then
    log "vscars service running"
else
    warn "vscars service not running yet — check after configuring env"
    warn "journalctl -u vscars -n 50"
fi

# ── 9. Cloudflare Tunnel service ──────────────────────────────────────────────
echo ""
log "Cloudflare Tunnel setup"
echo ""
echo -e "  Run this to install cloudflared as a service using your tunnel token:"
echo ""
echo -e "  ${CYAN}cloudflared service install <YOUR_TUNNEL_TOKEN>${NC}"
echo ""
echo -e "  Get the token from: Cloudflare Zero Trust → Networks → Tunnels → your tunnel → Configure"
echo ""
echo -e "  Then verify the tunnel is routing:"
echo -e "  ${CYAN}https://vscars.latenightstack.com/api/health${NC}"
echo ""

echo -e "${GREEN}✅ Deploy complete.${NC}"
echo ""
echo "  Service commands:"
echo "    sudo systemctl status vscars"
echo "    journalctl -u vscars -f"
echo "    sudo systemctl restart vscars"
echo ""
echo "  Env: $ENV_FILE"
echo ""
