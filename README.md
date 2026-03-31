# 🎮 VS Code Copilot Mobile Controller

A **Python-based web application** that allows you to control VS Code and Copilot from any mobile device worldwide. Features role-based access control, QR code authentication, and remote access via Ngrok.

## ✨ Features

### Core Features
- **🔐 Multi-User Authentication** - Register, login, JWT tokens
- **📱 Mobile Web Interface** - Beautiful responsive UI for mobile devices
- **🔑 Role-Based Access Control** - Superuser + Regular users with granular permissions
- **🌍 Remote Access** - Control VS Code from anywhere using Ngrok
- **📁 File Management** - Open, create, edit, delete files remotely
- **⚡ Command Execution** - Run shell commands from your phone
- **💬 Copilot Integration** - Ask Copilot directly from mobile
- **🛡️ Security** - JWT authentication, password hashing, permission system

### Authentication Methods
1. **Direct Registration** - Username/password signup with superuser detection
2. **QR Code Access** - Request access via QR code, superuser approves
3. **Access Control** - Superuser grants specific permissions to users

### Permission System
- **View Files** - Browse and read files (all authenticated users)
- **Edit Files** - Create, modify, delete files (requires permission)
- **Run Commands** - Execute shell commands (requires permission)
- **Run Copilot** - Access Copilot Chat (requires permission)

## Installation

### Prerequisites
- Python 3.8+
- VS Code (installed and in PATH)
- pip or poetry
- Ngrok account (optional, for remote access)

### Setup

1. **Navigate to project**
   ```bash
   cd "LLM redefined"
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

## Usage

### 1. Set Your Superuser Device ID

Edit `.env`:
```env
SUPERUSER_PHONE=iPhone-12-XXX  # Your phone's device ID (used during registration)
```

### 2. Start the Server

```bash
python main.py
```

You'll see:
```
============================================================
🎮 VS Code Copilot Mobile Controller
============================================================
📍 Server: http://0.0.0.0:8000
🌐 API: http://0.0.0.0:8000/api
💻 Web UI: http://0.0.0.0:8000
============================================================
```

### 3. Access the Web Interface

- **Local Network**: `http://localhost:8000`
- **From Phone on Same Network**: `http://<your-pc-ip>:8000`

### 4. Set Up Remote Access with Ngrok

**Get Ngrok token:**
1. Sign up at [ngrok.com](https://ngrok.com)
2. Get your auth token from dashboard
3. Update `.env`:
   ```env
   NGROK_ENABLED=true
   NGROK_AUTH_TOKEN=your_token_here
   ```

4. Restart the server - you'll get a public URL to use worldwide!

## Architecture

```
project/
├── app/
│   ├── main.py           # FastAPI application
│   ├── config.py         # Configuration management
│   ├── database.py       # SQLAlchemy models
│   ├── schemas.py        # Pydantic schemas
│   ├── auth.py          # Authentication & JWT
│   ├── tools.py         # VS Code tools
│   ├── utils/
│   │   ├── qr_code.py   # QR code generation
│   │   └── ngrok_helper.py  # Ngrok integration
│   └── __init__.py
├── static/
│   ├── index.html       # Web interface
│   ├── style.css        # Styling
│   └── script.js        # Frontend logic
├── main.py              # Entry point
├── requirements.txt     # Dependencies
├── .env                 # Environment variables
└── README.md
```

## Authentication Flow

### Flow 1: Direct Registration (First Superuser)
```
1. Mobile Browser → Registration page
2. Enter: username, email, password, device_id
3. Device ID matches SUPERUSER_PHONE? → Registered as SUPERUSER
4. Get JWT token
5. Access ALL features
```

### Flow 2: Direct Registration (Regular User)
```
1. Mobile Browser → Registration page
2. Enter: username, email, password, device_id  
3. Device ID doesn't match SUPERUSER → Regular user
4. Get JWT token
5. Can only VIEW files initially
6. Superuser must grant permissions
```

### Flow 3: QR Code Access Request
```
1. Regular user → "QR Access" tab
2. Enter: username, email, device_id
3. System generates QR code
4. Superuser scans QR code with PC
5. Superuser approves/rejects in Admin Panel
6. User gains requested permissions
```

## API Endpoints

### Authentication
```http
POST /api/auth/register
POST /api/auth/login
GET /api/auth/me
```

### Tools (File & Command Operations)
```http
GET /api/tools                    # List available tools
POST /api/tools/execute           # Execute a tool
```

### Access Management
```http
POST /api/access/request-via-qr   # Request access with QR
GET /api/access/pending-requests  # Get pending requests [SUPERUSER]
POST /api/access/approve/{id}     # Approve request [SUPERUSER]
POST /api/access/reject/{id}      # Reject request [SUPERUSER]
```

### Permissions
```http
GET /api/permissions/{user_id}    # Get user permissions [SUPERUSER]
PUT /api/permissions/{user_id}    # Update permissions [SUPERUSER]
```

### System
```http
GET /api/health                   # Health check
GET /api/ngrok/url               # Get public URL [SUPERUSER]
```

## API Usage Examples

### Register as Superuser
```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@example.com",
    "password": "secure123",
    "device_id": "iPhone-12-XXX"
  }'
```

### Login
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "secure123",
    "device_id": "iPhone-12-XXX"
  }'
```

### Execute Tool (Create File)
```bash
curl -X POST http://localhost:8000/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "tool": "create_file",
    "filepath": "/Users/username/test.txt",
    "content": "Hello from mobile!"
  }'
```

### Run Command
```bash
curl -X POST http://localhost:8000/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "tool": "run_command",
    "command": "npm run build",
    "cwd": "/path/to/project"
  }'
```

### Ask Copilot
```bash
curl -X POST http://localhost:8000/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "tool": "ask_copilot",
    "query": "How do I create a React component?"
  }'
```

## Available Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `open_file` | view | Open file in VS Code at specific line |
| `create_file` | edit | Create new file with content |
| `edit_file` | edit | Replace text in file |
| `delete_file` | edit | Delete a file |
| `read_file` | view | Read file contents |
| `run_command` | commands | Execute shell command |
| `list_files` | view | List directory contents |
| `ask_copilot` | copilot | Open Copilot Chat with query |

## Web Interface Guide

### Dashboard
- Quick actions (Open, Run, Chat)
- Your permissions status
- Remote access URL (if Ngrok enabled)

### Tools
- Visual grid of all available tools
- Click any tool to execute
- See permission requirements

### File Browser
- Browse directories
- Click files to open/edit
- Full file path support

### Admin Panel (Superuser Only)
- View pending QR access requests
- See QR code to scan
- Approve/reject access requests
- Manage user permissions
- Grant capabilities to users

## Configuration

### .env File Reference

```env
# Server
HOST=0.0.0.0              # Bind address
PORT=8000                 # Port number

# Database
DATABASE_URL=sqlite:///./vs_code_controller.db

# JWT
SECRET_KEY=your-secret    # Change this!
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Ngrok
NGROK_ENABLED=false       # Enable/disable
NGROK_AUTH_TOKEN=         # Your token

# Superuser
SUPERUSER_PHONE=iPhone-12-XXX  # Your device ID
```

## Security Setup

### Important: Change Secret Key
Edit `.env`:
```env
SECRET_KEY=your-super-secret-key-here-change-this
```

### Optional: Authentication Middleware
Add to `app/main.py` for additional security:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000"],  # Restrict origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Rate Limiting (Future Enhancement)
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
```

## Development

### Run in Development Mode
```bash
python main.py
```

### Auto-reload with Uvicorn
```bash
uvicorn app.main:app --reload --port 8000
```

### Database Inspection
```bash
# View SQLite database
sqlite3 vs_code_controller.db

# View users
SELECT * FROM users;

# View permissions
SELECT * FROM user_permissions;

# View access requests
SELECT * FROM access_requests;
```

### Enable Debug Mode
```bash
DEBUG=true python main.py
```

## Mobile Client Examples

### iOS via Shortcuts
```
1. Create new Shortcut
2. HTTP POST to: https://your-url/api/tools/execute
3. Headers: {"Authorization": "Bearer TOKEN"}
4. Body: {"tool": "run_command", "command": "npm start"}
```

### Android via Tasker
```
1. Create Task
2. HTTP POST
3. URL: https://your-url/api/tools/execute
4. Headers: Authorization: Bearer TOKEN
5. Body: JSON with tool and parameters
```

### Python Script (from anywhere)
```python
import requests

TOKEN = "your_jwt_token_here"
BASE_URL = "https://your-public-url"  # From Ngrok

headers = {"Authorization": f"Bearer {TOKEN}"}

# Run command
response = requests.post(
    f"{BASE_URL}/api/tools/execute",
    json={
        "tool": "run_command",
        "command": "npm run build"
    },
    headers=headers
)

print(response.json())
```

## Troubleshooting

### Can't Connect to Server
```bash
# Check if server is running
curl http://localhost:8000/api/health

# Check firewall
# macOS: System Preferences > Security & Privacy > Firewall
# Windows: Windows Defender Firewall
```

### Device ID Issues
- Device ID must be unique per device
- Use: `iPhone-12-ABC123` or `Android-Samsung-S21` format
- First registration with SUPERUSER_PHONE device_id = Superuser
- Subsequent registrations = Regular user

### JWT Token Expired
- Tokens expire in 30 minutes (configurable in .env)
- Login again to get new token
- Browser automatically handles this

### VS Code Command Not Found
```bash
# Ensure code command is available
which code

# If missing, add VS Code to PATH:
# macOS: Command + Shift + P → "Shell Command: Install"
```

### Ngrok Issues
- Free plan has time limits and bandwidth
- Token may expire, Generate new token in dashboard
- Check auth token is correct in .env

## Advanced Topics

### Custom Tool Integration
Add new tools in `app/tools.py` VSCodeTools class:

```python
@staticmethod
def my_custom_tool(filepath: str, option: str):
    # Your implementation
    return f"✅ Custom tool executed"
```

### Database Backup
```bash
cp vs_code_controller.db vs_code_controller.db.backup
```

### Reset Database
```bash
# Delete database file (careful!)
rm vs_code_controller.db

# Restart server to recreate
python main.py
```

### Performance Optimization
For Ngrok tunnels, consider:
- Compression middleware
- Request/response caching
- Connection pooling

## Frequently Asked Questions

**Q: Can I limit file access to specific directories?**
A: Yes, modify `app/tools.py` to add path validation:
```python
ALLOWED_PATHS = ["/Users/username/Documents"]

@staticmethod
def validate_path(filepath):
    for allowed in ALLOWED_PATHS:
        if filepath.startswith(allowed):
            return True
    raise PermissionError("Path not allowed")
```

**Q: How secure is this?**
A: Very secure with proper setup:
- HTTPS via Ngrok
- JWT tokens with expiration
- Password hashing with bcrypt
- Permission-based access control
- SQLAlchemy ORM prevents SQL injection

**Q: Can I host this on a VPS instead of Ngrok?**
A: Yes! Set up SSL/TLS and deploy to any server:
```bash
# Using Gunicorn on VPS
gunicorn -w 4 -b 0.0.0.0:8000 app.main:app
```

**Q: What if I lose my superuser device ID?**
A: Create new superuser by:
1. Updating SUPERUSER_PHONE in .env
2. Delete and recreate database: `rm vs_code_controller.db`
3. Restart server and register again

## Contributing

Contributions welcome! Areas for improvement:
- [ ] SSO integration (Google, GitHub)
- [ ] Team/group permissions
- [ ] Audit logging
- [ ] WebSocket for real-time updates
- [ ] File sync/backup features
- [ ] Custom command templates

## License

MIT License - Feel free to use and modify

## Support

Issues or questions?
- Check troubleshooting section
- Review API documentation
- Check logs: `python main.py` output
- Ensure .env is configured correctly

## Project Structure Summary

**Backend (Python/FastAPI)**
- User authentication & JWT
- Permission management  
- Tool execution
- Database with SQLAlchemy
- Ngrok integration

**Frontend (HTML/CSS/JS)**
- Responsive mobile UI
- Real-time status updates
- Tool execution forms
- Admin panel
- QR code scanning

**Database (SQLite)**
- Users & authentication
- Permissions & access control
- Access requests & QR codes
- Secure password storage

**Tools (VS Code Integration)**
- File operations (CRUD)
- Command execution
- Copilot Chat integration
- Directory browsing

---

**Made with ❤️ for mobile developers everywhere**
