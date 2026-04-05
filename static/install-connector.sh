#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log(){ echo -e "${GREEN}[+]${NC} $1"; }
warn(){ echo -e "${YELLOW}[!]${NC} $1"; }
fail(){ echo -e "${RED}[x]${NC} $1"; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required for connector installation."
fi

log "Installing pipx (user scope) if needed..."
python3 -m pip install --user --upgrade pip pipx >/dev/null
python3 -m pipx ensurepath >/dev/null || true

PIPX_BIN="$HOME/.local/bin/pipx"
if [[ -x "$PIPX_BIN" ]]; then
  PIPX="$PIPX_BIN"
elif command -v pipx >/dev/null 2>&1; then
  PIPX="$(command -v pipx)"
else
  fail "pipx not found after install. Reopen terminal and run again."
fi

log "Installing VSCARS connector command..."
"$PIPX" install --force git+https://github.com/latenightstack/vscars.git >/dev/null

if ! command -v vscars >/dev/null 2>&1; then
  warn "vscars command not found in PATH yet."
  echo "Run: export PATH=\"$HOME/.local/bin:$PATH\""
fi

cat <<EOF

✅ Connector installed.

Next steps:
1) Open app and generate API key (Plan & Billing)
2) Run: vscars init
3) Run: vscars start

EOF
