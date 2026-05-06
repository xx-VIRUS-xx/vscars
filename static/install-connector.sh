#!/usr/bin/env bash
# VSCARS CLI installer — installs the vscars connector on your machine
# Usage: curl -fsSL "https://vscars.latenightstack.com/static/install-connector.sh" | bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
info() { echo -e "${CYAN}[·]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}  ██╗   ██╗███████╗ ██████╗ █████╗ ██████╗ ███████╗${NC}"
echo -e "${CYAN}  ██║   ██║██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝${NC}"
echo -e "${CYAN}  ██║   ██║███████╗██║     ███████║██████╔╝███████╗${NC}"
echo -e "${CYAN}  ╚██╗ ██╔╝╚════██║██║     ██╔══██║██╔══██╗╚════██║${NC}"
echo -e "${CYAN}   ╚████╔╝ ███████║╚██████╗██║  ██║██║  ██║███████║${NC}"
echo -e "${CYAN}    ╚═══╝  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝${NC}"
echo ""
echo -e "  VS Code As a Remote Service — CLI Connector"
echo ""

# ── Detect OS ──────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  Linux*)  PLATFORM=linux ;;
  Darwin*) PLATFORM=mac ;;
  *)       fail "Unsupported OS: $OS. Use Linux or macOS." ;;
esac
info "Platform: $PLATFORM"

# ── Python check ──────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required. Install it from https://python.org and retry."
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  fail "Python 3.10+ required. You have Python $PY_VER."
fi
info "Python $PY_VER ✓"

# ── pip / pipx ────────────────────────────────────────────────────────────
log "Ensuring pip and pipx are available..."
python3 -m pip install --user --quiet --upgrade pip pipx
python3 -m pipx ensurepath >/dev/null 2>&1 || true

PIPX_BIN="$HOME/.local/bin/pipx"
if [[ -x "$PIPX_BIN" ]]; then
  PIPX="$PIPX_BIN"
elif command -v pipx >/dev/null 2>&1; then
  PIPX="$(command -v pipx)"
else
  fail "pipx not found after install. Open a new terminal and run this script again."
fi

# ── Install VSCARS CLI ────────────────────────────────────────────────────
# The CLI is served as a tarball directly from your relay server
VSCARS_SERVER="${VSCARS_SERVER:-https://vscars.latenightstack.com}"
CLI_TARBALL="$VSCARS_SERVER/static/vscars-cli.tar.gz"

log "Downloading VSCARS CLI..."
TMP_DIR="$(mktemp -d)"
trap "rm -rf $TMP_DIR" EXIT

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$CLI_TARBALL" -o "$TMP_DIR/vscars-cli.tar.gz"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$CLI_TARBALL" -O "$TMP_DIR/vscars-cli.tar.gz"
else
  fail "curl or wget required to download the CLI."
fi

log "Installing VSCARS CLI..."
tar -xzf "$TMP_DIR/vscars-cli.tar.gz" -C "$TMP_DIR"
"$PIPX" install --force "$TMP_DIR/vscars-cli/" >/dev/null

# ── PATH check ────────────────────────────────────────────────────────────
if ! command -v vscars >/dev/null 2>&1; then
  warn "vscars not in PATH yet. Adding ~/.local/bin to PATH..."
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc" 2>/dev/null || true
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"  2>/dev/null || true
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✅ VSCARS CLI installed successfully!${NC}"
echo ""
echo -e "  Next steps:"
echo -e ""
echo -e "  ${CYAN}1.${NC} Open the VSCARS app and go to ${CYAN}Plan & Billing → Generate API Key${NC}"
echo -e "  ${CYAN}2.${NC} Run: ${GREEN}vscars init${NC}"
echo -e "       → Enter server: ${CYAN}$VSCARS_SERVER${NC}"
echo -e "       → Enter your API key"
echo -e "  ${CYAN}3.${NC} Run: ${GREEN}vscars start${NC}"
echo -e "       → Keep this running — your machine appears in the app under My Machines"
echo ""
echo -e "  App: ${CYAN}${VSCARS_SERVER}/app${NC}"
echo -e "  Setup guide: ${CYAN}${VSCARS_SERVER}/setup${NC}"
echo ""
