#!/usr/bin/env python3
"""
VS Code Copilot Mobile Controller
A Python-based MCP server with web interface for controlling VS Code from mobile
"""

import os
import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.main import app
from app.config import HOST, PORT
import uvicorn

def main():
    """Main entry point"""
    
    print("\n" + "="*60)
    print("🎮 VS Code Copilot Mobile Controller")
    print("="*60)
    print(f"📍 Server: http://{HOST}:{PORT}")
    print(f"🌐 API: http://{HOST}:{PORT}/api")
    print(f"💻 Web UI: http://{HOST}:{PORT}")
    print("="*60 + "\n")
    
    # Start server
    print("🚀 Starting FastAPI server...")
    print("📱 Open your mobile browser and navigate to the server URL\n")
    
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info"
    )

if __name__ == "__main__":
    main()
