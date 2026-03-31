# 🎮 Project Architecture & Components

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    MOBILE PHONE (Anywhere)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Browser UI (Responsive Web Application)            │   │
│  │  - Login/Register                                   │   │
│  │  - Dashboard with Quick Actions                     │   │
│  │  - Tools Panel (File/Command/Copilot)              │   │
│  │  - Admin Panel (for Superuser)                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↕ HTTPS (Ngrok)
┌─────────────────────────────────────────────────────────────┐
│                    YOUR PC (Always On)                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  FastAPI Web Server (Python) - Port 8000            │   │
│  │                                                      │   │
│  │  Authentication Layer (JWT)                         │   │
│  │  ├─ Register/Login                                 │   │
│  │  ├─ Token Validation                               │   │
│  │  └─ Permission Checking                            │   │
│  │                                                      │   │
│  │  Tools Layer                                        │   │
│  │  ├─ File Operations (open, create, edit, delete)   │   │
│  │  ├─ Command Execution (shell commands)             │   │
│  │  ├─ File Browser (list, browse)                    │   │
│  │  └─ Copilot Integration                            │   │
│  │                                                      │   │
│  │  Database Layer (SQLite)                           │   │
│  │  ├─ Users & Authentication                         │   │
│  │  ├─ Permissions & Access Control                   │   │
│  │  └─ Access Requests & QR Codes                     │   │
│  │                                                      │   │
│  │  ┌────────────────────────────────────┐            │   │
│  │  │  Ngrok Integration (Remote Access) │            │   │
│  │  │  Generates public HTTPS URL        │            │   │
│  │  └────────────────────────────────────┘            │   │
│  └──────────────────────────────────────────────────────┘   │
│                           ↓                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         VS Code & Copilot (Local Control)           │   │
│  │  - File opening/editing                            │   │
│  │  - Command execution                               │   │
│  │  - Copilot Chat integration                        │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
LLM redefined/
├── app/                          # Python FastAPI application
│   ├── __init__.py
│   ├── main.py                  # FastAPI app + routes
│   ├── config.py                # Configuration management
│   ├── database.py              # SQLAlchemy models (User, Permissions, Requests)
│   ├── schemas.py               # Pydantic validation schemas
│   ├── auth.py                  # JWT + Password hashing
│   ├── tools.py                 # VS Code tools (file/command/copilot)
│   └── utils/
│       ├── __init__.py
│       ├── qr_code.py           # QR code generation (PIL + qrcode)
│       └── ngrok_helper.py      # Ngrok tunnel management
│
├── static/                       # Frontend files (served by FastAPI)
│   ├── index.html               # Responsive web UI
│   ├── style.css                # Beautiful styling
│   └── script.js                # Frontend logic + API calls
│
├── venv/                        # Python virtual environment
│
├── main.py                      # Entry point script
├── requirements.txt             # Python dependencies
├── .env                         # Configuration (SUPERUSER_PHONE, etc)
├── vs_code_controller.db        # SQLite database (created on first run)
├── README.md                    # Full documentation
├── QUICK_START.md               # Quick setup guide
└── ARCHITECTURE.md              # This file
```

## Technology Stack

### Backend
- **Framework**: FastAPI (modern, fast Python web framework)
- **Server**: Uvicorn (ASGI server)
- **Database**: SQLite + SQLAlchemy ORM
- **Auth**: JWT tokens + bcryptpassword hashing
- **Remote Access**: Ngrok (free tunneling service)

### Frontend
- **HTML5** - Semantic markup
- **CSS3** - Responsive design (mobile-first)
- **Vanilla JavaScript** - No dependencies, pure DOM manipulation
- **API**: Fetch API for REST calls

### Security
- JWT token-based authentication
- Bcrypt password hashing
- Role-based access control (RBAC)
- Permission system (Superuser + Regular users)
- QR code authentication requests

## Data Flow

### Login/Register Flow
```
1. User opens web UI in phone browser
2. Clicks "Register" or "Login"
3. Frontend sends POST to /api/auth/register or /api/auth/login
4. Backend validates credentials
5. Backend generates JWT token
6. Frontend stores token in localStorage
7. Frontend redirects to dashboard
8. All subsequent requests include token in Authorization header
```

### Tool Execution Flow
```
1. User opens Tools → clicks on tool (e.g., "Open File")
2. Modal prompts for parameters (filepath, line number)
3. User clicks "Execute"
4. Frontend POST to /api/tools/execute with:
   {
     "tool": "open_file",
     "filepath": "/path/to/file.ts",
     "line": 42
   }
5. Backend validates JWT token
6. Backend checks user permissions
7. Backend executes tool (VSCodeTools.open_file)
8. Tool runs 'code /path/to/file.ts:42' command
9. VS Code opens file on your PC
10. Backend returns result to frontend
11. Frontend displays output in modal
```

### QR Code Authentication Flow
```
1. New user in "QR Access" tab → enters details
2. Frontend POST to /api/access/request-via-qr
3. Backend generates QR code image (base64 PNG)
4. Backend stores request in database
5. Frontend displays QR code to user
6. User tells superuser: "Scan my QR code"
7. Superuser goes to Admin Panel
8. Superuser sees pending requests with QR codes
9. Superuser clicks "Approve"
10. User's permissions updated in database
11. User can now log in and has permissions
```

## Authentication & Authorization

### User Types
1. **Superuser**
   - Device ID matches SUPERUSER_PHONE in .env
   - All permissions automatically granted
   - Can manage other users
   - Can approve/reject access requests

2. **Regular User**
   - Device ID is unique
   - Starts with view-only permissions
   - Superuser can grant additional permissions
   - Can request access via QR code

### Permission System
- **view** - Read files, browse directories
- **edit** - Create, modify, delete files
- **commands** - Execute shell commands
- **copilot** - Access Copilot Chat

### JWT Token
- Contains: username, exp (expiration time)
- Expires: 30 minutes (configurable)
- Stored: Browser localStorage (frontend)
- Sent: Authorization header (Bearer {token})

## Database Schema

### Users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR UNIQUE,
    email VARCHAR UNIQUE,
    hashed_password VARCHAR,
    device_id VARCHAR UNIQUE,  -- Phone identifier
    is_superuser BOOLEAN,
    is_active BOOLEAN,
    created_at DATETIME
);
```

### Permissions Table
```sql
CREATE TABLE user_permissions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    can_run_copilot BOOLEAN,
    can_run_commands BOOLEAN,
    can_edit_files BOOLEAN,
    can_view_files BOOLEAN,  -- Always true for authenticated
    created_at DATETIME
);
```

### Access Requests Table
```sql
CREATE TABLE access_requests (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    request_type VARCHAR,  -- 'qr_code' or 'direct'
    qr_code_data TEXT,     -- QR image (base64)
    status VARCHAR,        -- 'pending', 'approved', 'rejected'
    created_at DATETIME,
    resolved_at DATETIME
);
```

## API Endpoints Summary

```
Authentication:
  POST   /api/auth/register
  POST   /api/auth/login
  GET    /api/auth/me

Tools:
  GET    /api/tools
  POST   /api/tools/execute

Access Management:
  POST   /api/access/request-via-qr
  GET    /api/access/pending-requests    [SUPERUSER]
  POST   /api/access/approve/{id}        [SUPERUSER]
  POST   /api/access/reject/{id}         [SUPERUSER]

Permissions:
  GET    /api/permissions/{user_id}      [SUPERUSER]
  PUT    /api/permissions/{user_id}      [SUPERUSER]

System:
  GET    /api/health
  GET    /api/ngrok/url                  [SUPERUSER]
  GET    /                               (serves index.html)
```

## Deployment Options

### Option 1: Local Network Only
```
venv) $ python main.py
# Access from phone on same WiFi: http://192.168.X.X:8000
```

### Option 2: Remote with Ngrok
```
# Edit .env
NGROK_ENABLED=true
NGROK_AUTH_TOKEN=your_token

venv) $ python main.py
# Public URL: https://abc123.ngrok.io
# Access from anywhere in world
```

### Option 3: Custom VPS
```
# Deploy to cloud VPS with SSL certificate
gunicorn -w 4 -b 0.0.0.0:8000 app.main:app
# Access via custom domain with HTTPS
```

## Performance Considerations

- **SQLite Limitation**: Single file-based DB, not for 100s of concurrent users
  - For scaling: Switch to PostgreSQL
- **Ngrok Free Tier**: 40 requests/minute, 2 hours session limit
  - For production: Use paid Ngrok plan or custom domain
- **File Operations**: Direct file system access on your PC
  - Security: Validate paths to prevent directory traversal
- **Command Execution**: Runs on your PC (sandboxed to your user)
  - Security: Superuser-only or permission-based

## Security Best Practices

1. ✅ **Change SECRET_KEY** in .env (not default)
2. ✅ **Use HTTPS** with Ngrok (automatically done)
3. ✅ **Strong Passwords** for superuser account
4. ✅ **Unique Device IDs** per user
5. ✅ **Path Validation** before file operations (implement)
6. ✅ **Command Whitelisting** (optional, implement for prod)
7. ✅ **Rate Limiting** (not implemented, add for prod)

## Extending the System

### Add New Tools
1. Add method to `VSCodeTools` class in `app/tools.py`
2. Add tool entry to `TOOLS` list with permission requirement
3. Tool automatically appears in Tools panel

Example:
```python
@staticmethod
def my_new_tool(param1: str, param2: str) -> str:
    # Implementation
    return f"✅ Done: {param1} {param2}"

# Add to TOOLS list:
{
    "name": "my_new_tool",
    "description": "Does something cool",
    "required_permission": "commands",
    "handler": VSCodeTools.my_new_tool
}
```

### Add OAuth Integration
1. Add oauth2-related dependencies
2. Modify `/api/auth/login` to support OAuth
3. Update frontend to show OAuth button

### Add WebSockets
1. Use FastAPI WebSockets
2. Real-time command output streaming
3. Live file content updates

## Troubleshooting Architecture

### Token Issues
- Check JWT_SECRET_KEY is same across app runs
- Tokens expire in 30 min (configurable)
- localStorage persists across refreshes

### Database Issues
- SQLite locks if two processes access simultaneously
- Use PostgreSQL for concurrent access
- Backup database before major changes

### Ngrok Connection
- Check auth token is valid
- Free tier has session limits
- Can't reconnect old URL after restart

### File Access
- Ensure file paths are absolute
- VS Code `code` command must be in PATH
- Windows paths: Use forward slashes or escape backslashes

---

This architecture provides a **secure**, **scalable**, and **user-friendly** way to control your VS Code from anywhere in the world!
