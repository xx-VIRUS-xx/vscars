# VSCARS — Full Project Documentation

**Last updated:** 2026-04-01
**Stack:** Python 3.12 · FastAPI · SQLite · SQLAlchemy · Vanilla JS · HTML/CSS
**Domain:** vscars.latenightstack.com

---

## Table of Contents

1. [What is VSCARS?](#1-what-is-vscars)
2. [Architecture Overview](#2-architecture-overview)
3. [File Structure](#3-file-structure)
4. [Database Models](#4-database-models)
5. [Authentication & Security](#5-authentication--security)
6. [Subscription & Billing](#6-subscription--billing)
7. [CLI API Key System](#7-cli-api-key-system)
8. [Machine Relay System](#8-machine-relay-system)
9. [Tool System](#9-tool-system)
10. [API Endpoints Reference](#10-api-endpoints-reference)
11. [Frontend](#11-frontend)
12. [vscars CLI Package](#12-vscars-cli-package)
13. [Environment Variables (.env)](#13-environment-variables-env)
14. [Running the App](#14-running-the-app)
15. [Subscription Tiers](#15-subscription-tiers)
16. [What Still Needs Doing](#16-what-still-needs-doing)

---

## 1. What is VSCARS?

VSCARS is a mobile-first web platform that lets users control their own development machines remotely — run terminal commands, browse files, use git, and chat with AI — all from their phone or tablet.

**Key principle:** The server is just a relay and an AI chat interface. All filesystem, terminal, and git operations run on the **user's own registered machine** via the `vscars` CLI agent. The server host (your laptop) is never exposed to regular users.

---

## 2. Architecture Overview

```
User's Phone/Browser
       │  HTTPS / WSS
       ▼
VSCARS Server  (vscars.latenightstack.com)
  ├── Auth / Billing / AI Chat APIs
  ├── Relay Manager (app/relay.py)
  │        │  WebSocket /ws/agent/{token}
  │        ▼
  │   User's Laptop running `vscars start`
  │   (cli/vscars/agent.py)
  │        │ runs tools locally via executor.py
  │        └── user's own filesystem / terminal / git
  └── Superuser exception: tools run directly on host
```

### Who runs tools where?

| User Type | File/Terminal/Git tools | AI chat |
|-----------|------------------------|---------|
| **Free** | ❌ Blocked entirely | ✅ Limited models |
| **Pro/Team/Self-Hosted** | ✅ On their **own machine** via CLI agent | ✅ Full model access |
| **Superuser (you)** | ✅ Directly on server host | ✅ All models |

---

## 3. File Structure

```
vscars/
├── main.py                     # Entrypoint (starts uvicorn)
├── app/
│   ├── main.py                 # FastAPI app, all route definitions
│   ├── database.py             # SQLAlchemy models + SQLite migrations
│   ├── auth.py                 # JWT creation/validation, password hashing (argon2)
│   ├── config.py               # All env var loading
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── tools.py                # Tool handlers (run on host for superuser)
│   ├── git_ops.py              # Git operations (status, diff, commit, push, log)
│   ├── relay.py                # WebSocket relay manager
│   ├── jarvis.py               # JARVIS interpreter (legacy name, used by tools)
│   ├── email.py                # Transactional email (Resend)
│   ├── billing/
│   │   ├── plan_limits.py      # Plan definitions, permission sync, API key issuance
│   │   ├── routes.py           # /api/billing/* endpoints + Stripe webhook handlers
│   │   ├── stripe_client.py    # Stripe SDK wrapper
│   │   └── license.py         # HMAC-signed self-hosted license key generation/validation
│   └── utils/
│       ├── qr_code.py          # QR code generation for device auth
│       └── ngrok_helper.py     # ngrok tunnel management
├── static/
│   ├── index.html              # Single-page app (all views)
│   ├── script.js               # All frontend logic (~3000 lines)
│   └── style.css               # All styles
├── cli/                        # Standalone pip package
│   ├── setup.py
│   └── vscars/
│       ├── __init__.py
│       ├── cli.py              # CLI entry point (vscars init/start/stop/status/logs/workspace)
│       ├── agent.py            # WebSocket agent with auto-reconnect
│       ├── executor.py         # Local tool executor (mirrors server tools.py)
│       └── config.py           # ~/.vscars/config.json management
└── deploy/
    ├── nginx.conf
    ├── devpilot.service
    └── deploy.sh
```

---

## 4. Database Models

All tables live in `vs_code_controller.db` (SQLite). SQLite-safe `ALTER TABLE` migrations run on every startup.

### `users`
| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | |
| `username` | str unique | |
| `email` | str unique | |
| `hashed_password` | str | argon2 hash |
| `device_id` | str unique | set at register |
| `is_superuser` | bool | first registered user only |
| `is_active` | bool | soft-disable accounts |
| `plan` | str | `free` \| `pro` \| `team` \| `self_hosted` |
| `stripe_customer_id` | str | nullable |
| `stripe_subscription_id` | str | nullable |
| `trial_ends_at` | datetime | nullable; used for grace periods |
| `daily_api_calls` | int | reset each UTC day |
| `daily_reset_at` | datetime | |
| `api_key_hash` | str | SHA256 of CLI API key; nullable until pro+ |

### `user_permissions`
Synced from plan via `apply_plan_to_permissions()` on every plan change.

| Column | Free | Pro/Team/Self-Hosted |
|--------|------|---------------------|
| `can_run_copilot` | ✅ | ✅ |
| `can_run_commands` | ❌ | ✅ |
| `can_edit_files` | ❌ | ✅ |
| `can_view_files` | ❌ | ✅ |
| `can_use_machine` | ❌ | ✅ |

### `registered_machines`
One row per machine registered via `vscars init`.

| Column | Notes |
|--------|-------|
| `machine_id` | UUID generated by CLI on first init |
| `user_id` | FK to users |
| `name` | e.g. "MacBook Pro" |
| `hostname` | platform.node() |
| `os_info` | "Darwin 25.3.0" |
| `token_hash` | SHA256 of machine auth token (issued at register, used by WS) |
| `is_connected` | live status updated by WS connect/disconnect |
| `last_seen_at` | updated on each ping |

### Other Tables

| Table | Purpose |
|-------|---------|
| `access_requests` | QR code device access requests |
| `command_logs` | Every tool execution (user, tool, params, result, status) |
| `conversation_history` | AI chat messages |
| `token_blacklist` | Revoked JWTs (logout support) |
| `password_reset_tokens` | Single-use reset links (1hr expiry) |
| `license_keys` | Self-hosted HMAC-signed license keys |
| `idea_notes` | Idea Vault — user notes/ideas |
| `saved_workflows` | Named shell command shortcuts |
| `user_sessions` | Active JWT sessions (for session management UI) |

---

## 5. Authentication & Security

### JWT Auth
- Library: `python-jose` / `PyJWT`
- Algorithm: HS256, secret auto-generated and persisted to `app/.secret_key`
- Default expiry: 60 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- Each token has a `jti` (UUID) for revocation support
- Logout adds `jti` hash to `token_blacklist` table

### Password Hashing
- Uses **argon2** (via passlib) — no 72-byte limit, more secure than bcrypt

### Token Revocation
- `is_token_revoked(token, db)` checked on every authenticated request
- `revoke_token(token, user_id, db)` called on logout

### Frontend Session Expiry
- JS decodes the JWT `exp` field client-side on login
- `scheduleTokenExpiry()` sets a `setTimeout` to fire `handleSessionExpiry()` at exact expiry
- 2-minute warning toast shown before expiry
- Any 401 response calls `handleSessionExpiry()` immediately

### Security Headers (every response)
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security: (only when FORCE_HTTPS=true)
```

### Rate Limiting
- Login/register: 5/minute per IP (slowapi)
- General API: 30/minute per IP
- Password reset: 3/minute per IP
- Request size cap: 10MB

### Path Sandbox (tools)
All file operations run through `_resolve_path()` which enforces paths stay inside the configured workspace. Path traversal (`../`) is blocked. `/tmp/` is the only other allowed prefix.

---

## 6. Subscription & Billing

### Stripe Integration
- `POST /api/billing/checkout` → creates Stripe Checkout session, returns redirect URL
- `GET /api/billing/portal` → Stripe Billing Portal for subscription management
- `POST /api/billing/webhook` → receives Stripe events, validates HMAC signature

**Webhook events handled:**
| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activates plan, links subscription ID |
| `customer.subscription.updated` | Syncs plan from price ID |
| `customer.subscription.deleted` | Downgrades to free |
| `invoice.payment_failed` | 7-day grace period before downgrade |

**Price IDs needed in `.env`:**
```
STRIPE_PRICE_PRO_MONTHLY=price_xxx
STRIPE_PRICE_TEAM_MONTHLY=price_xxx
STRIPE_PRICE_SELF_HOSTED_MONTHLY=price_xxx
STRIPE_PRICE_SELF_HOSTED_LIFETIME=price_xxx
```

### Self-Hosted License Keys
- Generated by superuser via `POST /api/billing/admin/generate-license`
- HMAC-signed with `LICENSE_SIGNING_KEY` — verifiable offline
- Stored as SHA256 hash in `license_keys` table
- Activated via `POST /api/billing/validate-license`
- Max activations configurable (default 3)
- Optional expiry (null = lifetime)

### Plan Sync
`apply_plan_to_permissions(user, db)` is called after every plan change. It:
1. Writes all permission flags to `user_permissions`
2. Auto-issues a CLI API key if upgrading to a paid plan and none exists yet

---

## 7. CLI API Key System

### Purpose
Lets users authenticate the `vscars` CLI without ever typing a password in the terminal. API key is issued once and used for all CLI operations.

### Flow
```
1. User buys Pro on vscars.latenightstack.com
2. apply_plan_to_permissions() auto-issues a key on plan upgrade
   OR user manually clicks "Generate API Key" in billing view
3. Raw key shown ONCE: vscars_<32 bytes urlsafe>
4. SHA256 hash stored in users.api_key_hash
5. User runs: vscars init → pastes key → machine registered
```

### Endpoints
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/auth/api-key` | Bearer JWT **or** `X-VSCARS-Key` | Check if key exists, plan, machine access |
| `POST` | `/api/auth/api-key/generate` | Bearer JWT | Issue/regenerate key (requires pro+) |

### Security
- Raw key never stored — only SHA256 hash in DB
- `X-VSCARS-Key` header accepted on `/api/machines/register` and `/api/auth/api-key`
- If key is compromised: user regenerates from dashboard; old key instantly invalid

---

## 8. Machine Relay System

### Files
- **`app/relay.py`** — server-side relay manager
- **`cli/vscars/agent.py`** — client-side WebSocket agent
- **`cli/vscars/executor.py`** — local tool executor

### How the Relay Works

```
Browser                  Server                   User's Machine
  │                        │                           │
  │  POST /api/tools/execute  │                        │
  │──────────────────────►│                            │
  │                        │  WS send {tool_call}      │
  │                        │──────────────────────────►│
  │                        │                           │ executor.execute()
  │                        │  WS recv {tool_result}    │
  │                        │◄──────────────────────────│
  │  HTTP response          │                           │
  │◄───────────────────────│                           │
```

### relay.py internals
```python
_connections: dict[int, dict[str, WebSocket]]  # user_id → {machine_id → ws}
_pending: dict[str, asyncio.Future[dict]]       # call_id → future

async def call_tool(user_id, machine_id, tool_name, params, timeout=90)
    # sends JSON over WS, awaits Future resolution
    # raises ConnectionError if no machine online
    # raises asyncio.TimeoutError if machine silent for 90s

def resolve_call(call_id, result)
    # called by WS handler when machine sends tool_result
    # sets the Future result, unblocking the HTTP handler
```

### Machine WebSocket (`/ws/agent/{machine_token}`)
- Agent authenticates via `machine_token` → SHA256 matched against `registered_machines.token_hash`
- Server sends `{type: "connected"}` on accept
- Agent sends `{type: "ping"}` every 25s; server replies `{type: "pong"}`
- Server sends `{type: "tool_call", call_id, tool, params}`
- Agent replies `{type: "tool_result", call_id, success, result}`
- On disconnect: `is_connected = False` in DB, relay entry removed

### Machine Registry Endpoints
| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/machines/register` | `X-VSCARS-Key` or `Bearer JWT`; requires pro+ |
| `GET` | `/api/machines` | Lists all machines + live online status |
| `DELETE` | `/api/machines/{machine_id}` | Soft-delete (sets `is_active=False`) |

---

## 9. Tool System

18 tools defined in `TOOLS` list in `app/tools.py`. Each has a `required_permission` that gates access.

### Permission Levels
| Permission | Free | Pro+ |
|-----------|------|------|
| `copilot` | ✅ | ✅ |
| `view` | ❌ | ✅ (via relay) |
| `edit` | ❌ | ✅ (via relay) |
| `commands` | ❌ | ✅ (via relay) |

### Tool List

| Tool | Permission | Description |
|------|-----------|-------------|
| `open_file` | view | Open file in VS Code |
| `open_project` | view | Open folder in VS Code |
| `read_file` | view | Read file contents |
| `list_files` | view | List directory contents |
| `search_files` | view | Search by filename |
| `git_status` | view | Git branch + status |
| `browse_directory` | view | Visual tree with git + project detection |
| `get_workspace_info` | view | OS, Python, hostname info |
| `create_file` | edit | Create file with content |
| `edit_file` | edit | Replace text in file |
| `delete_file` | edit | Delete a file |
| `create_project` | edit | Scaffold python/node/react/flask/fastapi |
| `run_command` | commands | Run shell command (blocked pattern list) |
| `open_terminal` | commands | Open terminal at path |
| `git_command` | commands | Run arbitrary git command |
| `ask_copilot` | copilot | AI chat via GitHub Models (GPT-4o) |
| `ask_ai` | copilot | Multi-provider AI (auto-picks available) |
| `copilot_agent` | copilot | Autonomous agent (edit/run/build) |

### AI Fallback Chain (`copilot_agent`)
On quota/unavailable errors, walks this chain:
```
claude-haiku-4.5 → claude-sonnet-4.6 → gpt-4.1 → gpt-5.2 → claude-opus-4.6
```
Stops on non-quota errors (real failures).

### AI Models by Plan

| Model | Free | Pro | Team/Self-Hosted |
|-------|------|-----|-----------------|
| Claude Haiku 4.5 | ✅ | ✅ | ✅ |
| GPT-5 Mini | ✅ | ✅ | ✅ |
| Claude Sonnet 4.6 | ❌ | ✅ | ✅ |
| GPT-4.1 | ❌ | ✅ | ✅ |
| GPT-5.2 | ❌ | ✅ | ✅ |
| Claude Opus 4.6 | ❌ | ❌ | ✅ |
| GPT-5.4, GPT-5.3 Codex, Gemini 3 Pro | ❌ | ❌ | ✅ |

---

## 10. API Endpoints Reference

### Auth
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| `POST` | `/api/auth/register` | — | First user = superuser + pro |
| `POST` | `/api/auth/login` | — | Returns JWT |
| `GET` | `/api/auth/me` | JWT | Current user info |
| `POST` | `/api/auth/logout` | JWT | Revokes token |
| `POST` | `/api/auth/forgot-password` | — | Sends reset email |
| `POST` | `/api/auth/reset-password` | — | Consumes reset token |
| `GET` | `/api/auth/sessions` | JWT | List active sessions |
| `DELETE` | `/api/auth/sessions/{id}` | JWT | Revoke a session |
| `GET` | `/api/auth/api-key` | JWT or X-VSCARS-Key | API key status |
| `POST` | `/api/auth/api-key/generate` | JWT | Issue/regenerate CLI key |

### Tools
| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/tools` | List tools with permissions |
| `POST` | `/api/tools/execute` | Execute a tool (proxied to machine for non-superuser) |
| `GET` | `/api/tools/history` | Last 50 command logs |
| `GET` | `/api/tools/execution-log` | Backend logs (superuser only) |

### Git Panel
| Method | Path |
|--------|------|
| `GET` | `/api/git/status` |
| `GET` | `/api/git/diff?staged=true` |
| `POST` | `/api/git/stage` |
| `POST` | `/api/git/unstage` |
| `POST` | `/api/git/commit` |
| `POST` | `/api/git/push` |
| `GET` | `/api/git/log?n=10` |
| `GET` | `/api/git/branches` |
| `POST` | `/api/git/ai-commit-message` |

### Idea Vault
| Method | Path |
|--------|------|
| `GET` | `/api/ideas` |
| `POST` | `/api/ideas` |
| `PATCH` | `/api/ideas/{id}` |
| `DELETE` | `/api/ideas/{id}` |

### Saved Workflows
| Method | Path |
|--------|------|
| `GET` | `/api/workflows` |
| `POST` | `/api/workflows` |
| `DELETE` | `/api/workflows/{id}` |
| `POST` | `/api/workflows/{id}/run` |

### Machines
| Method | Path |
|--------|------|
| `POST` | `/api/machines/register` |
| `GET` | `/api/machines` |
| `DELETE` | `/api/machines/{machine_id}` |

### Billing
| Method | Path |
|--------|------|
| `GET` | `/api/billing/status` |
| `POST` | `/api/billing/checkout` |
| `GET` | `/api/billing/portal` |
| `POST` | `/api/billing/webhook` |
| `POST` | `/api/billing/validate-license` |
| `POST` | `/api/billing/admin/generate-license` |

### AI / Copilot
| Method | Path |
|--------|------|
| `GET` | `/api/copilot/models` |

### Settings
| Method | Path |
|--------|------|
| `POST` | `/api/settings/github-token` |
| `GET` | `/api/settings/github-token` |
| `POST` | `/api/settings/workspace` |
| `GET` | `/api/settings/workspace` |

### Dashboard
| Method | Path |
|--------|------|
| `GET` | `/api/dashboard/brief` |

### Other
| Method | Path |
|--------|------|
| `GET` | `/api/health` |
| `GET` | `/api/ngrok/url` |
| `GET` | `/api/bugs` |
| `POST` | `/api/bugs/report` |
| `WS` | `/ws/stream?token=jwt` |
| `WS` | `/ws/agent/{machine_token}` |

---

## 11. Frontend

Single-page app at `static/index.html`. All logic in `static/script.js` (~3000 lines).

### Views (nav via `switchView(name)`)
| View ID | Icon | Description |
|---------|------|-------------|
| `home` / `dashboard` | ⊞ | Morning Brief — stats, git, ideas count |
| `tools` | ⊡ | Tool grid — click to open tool form/modal |
| `file-browser` | ⊟ | File browser with path navigation + search |
| `git` | ⌥ | Git panel — status, diff, stage, commit, push |
| `copilot` | ⊕ | Copilot Agent tool |
| `conversations` | ⊘ | AI Chat history |
| `ideas` | ⊗ | Idea Vault — create/edit/complete notes |
| `workflows` | ⊞ | Saved shell command shortcuts |
| `activity` | ≣ | Command execution log |
| `machines` | ⬡ | Registered machines + CLI setup |
| `settings` | ⊛ | GitHub token, workspace path |
| `billing` | ◬ | Plan, pricing, API key, license key |
| `admin` | ⊠ | User management (superuser only) |

### Mobile
- `body.is-mobile` CSS class set by JS UA detection (not CSS media query — prevents false positives on narrow windows)
- Pill bar at bottom with drag-up gesture to open full service drawer
- Drawer always in DOM at `translateY(100%)` → `.open` = `translateY(0)` with cubic-bezier transition
- All mobile CSS uses `body.is-mobile` selectors

### Key JS Patterns
- `fetchAPI(endpoint, options)` — all API calls go through this; handles 401→session expiry, attaches Bearer token
- `showToast(msg, type, duration)` — notifications system
- `showLoading(msg)` / `hideLoading()` — loading overlay
- `executeToolForm(e)` — handles all tool form submissions, proxies errors (503 → connect machine card, 403 → upgrade prompt, 429 → model picker)
- `scheduleTokenExpiry(token)` — decodes JWT exp, sets countdown timer
- `openCopilotAgentTool(prefillModel?)` — fetches available models from `/api/copilot/models`, renders select

---

## 12. vscars CLI Package

Located at `cli/`. Installed via:
```bash
pip install git+https://github.com/latenightstack/vscars.git
# or locally:
pip install -e /path/to/vscars/cli
```

### Commands

#### `vscars init [--server URL]`
Interactive setup:
1. Prompts for server URL (default: `https://vscars.latenightstack.com`)
2. Prompts for API key (get from dashboard → Plan & Billing → Generate API Key)
3. Validates key against server (`GET /api/auth/api-key` with `X-VSCARS-Key`)
4. Checks plan has `can_use_machine`
5. Registers machine (`POST /api/machines/register`)
6. Saves config to `~/.vscars/config.json` (chmod 600)

#### `vscars start`
Starts the WebSocket agent:
- Connects to `wss://{server}/ws/agent/{machine_token}`
- Listens for `tool_call` messages, executes locally, sends `tool_result`
- Auto-reconnects on disconnect (5s delay)
- Logs to `~/.vscars/agent.log`
- Writes PID to `~/.vscars/agent.pid`

#### `vscars stop`
Sends SIGTERM to agent PID.

#### `vscars status`
Shows config, agent PID status, pings server for health.

#### `vscars logs [-n N]`
Tails `~/.vscars/agent.log` (default 50 lines).

#### `vscars workspace <path>`
Sets default workspace for tool execution (saved to `~/.vscars/workspace.txt`).

### executor.py
Local mirror of server's `tools.py`. Handles the same tool names. Enforces workspace sandbox via `_resolve()`. Blocked dangerous command patterns same as server.

---

## 13. Environment Variables (.env)

```bash
# Database
DATABASE_URL=sqlite:///./vs_code_controller.db

# JWT
SECRET_KEY=                         # auto-generated if empty
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Server
HOST=0.0.0.0
PORT=8000
APP_BASE_URL=https://vscars.latenightstack.com
FORCE_HTTPS=true                    # enables HSTS header

# AI / GitHub Copilot
GITHUB_TOKEN=                       # GitHub personal token for Copilot API
ANTHROPIC_API_KEY=                  # for Claude models
OPENAI_API_KEY=                     # for GPT models
COPILOT_MODEL=gpt-4o

# Workspace
WORKSPACE_PATH=/path/to/default/workspace
COMMAND_TIMEOUT=120

# Stripe (all 4 required for billing to work)
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_PRO_MONTHLY=price_xxx
STRIPE_PRICE_TEAM_MONTHLY=price_xxx
STRIPE_PRICE_SELF_HOSTED_MONTHLY=price_xxx
STRIPE_PRICE_SELF_HOSTED_LIFETIME=price_xxx

# Self-hosted license signing
LICENSE_SIGNING_KEY=change-this-32-char-secret

# Email (Resend)
RESEND_API_KEY=re_xxx
FROM_EMAIL=VSCARS <noreply@yourdomain.com>
APP_NAME=VSCARS

# Ngrok (optional local tunneling)
NGROK_ENABLED=false
NGROK_AUTH_TOKEN=

# CORS (comma-separated origins, or * for open)
ALLOWED_ORIGINS=https://vscars.latenightstack.com
```

---

## 14. Running the App

### Development
```bash
cd vscars
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### With ngrok (for mobile access during dev)
```bash
/opt/homebrew/bin/ngrok http 8000
# Use native binary — not pyngrok (has SSL cert issues)
```

### Production (systemd)
```bash
sudo cp deploy/devpilot.service /etc/systemd/system/vscars.service
sudo systemctl enable vscars
sudo systemctl start vscars
# nginx reverse proxy — see deploy/nginx.conf
```

### First Run Behavior
- First registered user automatically becomes **superuser** with **pro plan**
- All subsequent registrations get **free plan**
- DB tables and migrations run automatically on startup

---

## 15. Subscription Tiers

| | Free | Pro ($9/mo) | Team ($29/mo) | Self-Hosted ($19/mo or $49 lifetime) |
|--|------|------------|--------------|-------------------------------------|
| AI Chat | ✅ Limited models | ✅ Standard models | ✅ All models | ✅ All models |
| Daily API calls | 50 | 1,000 | Unlimited | Unlimited |
| Machine registration | ❌ | ✅ | ✅ | ✅ |
| File browser | ❌ | ✅ (own machine) | ✅ | ✅ |
| Terminal / git | ❌ | ✅ (own machine) | ✅ | ✅ |
| CLI API key | ❌ | ✅ | ✅ | ✅ |
| Server host exposed | ❌ Never | ❌ Never | ❌ Never | N/A (they run their own) |

---

## 16. What Still Needs Doing

### Before Launch
- [ ] Create GitHub repo `latenightstack/vscars` and push CLI code
- [ ] Update `cli/setup.py` with real GitHub URL
- [ ] Set all 4 Stripe price IDs in `.env` on production server
- [ ] Configure `APP_BASE_URL` to `https://vscars.latenightstack.com`
- [ ] Set `FORCE_HTTPS=true` on production
- [ ] Test full flow: register → buy pro → generate API key → vscars init → vscars start → run tool

### Nice to Have
- [ ] Landing page at `static/landing.html`
- [ ] Email on successful machine registration
- [ ] Multiple machines UI (currently shows list but no way to pick which one to target)
- [ ] `vscars update` command (re-runs pip install from GitHub)
- [ ] Windows support in executor.py (`open_terminal` uses xterm on Linux, needs PowerShell path)
- [ ] Publish to PyPI when stable
