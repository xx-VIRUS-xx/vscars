# VSCARS - Quick Reference Guide

## Project Overview
**VSCARS** = VS Code Copilot Access Remote Service
- **Type**: Python FastAPI web application
- **Purpose**: Control VS Code & Copilot from mobile devices
- **Architecture**: Client-server with on-premise agents
- **Size**: 14,847 lines of Python code across 30+ files
- **Database**: SQLite (13 tables)

---

## Starting the Server

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env  # Edit with your settings

# 3. Run server
python main.py

# Server runs on http://localhost:8000
# Open in mobile browser or desktop browser
```

---

## Starting an Agent (On Your Machine)

```bash
# 1. Install CLI package
cd cli
pip install -e .

# 2. Initialize agent
vscars init --api-key YOUR_API_KEY

# 3. Start agent
vscars start

# Agent connects to relay server and waits for commands
```

---

## Key Files & Their Roles

| File | LOC | Purpose |
|------|-----|---------|
| `main.py` | 2,336 | FastAPI server with all API routes |
| `app/tools.py` | 1,405 | Core tool execution engine |
| `app/database.py` | 463 | ORM models & database |
| `app/config.py` | 82 | Environment configuration |
| `app/auth.py` | 159 | JWT authentication |
| `app/git_ops.py` | 132 | Git integration |
| `cli/vscars/agent.py` | 135 | WebSocket agent client |
| `cli/vscars/executor.py` | 278 | Local tool execution |
| `app/billing/routes.py` | 348 | Stripe & license endpoints |
| `app/jarvis.py` | 194 | Natural language interpreter |

---

## Architecture at a Glance

```
┌─────────────────────────────────────┐
│  Mobile Browser / Desktop Client    │
└──────────────┬──────────────────────┘
               │ REST/WebSocket
               ▼
    ┌──────────────────────────┐
    │  Main FastAPI Server     │
    │  (app/main.py)           │
    │  ├─ Authentication       │
    │  ├─ File operations      │
    │  ├─ Git operations       │
    │  ├─ AI/Copilot           │
    │  └─ Billing              │
    └──────────────────────────┘
               ▲
               │ Optional: On-Premise Agent
               │ (WebSocket Connection)
               │
    ┌──────────────────────────┐
    │  CLI Agent               │
    │  (cli/vscars/agent.py)   │
    │  └─ Local Tool Executor  │
    │     (executor.py)        │
    └──────────────────────────┘
              User's Machine
```

---

## Database Schema

13 Main Tables:

```
Authentication & Users:
├─ users
├─ user_permissions
├─ access_requests
└─ token_blacklist

Sessions & Logs:
├─ command_log
├─ conversation_history
├─ user_sessions
└─ agent_sessions

Content & Workflows:
├─ idea_notes
├─ saved_workflows
├─ password_reset_tokens
└─ registered_machines

Security & Billing:
├─ trust_policies
├─ tool_approvals
└─ license_keys
```

---

## API Routes Overview

### Authentication
```
POST   /register          Register new user
POST   /login             Login & get JWT token
GET    /me                Get current user profile
```

### Tools & Execution
```
GET    /api/tools                    List available tools
POST   /api/execute-tool             Execute tool
WS     /ws/{token}                   WebSocket for streaming
```

### Files
```
GET    /api/files                    List files
GET    /api/files/{path}             Read file
POST   /api/files/{path}             Create/edit file
```

### Git
```
GET    /api/git/status               Get git status
GET    /api/git/log                  Get commit history
POST   /api/git/commit               Create commit
POST   /api/git/push                 Push commits
```

### Permissions
```
GET    /api/permissions              Get user permissions
POST   /api/request-access           Request tool access
POST   /api/grant-permission         Grant permission (superuser)
```

### AI/Copilot
```
POST   /api/copilot/chat             Chat with Copilot
POST   /api/chat                     Chat with AI
```

### Billing
```
POST   /billing/subscribe             Subscribe to plan
POST   /billing/license               Generate license key
POST   /billing/verify                Verify license
POST   /billing/webhook               Stripe webhook
```

---

## Environment Variables (.env)

### Server Settings
```
HOST=0.0.0.0
PORT=8000
DATABASE_URL=sqlite:///./vs_code_controller.db
```

### JWT & Security
```
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### API Keys
```
GITHUB_TOKEN=ghp_...
COPILOT_MODEL=gpt-4o
```

### Workspace
```
WORKSPACE_PATH=/Users/xxvirusxx
COMMAND_TIMEOUT=120
MAX_FILE_SIZE=5242880
```

### Stripe Billing
```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_TEAM_MONTHLY=price_...
```

### Ngrok (Optional)
```
NGROK_ENABLED=false
NGROK_AUTH_TOKEN=your_token
```

---

## Authentication Flow

```
1. User Registration
   POST /register
   ├─ Username, email, password
   └─ Creates user in database

2. User Login
   POST /login
   ├─ Username/password
   └─ Returns JWT token

3. Request to Protected Route
   GET /api/permissions
   ├─ Header: Authorization: Bearer {token}
   └─ get_current_user() validates token

4. Token Expiry
   ├─ Expired (30 min default)
   └─ User must login again
```

---

## Permission System

### Levels
- **Superuser**: Full access, can grant permissions
- **Regular User**: Limited permissions, needs approval

### Granular Permissions
- `view_files` - Can view files
- `edit_files` - Can create/edit/delete files
- `run_commands` - Can execute commands
- `run_copilot` - Can use Copilot

### Access Control Flow
```
1. User requests tool
2. Check user permissions in database
3. Check trust policies for tool
4. Execute tool or return 403 Forbidden
```

---

## Tool Execution

### Available Tools

**File Operations**:
- `open_file` - Read file content
- `create_file` - Create new file
- `edit_file` - Modify file
- `delete_file` - Delete file
- `list_files` - List directory

**Command Execution**:
- `run_command` - Execute shell command
- `get_command_output` - Get command result

**Git Operations**:
- `git_status` - Repository status
- `git_diff` - View changes
- `git_commit` - Make commit
- `git_push` - Push to remote
- `git_log` - View history

**AI/LLM**:
- `copilot_chat` - Chat with Copilot
- `claude_chat` - Chat with Claude
- `openai_chat` - Chat with OpenAI

**VS Code**:
- `open_vscode` - Open file in VS Code
- `read_vscode_output` - Read VS Code output

---

## Security Features

### 1. Path Validation
```python
# tools.py & executor.py
_resolve(path)
├─ Ensures path is within WORKSPACE_PATH
├─ Prevents directory traversal
└─ Allows /tmp for temporary files
```

### 2. Authentication
```
JWT Token + Password Hash
├─ Bcrypt/Argon2 password hashing
├─ 30-minute token expiry
└─ Token blacklist for logout
```

### 3. Authorization
```
Permission System
├─ Per-user tool permissions
├─ Superuser approval workflows
└─ Tool approval records
```

### 4. Rate Limiting
```
SlowAPI Middleware
├─ Request rate limits
└─ Prevents brute force
```

### 5. License Signing
```
HMAC-SHA256
├─ License keys signed with LICENSE_SIGNING_KEY
└─ Validation ensures authenticity
```

---

## Billing Plans

### Free
- Limited tool access
- Community support

### Pro ($9/month)
- All tools
- Email support
- Command history

### Team ($29/month)
- Team management
- Advanced permissions
- Priority support

### Self-Hosted ($19/month or $49 lifetime)
- Deploy on your server
- No dependency on external service

---

## Common Tasks

### Add a New Tool

1. **Define in tools.py**:
```python
def my_tool(input_data: str) -> str:
    # Implement tool logic
    return result
```

2. **Register in TOOLS dict**:
```python
TOOLS = {
    "my_tool": {"description": "...", "params": {...}}
}
```

3. **Call via API**:
```
POST /api/execute-tool
{
  "tool_name": "my_tool",
  "input": "..."
}
```

### Add a New Route

1. **In main.py**:
```python
@app.get("/api/my-endpoint")
def my_endpoint(current_user = Depends(get_current_user)):
    # Implement logic
    return response
```

2. **Route is now available**:
```
GET /api/my-endpoint
```

### Check Database

```bash
# View tables
sqlite3 vs_code_controller.db ".schema"

# Query data
sqlite3 vs_code_controller.db "SELECT * FROM users;"
```

---

## Troubleshooting

### Server won't start
```
✓ Check Python version (3.8+)
✓ Check requirements installed: pip install -r requirements.txt
✓ Check .env file configured
✓ Check port 8000 not in use
```

### Agent can't connect
```
✓ Check relay server URL in CLI config
✓ Check API key is valid
✓ Check firewall allows WebSocket
✓ Check agent logs: vscars logs
```

### Permission denied on file
```
✓ Check path is within WORKSPACE_PATH
✓ Check user has edit_files permission
✓ Check file exists and is readable
```

### Stripe webhook failing
```
✓ Check STRIPE_WEBHOOK_SECRET in .env
✓ Verify webhook is configured in Stripe dashboard
✓ Check endpoint is publicly accessible
```

---

## Deployment

### Quick Deploy (Development)
```bash
python main.py
```

### Production Deploy
```bash
# Using Gunicorn + Nginx
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker

# With Nginx reverse proxy
# See deploy/nginx.conf for configuration

# Enable Ngrok for remote access
export NGROK_ENABLED=true
export NGROK_AUTH_TOKEN=your_token
python main.py
```

---

## Performance Tips

- **Command Timeout**: Increase `COMMAND_TIMEOUT` for long builds
- **Max File Size**: Adjust `MAX_FILE_SIZE` (default 5MB)
- **Database**: Use PostgreSQL for >1K concurrent users
- **Caching**: Implement Redis for frequently accessed data
- **Rate Limiting**: Adjust limits in SlowAPI middleware

---

## File Structure Summary

```
Total Python Code: 14,847 lines
Total Modules: 30+
Total Dependencies: 20
Database Tables: 13
API Routes: 20+
```

---

## Getting Help

- **Documentation**: See ARCHITECTURE.md, API.md
- **Quick Start**: See QUICK_START.md
- **Installation**: See INSTALLATION.md
- **Issues**: Check qa/ directory for test logs
- **Code**: Well-commented source code in app/ and cli/

