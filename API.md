# 📡 API Reference

Complete REST API documentation for JARVIS.

**Base URL:** `http://localhost:8000/api`  
**Authentication:** JWT Bearer token in `Authorization` header

---

## Authentication

### Login
**Endpoint:** `POST /api/auth/login`

Get JWT token for API requests.

**Request:**
```json
{
  "username": "superbot",
  "password": "test123",
  "device_id": "iPhone-16-Pro"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Status Codes:**
- `200` - Success
- `401` - Invalid credentials
- `400` - Missing required fields

---

### Register
**Endpoint:** `POST /api/auth/register`

Create new user account.

**Request:**
```json
{
  "username": "newuser",
  "email": "user@example.com",
  "password": "securepass123",
  "device_id": "Android-Phone"
}
```

**Response:**
```json
{
  "id": 2,
  "username": "newuser",
  "email": "user@example.com",
  "is_superuser": false,
  "created_at": "2026-03-16T10:30:00"
}
```

**Status Codes:**
- `201` - Account created
- `400` - User already exists / Invalid data

---

### Get Current User
**Endpoint:** `GET /api/auth/me`

**Headers:**
```
Authorization: Bearer YOUR_JWT_TOKEN
```

**Response:**
```json
{
  "id": 1,
  "username": "superbot",
  "email": "bot@example.com",
  "is_superuser": true,
  "device_id": "iPhone-16-Pro",
  "created_at": "2026-03-14T09:00:00"
}
```

---

## Tools

### List Available Tools
**Endpoint:** `GET /api/tools`

**Headers:**
```
Authorization: Bearer YOUR_JWT_TOKEN
```

**Response:**
```json
{
  "tools": [
    {
      "name": "read_file",
      "description": "Read file contents",
      "permission_required": "view"
    },
    {
      "name": "copilot_agent",
      "description": "Run Copilot in agentic mode",
      "permission_required": "copilot"
    }
    // ... more tools
  ]
}
```

---

### Execute Tool
**Endpoint:** `POST /api/tools/execute`

**Headers:**
```
Authorization: Bearer YOUR_JWT_TOKEN
Content-Type: application/json
```

**Request:**
```json
{
  "tool": "read_file",
  "filepath": "/Users/xxvirusxx/Projects/file.py"
}
```

**Response:**
```json
{
  "success": true,
  "tool": "read_file",
  "result": "✅ File: /Users/xxvirusxx/Projects/file.py\n📊 Lines: 42\n\n... file content ...",
  "error": null
}
```

---

## Tool Parameters Reference

### file Operations

#### read_file
```json
{
  "tool": "read_file",
  "filepath": "/path/to/file.py"
}
```

#### create_file
```json
{
  "tool": "create_file",
  "filepath": "/path/to/newfile.py",
  "content": "print('hello')"
}
```

#### edit_file
```json
{
  "tool": "edit_file",
  "filepath": "/path/to/file.py",
  "old_text": "old code",
  "new_text": "new code"
}
```

#### delete_file
```json
{
  "tool": "delete_file",
  "filepath": "/path/to/file.py"
}
```

#### open_file
```json
{
  "tool": "open_file",
  "filepath": "/path/to/file.py",
  "line": 42
}
```

#### list_files
```json
{
  "tool": "list_files",
  "dirpath": "/path/to/directory"
}
```

#### browse_directory
```json
{
  "tool": "browse_directory",
  "dirpath": "/path/to/directory",
  "depth": 3,
  "show_hidden": false
}
```

---

### Copilot Tools

#### copilot_agent (⭐ Most Powerful)
Run Copilot in autonomous mode to edit files, run commands, build features.

```json
{
  "tool": "copilot_agent",
  "prompt": "Create a Python REST API for managing todos using FastAPI",
  "project_path": "/Users/xxvirusxx/Projects/my-api",
  "model": "claude-haiku-4.5",
  "allow_tools": "all"
}
```

**Parameters:**
- `prompt` (req) - What Copilot should do
- `project_path` (opt) - Project directory (uses workspace default if blank)
- `model` (opt) - AI model (default: claude-haiku-4.5)
  - Valid: claude-opus-4.6, claude-sonnet-4.6, gpt-5.2, gpt-5.1, gpt-4.1, etc.
- `allow_tools` (opt) - Permission level: "all" | "read" | "edit" (default: "all")

**Response Example:**
```json
{
  "success": true,
  "tool": "copilot_agent",
  "result": "🤖 COPILOT AGENT RESPONSE\n📁 Project: /Users/xxvirusxx/Projects/my-api\n🧠 Model: claude-haiku-4.5\n🔧 Permissions: all\n\nI'll help you create a FastAPI REST API for managing todos...(execution details)",
  "error": null
}
```

#### ask_copilot
Chat with Copilot using GitHub Models API.

```json
{
  "tool": "ask_copilot",
  "query": "How do I implement pagination in FastAPI?"
}
```

**Response:**
```json
{
  "success": true,
  "tool": "ask_copilot",
  "result": "🤖 COPILOT RESPONSE\n\nPagination in FastAPI can be implemented...",
  "error": null
}
```

---

### Command Execution

#### run_command
```json
{
  "tool": "run_command",
  "command": "npm install",
  "cwd": "/path/to/project"
}
```

#### git_status
```json
{
  "tool": "git_status",
  "repo_path": "/path/to/repo"
}
```

#### git_command
```json
{
  "tool": "git_command",
  "command": "commit -m 'initial commit'",
  "repo_path": "/path/to/repo"
}
```

#### open_terminal
```json
{
  "tool": "open_terminal",
  "cwd": "/path/to/directory"
}
```

---

### Project Management

#### create_project
```json
{
  "tool": "create_project",
  "project_name": "my-new-api",
  "project_type": "fastapi",
  "parent_dir": "/Users/xxvirusxx/Projects",
  "copilot_prompt": "Create a production-ready FastAPI REST API with authentication, database models, and tests"
}
```

**Project Types:**
- python, node, react, flask, fastapi, django, etc.

---

### System Info

#### get_workspace_info
```json
{
  "tool": "get_workspace_info"
}
```

**Response:**
```json
{
  "success": true,
  "result": "📁 Workspace: /Users/xxvirusxx/Projects\n🖥️ System: Darwin (arm64)\n🐍 Python: 3.11.0\n💻 VS Code: 1.87.0\n📦 Git: git version 2.40.0\n🟢 Node: v18.17.0\n🤖 Copilot CLI: 1.0.5\n🐙 GitHub CLI: 2.30.0\n💾 Disk: 500GB free of 1TB\n⏱️ Timeout: 120s"
}
```

---

## Permissions

### Get User Permissions
**Endpoint:** `GET /api/permissions/{user_id}`

**Response:**
```json
{
  "user_id": 1,
  "can_view_files": true,
  "can_edit_files": true,
  "can_run_commands": true,
  "can_run_copilot": true
}
```

---

## Admin Operations

### Pending Access Requests
**Endpoint:** `GET /api/admin/pending-requests`

**Response:**
```json
{
  "requests": [
    {
      "id": 1,
      "user_id": 2,
      "username": "newuser",
      "status": "pending",
      "requested_at": "2026-03-16T10:00:00"
    }
  ]
}
```

---

### Approve Access Request
**Endpoint:** `POST /api/admin/approve-request`

```json
{
  "request_id": 1,
  "approve": true
}
```

---

### Grant Permission
**Endpoint:** `POST /api/admin/grant-permission`

```json
{
  "user_id": 2,
  "permission": "edit_files",
  "grant": true
}
```

---

## History & Logs

### Get Activity Log
**Endpoint:** `GET /api/history/activity`

**Response:**
```json
{
  "activities": [
    {
      "id": 1,
      "user_id": 1,
      "action": "Executed read_file",
      "timestamp": "2026-03-16T10:30:00",
      "tool_name": "read_file",
      "status": "success"
    }
  ]
}
```

---

### Get Conversation History
**Endpoint:** `GET /api/history/conversations`

**Response:**
```json
{
  "conversations": [
    {
      "id": 1,
      "user_id": 1,
      "query": "How do I deploy FastAPI?",
      "response": "FastAPI can be deployed to...",
      "tool_used": "ask_copilot",
      "timestamp": "2026-03-16T10:30:00"
    }
  ]
}
```

---

## Error Handling

### Error Response Format
```json
{
  "success": false,
  "tool": "tool_name",
  "result": "❌ Error description",
  "error": "detailed error message"
}
```

### Common Status Codes
- `200` - Success
- `201` - Created
- `400` - Bad request (invalid params)
- `401` - Unauthorized (invalid/missing token)
- `403` - Forbidden (permission denied)
- `404` - Not found (tool/user not found)
- `500` - Server error

---

## Rate Limiting

Currently no built-in rate limiting. Recommended for production:
- Implement per-user request limits
- Add timeout protection for long-running tools
- Cache frequent requests

---

## Authentication Example

```bash
# 1. Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superbot",
    "password": "test123",
    "device_id": "iPhone-16-Pro"
  }' | jq -r '.access_token')

# 2. Use token in requests
curl -X POST http://localhost:8000/api/tools/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "read_file",
    "filepath": "/path/to/file.py"
  }'
```

---

## SDK Integration

### Python requests
```python
import requests

token = "your_jwt_token"
headers = {"Authorization": f"Bearer {token}"}

response = requests.post(
    "http://localhost:8000/api/tools/execute",
    headers=headers,
    json={
        "tool": "copilot_agent",
        "prompt": "Create a Python script",
        "model": "claude-haiku-4.5"
    }
)

print(response.json())
```

### JavaScript fetch
```javascript
const token = "your_jwt_token";

const response = await fetch("http://localhost:8000/api/tools/execute", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    tool: "copilot_agent",
    prompt: "Create a React component",
    model: "claude-haiku-4.5"
  })
});

const result = await response.json();
console.log(result);
```

---

## Websocket Support

Not yet implemented. Planned for future releases for real-time:
- Status updates
- Direct terminal output streaming
- Live log updates
- Notification delivery

---

**API Version:** v1  
**Last Updated:** March 16, 2026
