# ⚡ Quick Start Guide - VS Code Copilot Mobile Controller

## 🎯 5 Minute Setup

### Step 1: Install Dependencies (2 min)
```bash
cd "LLM redefined"
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Superuser Device (1 min)
```bash
# Edit .env
nano .env

# Change this line to your phone's device ID:
SUPERUSER_PHONE=iPhone-12-XXX  # Your actual device ID
```

### Step 3: Start Server (1 min)
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

### Step 4: Access from Mobile (1 min)
On your phone, open browser:
- **Same Network**: `http://<your-pc-ip>:8000`
- **Find IP**: Run this on PC
  ```bash
  # macOS/Linux
  ifconfig | grep "inet " | grep -v 127.0.0.1
  
  # Windows
  ipconfig
  ```

## 📱 First Time Setup

### Register as Superuser
1. Open web interface on your phone
2. Click **"Register"** tab
3. Enter:
   - Username: `admin`
   - Email: `your.email@example.com`
   - Password: `secure123`
   - Device ID: **EXACTLY** same as `SUPERUSER_PHONE` from .env
4. Click "Create Account"
5. ✅ You're now superuser with ALL permissions!

### Test It Works
1. Go to Dashboard
2. Click "Quick Actions" → "Run Command"
3. Enter: `echo "Hello from mobile!"`
4. Click Execute
5. ✅ Should see output!

## 🔐 Set Up Remote Access (Optional)

### Get Ngrok
1. Sign up free at [ngrok.com](https://ngrok.com)
2. Get your auth token from dashboard
3. Update `.env`:
   ```env
   NGROK_ENABLED=true
   NGROK_AUTH_TOKEN=your_token_here
   ```
4. Restart server
5. See public URL on Dashboard!

Now you can access from ANYWHERE in the world! 🌍

## 🛠️ Tools Available

| Tool | What it does |
|------|------------|
| **Open File** | Tap to open any file in your PC's VS Code |
| **Create File** | New files with content from phone |
| **Edit File** | Modify existing files |
| **Run Command** | Execute npm, git, python, anything! |
| **List Files** | Browse your PC's directories |
| **Ask Copilot** | Chat with Copilot from phone |

## 👥 User Management

### Add Another User
1. Have them register from their phone
2. Use different Device ID
3. They'll be "Regular User" (limited permissions)
4. You (superuser) can grant permissions in Admin Panel:
   - ✓ Run Commands
   - ✓ Edit Files
   - ✓ Ask Copilot

### Grant Permissions
1. Go to Admin Panel
2. Find user
3. Toggle permissions
4. ✅ Done!

## 🔒 QR Code Authentication

### Alternative: Let Users Request Access
1. New users → "QR Access" tab
2. Enter name, email, device ID
3. System generates QR code
4. You scan with PC (screenshot works!)
5. QR code appears in Admin Panel
6. You approve or reject
7. User gets instant access!

## 📊 Dashboard Overview

- **Quick Actions** - Run common tasks
- **My Permissions** - See what you can do
- **Remote Access** - Share public URL (if Ngrok enabled)

## ⚙️ Admin Panel (Superuser Only)

See:
- Pending access requests
- QR codes to scan
- All registered users
- User permissions

## 🚨 Troubleshooting

### "Can't connect to server"
```bash
# Check if server is running
curl http://localhost:8000/api/health

# If not, make sure:
# 1. You're in the project directory
# 2. You activated venv: source venv/bin/activate
# 3. You ran: python main.py
```

### "Authorization failed" on login
- Check username/password
- Verify device ID exactly matches what you set in .env (for superuser)
- For other users: Any device ID works, admins approve later

### "Command not found" error
- Check file/command paths are absolute
- Bad example: `npm build` (relative)
- Good example: `/Users/username/project && npm build` (absolute)

### "Can't access from phone on WiFi"
```bash
# Get your PC's IP
ifconfig | grep "inet " | grep -v 127.0.0.1

# Use that in phone browser:
http://192.168.1.100:8000  # Or your IP
```

## 🔑 Device IDs

Examples:
- `iPhone-12-Pro`
- `iPad-Air-2024`
- `Samsung-S24-Ultra`
- `Pixel-9-Pro`

**Important**: Each device needs unique ID for user tracking!

## 📝 Common Tasks

### Run npm build from phone
1. Go to Tools → run_command
2. Enter command: `cd /path/to/project && npm run build`
3. Click Execute
4. Watch output in real-time!

### Edit code from phone
1. Go to Tools → edit_file
2. filepath: `/Users/user/project/app.ts`
3. oldText: `color: red`
4. newText: `color: blue`
5. Done instantly!

### Ask Copilot while coding
1. Go to Tools → ask_copilot
2. Query: `How do I use useEffect in React?`
3. Copilot opens on your PC with answer!

## 🌐 Remote Access Setup

### Option 1: Ngrok (Easiest)
- Free tier gives you public URL
- URL changes on restart
- Perfect for temporary remote access

### Option 2: Custom Domain
- Point domain to your PC's IP
- Requires port forwarding (advanced)
- Persistent URL

### Option 3: VPN
- Most secure
- Can access home network remotely
- Requires VPN setup on PC

## 💾 Backup Your Data

```bash
# Database with all users/permissions
cp vs_code_controller.db ~/backup.db

# Or backup entire project
tar -czf ../backup.tar.gz .
```

## 🔄 Reset Everything

```bash
# Delete all users and start over
rm vs_code_controller.db

# Restart server
python main.py
```

## ✅ You're All Set!

You can now:
- ✅ Control VS Code from phone
- ✅ Run commands remotely
- ✅ Chat with Copilot
- ✅ Manage teams with permissions
- ✅ Access worldwide with Ngrok

Enjoy! 🚀

---

Need help? Check [README.md](README.md) for full documentation.
