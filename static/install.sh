#!/usr/bin/env bash
# VSCARS CLI installer
# Usage: curl -fsSL https://vscars.latenightstack.com/install.sh | bash

set -euo pipefail

PURPLE='\033[0;35m'; CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${CYAN}[·]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
fail()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo -e "${PURPLE}  VSCARS CLI Installer${NC}"
echo ""

# ── Check Python ──────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c 'import sys; print(sys.version_info >= (3,10))' 2>/dev/null)
        if [[ "$version" == "True" ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    fail "Python 3.10+ is required. Install it from https://www.python.org/downloads/"
fi

PY_VERSION=$("$PYTHON" --version 2>&1)
info "Using $PY_VERSION"

# ── Install ───────────────────────────────────────────────────────────────────
info "Installing vscars-cli..."
"$PYTHON" -m pip install --quiet --upgrade vscars-cli

# ── Check PATH ────────────────────────────────────────────────────────────────
VSCARS_BIN=$(command -v vscars 2>/dev/null || true)

if [[ -z "$VSCARS_BIN" ]]; then
    # pip user install — add to PATH
    USER_BIN="$("$PYTHON" -m site --user-base)/bin"
    info "Adding $USER_BIN to PATH..."

    SHELL_RC=""
    case "${SHELL:-}" in
        */zsh)  SHELL_RC="$HOME/.zshrc" ;;
        */bash) SHELL_RC="$HOME/.bashrc" ;;
    esac

    if [[ -n "$SHELL_RC" ]]; then
        if ! grep -q "$USER_BIN" "$SHELL_RC" 2>/dev/null; then
            echo "export PATH=\"\$PATH:$USER_BIN\"" >> "$SHELL_RC"
            info "Added to $SHELL_RC — restart your shell or run: source $SHELL_RC"
        fi
    fi

    VSCARS_BIN="$USER_BIN/vscars"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
ok "vscars-cli installed"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Get your API key from Settings at https://vscars.latenightstack.com"
echo "  2. Run:  vscars init --api-key vscars_<your_key>"
echo "  3. Run:  vscars start"
echo ""
echo "  Your machine will appear in the Machines tab. Done."
echo ""
