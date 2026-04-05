# VSCARS Project - Complete Structure Analysis

## Quick Overview
VSCARS is a **Python FastAPI-based web application** that allows remote control of VS Code and Copilot from mobile devices. It features:
- Multi-user authentication with role-based access
- Real-time tool execution via WebSocket
- Git integration with AI-generated commit messages
- Billing system with Stripe integration
- On-premise agent architecture for local execution

**Total Code:** 14,847 Python lines across 30+ files

---

## 1. DIRECTORY TREE

```
vscars/
├── main.py                      ← MAIN ENTRY POINT (FastAPI server start)
├── requirements.txt             ← Dependencies (20 packages)
├── .env                         ← Configuration
├── vs_code_controller.db        ← SQLite database
│
├── app/                         ← MAIN APPLICATION MODULE (6,450 LOC)
│   ├── main.py (2,336)          # FastAPI routes & WebSocket handlers
│   ├── tools.py (1,405)         # Tool execution engine (file, git, AI, command)
│   ├── database.py (463)        # ORM models & DB operations
│   ├── config.py (82)           # Config from environment
│   ├── auth.py (159)            # JWT & password authentication
│   ├── schemas.py (116)         # Pydantic request/response models
│   ├── git_ops.py (132)         # Git operations with AI commit messages
│   ├── jarvis.py (194)          # Natural language command interpreter
│   ├── email.py (84)            # Email service (Resend)
│   ├── relay.py (98)            # Relay server communication
│   ├── trust.py (181)           # Trust policies & tool approvals
│   ├── billing/                 # Billing module (669 LOC)
│   │   ├── routes.py (348)      # Stripe & license endpoints
│   │   ├── plan_limits.py (146) # Plan-based permission enforcement
│   │   ├── stripe_client.py (97) # Stripe API integration
│   │   └── license.py (78)      # License key generation & validation
│   └── utils/                   # Utilities (137 LOC)
│       ├── ngrok_helper.py (63) # Ngrok tunnel management
│       └── qr_code.py (73)      # QR code auth
│
├── cli/                         ← CLI AGENT MODULE (720 LOC)
│   ├── setup.py                 # Setuptools package config
│   └── vscars/
│       ├── cli.py (264)         # Command-line interface (vscars start/init/etc)
│       ├── agent.py (135)       # WebSocket agent client (persistent)
│       ├── executor.py (278)    # Local tool execution (mirrors server)
│       └── config.py (42)       # CLI configuration
│
├── static/                      ← FRONTEND (HTML/CSS/JS)
│   ├── index.html               # Main web UI
│   ├── setup.html               # Setup wizard
│   ├── script.js                # JavaScript logic
│   └── style.css                # Styling
│
├── deploy/                      ← DEPLOYMENT
│   ├── deploy.sh                # Deployment script
│   ├── nginx.conf               # Nginx reverse proxy config
│   ├── devpilot.service         # Systemd service file
│   └── requirements_and_steps.md # Deployment guide
│
├── scripts/                     ← UTILITIES
│   └── run_subscription_setup_checks.py
│
├── qa/                          ← QA TESTS & LOGS
│   ├── TEST_RUN_LOG.md
│   ├── AGENT_ASYNC_TEST.md
│   └── test results (JSON)
│
├── archive/                     ← LEGACY CODE
│   └── self-healing/            # Old self-healing system
│
└── Documentation/
    ├── README.md                # Main documentation
    ├── ARCHITECTURE.md          # System architecture
    ├── API.md                   # API reference
    ├── QUICK_START.md           # Getting started
    └── PROJECT_SUMMARY.md       # Project overview
```

---

## 2. FILE TYPES & STATISTICS

| Type | Count | Total LOC | Purpose |
|------|-------|-----------|---------|
| `.py` | 30+ | 14,847 | Python source code |
| `.md` | 11 | - | Documentation |
| `.html` | 4 | - | Web UI templates |
| `.css` | 3 | - | Stylesheets |
| `.js` | 1 | - | Frontend logic |
| `.json` | 4 | - | Config & test data |
| `.db` | 1 | - | SQLite database |
| `.sh` | 2 | - | Shell scripts |

---

## 3. KEY ENTRY POINTS

### **Server Entry Point: `main.py`**
```python
# Starts FastAPI server on HOST:PORT
- Loads .env configuration
- Initializes SQLite database
- Starts Ngrok tunnel (if enabled)
- Runs Uvicorn ASGI server
- Serves static files
- Handles WebSocket connections
```

### **CLI Entry Point: `cli/vscars/cli.py`**
```python
# Command-line interface
vscars init              # Register machine with account
vscars start             # Start agent (calls agent.py)
vscars stop              # Stop agent
vscars status            # Show configuration
vscars logs              # Tail agent logs
vscars workspace <path>  # Set workspace directory
```

### **Agent Entry Point: `cli/vscars/agent.py`**
```python
# Persistent WebSocket client (runs on user machine)
- Connects to relay WebSocket
- Sends ping every 25 seconds
- Listens for tool_call messages
- Executes tools via executor.py
- Sends results back
- Auto-reconnects on disconnect
```

---

## 4. CORE MODULES (By Size & Importance)

### **main.py (2,336 lines)** - FastAPI Application
**Purpose:** Central router with all API endpoints

**Route Groups:**
- `/register`, `/login`, `/me` - Authentication
- `/api/tools` - List available tools
- `/api/execute-tool` - Execute tool by name
- `/ws/{token}` - WebSocket for streaming execution
- `/api/permissions` - Get/request permissions
- `/api/files/*` - File operations
- `/api/git/*` - Git operations
- `/api/copilot/chat` - Copilot integration
- `/billing/*` - Stripe & license endpoints (mounted router)

**Key Functions:**
- `create_access_token()` - JWT generation
- `execute_tool_ws()` - WebSocket handler
- Middleware: CORS, rate limiting, auth

---

### **tools.py (1,405 lines)** - Tool Execution Engine
**Purpose:** Execute all commands on server (and mirrored on agent)

**Tool Categories:**
- **File Ops:** `open_file()`, `create_file()`, `edit_file()`, `delete_file()`, `list_files()`
- **Commands:** `run_command()`, `get_command_output()`
- **Git:** Calls to `git_ops.py` functions
- **VS Code:** `open_vscode()`, `read_vscode_output()`
- **AI/LLM:** `copilot_chat()`, `claude_chat()`, `openai_chat()`
- **JARVIS NLP:** Convert natural language to commands

**Security:**
```python
_get_workspace()  # Get user workspace root
_resolve(path)    # Validate path is within workspace
```

---

### **database.py (463 lines)** - ORM Models
**Purpose:** SQLAlchemy database schema & operations

**Models:**
```
User, UserPermission, AccessRequest
CommandLog, ConversationHistory
PasswordResetToken, IdeaNote, SavedWorkflow
UserSession, RegisteredMachine
TrustPolicy, ToolApproval
AgentTask, AgentSession, AgentSessionMessage
LicenseKey, TokenBlacklist
```

**Key Functions:**
- `init_db()` - Create tables
- `get_db()` - FastAPI dependency
- `SessionLocal` - SQLAlchemy session

---

### **auth.py (159 lines)** - Authentication
**Functions:**
- `hash_password()` - Bcrypt/Argon2 hashing
- `verify_password()` - Password check
- `create_access_token()` - JWT generation
- `get_current_user()` - FastAPI dependency
- `check_permission()` - Permission validation

---

### **config.py (82 lines)** - Configuration Management
**Variables:**
```
HOST, PORT, DATABASE_URL
SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
GITHUB_TOKEN, COPILOT_MODEL
WORKSPACE_PATH, COMMAND_TIMEOUT, MAX_FILE_SIZE
STRIPE_SECRET_KEY, STRIPE_PRICE_IDs
LICENSE_SIGNING_KEY, APP_BASE_URL
NGROK_ENABLED, NGROK_AUTH_TOKEN
RESEND_API_KEY, FROM_EMAIL
```

---

### **git_ops.py (132 lines)** - Git Integration
**Functions:**
```
git_status()              # Repo status
git_diff()                # Staged/unstaged diffs
git_stage(path)           # Stage files
git_unstage(path)         # Unstage files
git_commit(message)       # Create commit
git_push()                # Push to remote
git_log()                 # Commit history
git_branches()            # List branches
git_ai_commit_message()   # AI-generated message
```

---

### **billing/** (669 lines) - Billing Module
**Structure:**
- `routes.py` (348) - License key & subscription endpoints
- `plan_limits.py` (146) - Feature limits by plan
- `stripe_client.py` (97) - Stripe API integration
- `license.py` (78) - License key generation & validation

**Plans:**
- Free (limited tools)
- Pro ($9/mo)
- Team ($29/mo)
- Self-Hosted ($19/mo or $49 lifetime)

---

### **cli/vscars/executor.py (278 lines)** - Local Tool Executor
**Purpose:** Mirrors `tools.py` but runs on client machine

- Same tool handlers as server
- Respects workspace path
- Path validation with `_resolve()`
- Results sent back via WebSocket

---

## 5. DEPENDENCY FLOWCHART

```
┌─────────────────────────────────────────────────────┐
│         main.py (ENTRY POINT)                       │
│         FastAPI application                         │
└─────────────────────────────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    ┌────────┐   ┌────────┐   ┌────────┐
    │config  │   │database│   │auth    │
    └────────┘   └────────┘   └────────┘
         │            │            │
         └────────────┼────────────┘
                      ▼
         ┌──────────────────────┐
         │  Core Dependencies   │
         ├──────────────────────┤
         │ • FastAPI            │
         │ • SQLAlchemy         │
         │ • PyJWT              │
         │ • Pydantic           │
         └──────────────────────┘
         
         ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ tools    │  │ git_ops  │  │ schemas  │
    │ (execute)│  │ (git)    │  │ (validate)
    └──────────┘  └──────────┘  └──────────┘
         │              │
         ▼              ▼
    ┌──────────┐  ┌──────────┐
    │ jarvis   │  │ subprocess
    │ (NLP)    │  │ (execute)
    └──────────┘  └──────────┘

    ┌──────────────┐  ┌──────────────┐
    │ billing      │  │ trust        │
    │ • routes     │  │ • policies   │
    │ • stripe     │  │ • approvals  │
    │ • license    │  └──────────────┘
    │ • plan_limits│
    └──────────────┘

    ┌──────────────┐  ┌──────────────┐
    │ utils        │  │ relay        │
    │ • ngrok      │  │ • websocket  │
    │ • qr_code    │  │ • messaging  │
    └──────────────┘  └──────────────┘

    ┌──────────────┐  ┌──────────────┐
    │ email        │  │ External APIs│
    │ • resend     │  │ • Stripe     │
    └──────────────┘  │ • Resend     │
                      │ • Ngrok      │
                      │ • GitHub API │
                      └──────────────┘
```

---

## 6. DATABASE MODELS (13 tables)

```sql
users                    -- User accounts
user_permissions        -- Per-user tool permissions
access_requests         -- Access control requests
command_log             -- Command execution history
conversation_history    -- AI conversation logs
password_reset_tokens   -- Password reset links
idea_notes              -- User notes
saved_workflows         -- Saved command sequences
user_sessions           -- Active sessions
registered_machines     -- Registered on-premise agents
trust_policies          -- Trust rules for tools
tool_approvals          -- Tool execution approvals
license_keys            -- License key records
```

---

## 7. PYTHON DEPENDENCIES (requirements.txt)

```
# Web Framework (3)
fastapi>=0.104.0       # API framework
uvicorn>=0.24.0        # ASGI server
slowapi>=0.1.9         # Rate limiting

# Database (1)
sqlalchemy>=2.0.0      # ORM

# Authentication (3)
PyJWT>=2.12.0          # JWT tokens
passlib>=1.7.4         # Password utilities
bcrypt>=4.1.0          # Hash & verify
argon2-cffi>=23.1.0    # Alternative hashing

# External APIs (3)
stripe>=7.0.0          # Stripe billing
resend>=0.8.0          # Email service
requests>=2.31.0       # HTTP client

# Async & WebSocket (1)
websockets>=12.0       # WebSocket support

# Data Validation (2)
pydantic>=2.5.0        # Request validation
python-multipart>=0.0.6 # File uploads

# Config & Utils (4)
python-dotenv>=1.0.0   # .env parsing
qrcode>=7.4.0          # QR code generation
pillow>=10.0.0         # Image processing
pyngrok>=6.2.1         # Ngrok tunneling
gunicorn>=21.2.0       # Production WSGI
```

---

## 8. Configuration Files

| File | Type | Purpose |
|------|------|---------|
| `.env` | ENV | App settings (keys, URLs, secrets) |
| `requirements.txt` | pip | Python dependencies |
| `cli/setup.py` | Python | CLI package installation |
| `deploy/nginx.conf` | Nginx | Reverse proxy config |
| `deploy/devpilot.service` | Systemd | Linux service config |
| `ARCHITECTURE.md` | Markdown | System design docs |
| `API.md` | Markdown | API documentation |

---

## 9. SECURITY BOUNDARIES

### **1. Path Validation**
```python
# tools.py & executor.py
_resolve(path) ensures:
  - Path is within WORKSPACE_PATH
  - /tmp/ is allowed for temp files
  - Prevents directory traversal
```

### **2. Authentication**
```python
# auth.py
- JWT tokens with 30-minute expiry
- Bcrypt/Argon2 password hashing
- get_current_user() dependency on all protected routes
```

### **3. Authorization**
```python
# trust.py & database.py
- Per-user tool permissions
- Superuser approval workflows
- Tool approval records
```

### **4. Rate Limiting**
```python
# main.py (SlowAPI)
- Request rate limits
- Prevents brute force
```

### **5. License Signing**
```python
# billing/license.py
- HMAC-SHA256 signing
- License_SIGNING_KEY validation
```

---

## 10. EXECUTION FLOW

### **Server Execution:**
```
Client Request
    ↓
main.py route handler
    ↓
get_current_user() ← JWT validation
    ↓
check_permission() ← Tool permission check
    ↓
execute_tool(tool_name, input)
    ↓
tools.py handler
    ├─ File operations
    ├─ Git operations (via git_ops.py)
    ├─ Command execution (subprocess)
    ├─ AI/LLM integration
    └─ JARVIS NLP
    ↓
Response sent (REST or WebSocket)
```

### **Agent (Local) Execution:**
```
cli.py → vscars start
    ↓
agent.py (persistent WebSocket client)
    ↓
Listen for tool_call messages
    ↓
executor.py (mirrors tools.py)
    ├─ Execute locally
    └─ Path validation via _resolve()
    ↓
Send results via WebSocket back to server
```

---

## 11. API ENDPOINTS SUMMARY

### **Authentication**
- `POST /register` - Register new user
- `POST /login` - JWT login
- `GET /me` - Current user profile

### **Tools**
- `GET /api/tools` - List available tools
- `POST /api/execute-tool` - Execute tool
- `WS /ws/{token}` - WebSocket streaming

### **Files**
- `GET /api/files` - List files
- `GET /api/files/{path}` - Read file
- `POST /api/files/{path}` - Create/edit file

### **Git**
- `GET /api/git/status` - Repo status
- `GET /api/git/log` - Commit history
- `POST /api/git/commit` - Make commit
- `POST /api/git/push` - Push commits

### **AI**
- `POST /api/copilot/chat` - Copilot integration
- `POST /api/chat` - General AI chat

### **Permissions**
- `GET /api/permissions` - User permissions
- `POST /api/request-access` - Request access
- `POST /api/grant-permission` - Grant permission

### **Billing**
- `POST /billing/license` - Generate license
- `POST /billing/verify` - Verify license
- `POST /billing/webhook` - Stripe webhook

---

## 12. DEPLOYMENT ARCHITECTURE

```
Production Environment:
┌──────────────────────────────────┐
│  Client (Mobile Browser)          │
└──────────────────────────────────┘
           ↓ HTTPS
┌──────────────────────────────────┐
│  Nginx Reverse Proxy              │
│  (SSL Termination, Routing)       │
└──────────────────────────────────┘
           ↓ HTTP
┌──────────────────────────────────┐
│  Uvicorn Server                   │
│  (FastAPI, Port 8000)             │
└──────────────────────────────────┘
           ↓ File I/O & Subprocess
┌──────────────────────────────────┐
│  SQLite Database                  │
│  (vs_code_controller.db)          │
└──────────────────────────────────┘

Optional:
┌──────────────────────────────────┐
│  Ngrok Tunnel (Public URL)        │
│  (For Remote Access)              │
└──────────────────────────────────┘

Client Machines (via Agent):
┌──────────────────────────────────┐
│  vscars Agent (WebSocket Client)  │
│  Connects to Relay                │
│  Executes Tools Locally           │
└──────────────────────────────────┘
```

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total Python LOC | 14,847 |
| Total Modules | 30+ |
| Main Entry Points | 2 (server, CLI) |
| Database Tables | 13 |
| API Routes | 20+ |
| External Dependencies | 20 |
| Authentication Methods | JWT + Password Hash |
| Billing Plans | 4 (Free, Pro, Team, Self-Hosted) |
| Security Layers | 5 (Auth, Authz, Path, Rate Limit, License) |

