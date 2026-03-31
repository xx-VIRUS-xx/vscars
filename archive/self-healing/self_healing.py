"""
Self-Healing AI Development System
Automatically fixes bugs and implements features using Copilot Agent
"""

import os
import json
import subprocess
import time
import threading
from datetime import datetime
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.database import SelfHealingIssue, IssueNotificationQueue, SessionLocal
from app.tools import VSCodeTools
from app.config import WORKSPACE_PATH

class SelfHealingSystem:
    def __init__(self, db: Session):
        self.db = db
        self.workspace = WORKSPACE_PATH
        
    def report_issue(
        self,
        issue_type: str,  # 'bug' or 'feature_request'
        title: str,
        description: str,
        user_id: int,
        affected_file: Optional[str] = None,
        error_message: Optional[str] = None,
        priority: str = "medium"
    ) -> SelfHealingIssue:
        """Report a bug or feature request and start auto-fix"""
        
        # Create issue record
        issue = SelfHealingIssue(
            issue_type=issue_type,
            title=title,
            description=description,
            affected_file=affected_file,
            error_message=error_message,
            requested_by=user_id,
            priority=priority,
            status="reported"
        )
        
        self.db.add(issue)
        self.db.commit()
        self.db.refresh(issue)
        
        issue_id = issue.id  # Store ID before thread starts
        
        # Queue notification
        self._queue_notification(
            issue_id=issue_id,
            user_id=user_id,
            event_type="reported",
            message=f"🐛 {title} has been reported and AI assistant is analyzing..."
        )
        
        # Start auto-fix in background thread (non-blocking)
        fix_thread = threading.Thread(
            target=self._start_auto_fix_async,
            args=(issue_id, user_id),
            daemon=True
        )
        fix_thread.start()
        
        return issue
    
    def _start_auto_fix_async(self, issue_id: int, user_id: int):
        """Async fix runner - runs in background thread with fresh DB session"""
        db = SessionLocal()  # Fresh session for this thread
        try:
            issue = db.query(SelfHealingIssue).filter(
                SelfHealingIssue.id == issue_id
            ).first()
            
            if not issue:
                return
            
            # Update status
            issue.status = "in-progress"
            issue.in_progress_at = datetime.utcnow()
            db.commit()
            
            # Queue notification
            self._queue_notification_async(
                db, issue_id, user_id, "in_progress",
                f"🤖 Copilot Agent is analyzing and fixing '{issue.title}'..."
            )
            
            # Build Copilot prompt
            if issue.issue_type == "bug":
                copilot_prompt = self._build_bug_fix_prompt(issue)
            else:
                copilot_prompt = self._build_feature_prompt(issue)
            
            # Invoke Copilot Agent in agentic mode (can edit files, run commands)
            print(f"[SELF-HEALING] Starting Copilot Agent for issue #{issue_id}...")
            copilot_output = VSCodeTools.copilot_agent(
                prompt=copilot_prompt,
                project_path=self.workspace,
                model="claude-haiku-4.5",
                allow_tools="all"  # Allow all operations for auto-fixing
            )
            
            print(f"[SELF-HEALING] Copilot output: {copilot_output[:200]}...")
            
            issue.copilot_response = copilot_output
            issue.status = "fixing"
            db.commit()
            
            # Parse modified files from response
            modified_files = self._parse_modified_files(copilot_output)
            if modified_files:
                issue.files_modified = json.dumps(modified_files)
                db.commit()
            
            # Try to commit the changes
            commit_hash = self._git_commit_fixes(issue)
            if commit_hash:
                issue.git_commit_hash = commit_hash
                db.commit()
            
            # Queue testing notification
            self._queue_notification_async(
                db, issue_id, user_id, "fix_found",
                f"✅ Fix complete! Testing solution for '{issue.title}'..."
            )
            
            # Test if server still works
            issue.status = "testing"
            db.commit()
            
            if self._test_server_health():
                # Restart server and get ngrok URL
                self._restart_server_and_redeploy(issue, db)
                
                issue.status = "completed"
                issue.completed_at = datetime.utcnow()
                db.commit()
                
                # Generate final notification with ngrok URL
                ngrok_url = self._get_ngrok_url()
                self._queue_notification_async(
                    db, issue_id, user_id, "completed",
                    f"🚀 '{issue.title}' is DEPLOYED! Website is live!",
                    ngrok_url=ngrok_url
                )
                
                print(f"[SELF-HEALING] Issue #{issue_id} COMPLETED with URL: {ngrok_url}")
            else:
                issue.status = "failed"
                db.commit()
                
                self._queue_notification_async(
                    db, issue_id, user_id, "error",
                    f"❌ Server health check failed for fix. Manual review needed."
                )
                print(f"[SELF-HEALING] Issue #{issue_id} failed - server unhealthy")
        
        except Exception as e:
            print(f"[SELF-HEALING] Error in auto-fix: {str(e)}")
            issue = db.query(SelfHealingIssue).filter(
                SelfHealingIssue.id == issue_id
            ).first()
            if issue:
                issue.status = "failed"
                issue.copilot_response = f"Error: {str(e)}"
                db.commit()
            
            self._queue_notification_async(
                db, issue_id, user_id, "error",
                f"❌ Auto-fix failed: {str(e)}"
            )
        finally:
            db.close()
    
    def _start_auto_fix(self, issue: SelfHealingIssue):
        """(Deprecated) Use _start_auto_fix_async instead"""
        pass
    
    def _build_bug_fix_prompt(self, issue: SelfHealingIssue) -> str:
        """Build the prompt for bug fixing"""
        prompt = f"""
You are an expert code fixing agent. Fix the following bug in the project at {self.workspace}

BUG TITLE: {issue.title}
DESCRIPTION: {issue.description}
"""
        if issue.affected_file:
            prompt += f"AFFECTED FILE: {issue.affected_file}\n"
        if issue.error_message:
            prompt += f"ERROR MESSAGE:\n{issue.error_message}\n"
        if issue.reproduction_steps:
            prompt += f"REPRODUCTION STEPS:\n{issue.reproduction_steps}\n"
        
        prompt += """
INSTRUCTIONS:
1. Examine the code and understand the issue
2. Identify the root cause
3. Make the necessary changes to fix the bug
4. Run relevant commands to verify the fix works
5. Make sure your changes don't break other parts

Be efficient and thorough. Only modify what's necessary.
"""
        return prompt
    
    def _build_feature_prompt(self, issue: SelfHealingIssue) -> str:
        """Build the prompt for feature implementation"""
        prompt = f"""
You are an expert code implementation agent. Implement the following feature in the project at {self.workspace}

FEATURE NAME: {issue.title}
DESCRIPTION: {issue.description}

INSTRUCTIONS:
1. Review the project structure and understand the codebase
2. Implement the feature in a clean, maintainable way
3. Add any necessary configuration or environment variables
4. Test the implementation if possible
5. Update relevant documentation

Be efficient and follow the project's coding conventions.
"""
        return prompt
    
    def _parse_modified_files(self, response: str) -> List[str]:
        """Extract list of modified files from Copilot response"""
        # This is a simple implementation - can be enhanced
        try:
            # Look for file paths in the output
            files = []
            for line in response.split("\n"):
                if "modified:" in line.lower() or "created:" in line.lower():
                    # Extract file path
                    parts = line.split(":")
                    if len(parts) > 1:
                        filepath = parts[-1].strip()
                        files.append(filepath)
            return files
        except:
            return []
    
    def _git_commit_fixes(self, issue: SelfHealingIssue) -> Optional[str]:
        """Commit the fixes to git"""
        try:
            os.chdir(self.workspace)
            
            # Add all changes
            subprocess.run(["git", "add", "-A"], capture_output=True, timeout=30)
            
            # Create commit message
            commit_msg = f"🤖 Auto-fix: {issue.title}\n\nFiltered by Copilot Agent\nIssue: {issue.description}"
            
            result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                # Get commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                return hash_result.stdout.strip()
            
            return None
        except Exception as e:
            print(f"Git commit failed: {e}")
            return None
    
    def _test_server_health(self) -> bool:
        """Test if the server is healthy"""
        try:
            import requests
            response = requests.get("http://localhost:8000/api/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def _restart_server_and_redeploy(self, issue: SelfHealingIssue, db: Session = None):
        """Record deployment info without killing the running server.
        
        Note: We intentionally do NOT kill/restart the server here because
        this code runs INSIDE the server process. Killing it would terminate
        the self-healing pipeline itself. The server will pick up code changes
        on next restart (manual or via uvicorn --reload).
        """
        if db is None:
            db = self.db
        
        try:
            issue.server_restart_time = datetime.utcnow()
            issue.ngrok_url = self._get_ngrok_url()
            db.commit()
            
            print(f"[SELF-HEALING] Deployment recorded for issue #{issue.id}. "
                  f"Server restart skipped (self-preservation). "
                  f"Restart manually or use --reload for changes to take effect.")
            
        except Exception as e:
            print(f"Deployment recording failed: {e}")
    
    def _get_ngrok_url(self) -> Optional[str]:
        """Get current ngrok public URL (tries both default and alternate ports)"""
        import requests
        for port in [4040, 4041]:
            try:
                response = requests.get(f"http://127.0.0.1:{port}/api/tunnels", timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("tunnels"):
                        for tunnel in data["tunnels"]:
                            if "https" in tunnel.get("public_url", ""):
                                return tunnel["public_url"]
            except:
                continue
        return None
    
    def _queue_notification(
        self,
        issue_id: int,
        user_id: int,
        event_type: str,
        message: str,
        ngrok_url: Optional[str] = None
    ):
        """Queue a notification for the user"""
        notification = IssueNotificationQueue(
            issue_id=issue_id,
            user_id=user_id,
            event_type=event_type,
            message=message,
            ngrok_url=ngrok_url or self._get_ngrok_url()
        )
        self.db.add(notification)
        self.db.commit()
    
    def _queue_notification_async(
        self,
        db: Session,
        issue_id: int,
        user_id: int,
        event_type: str,
        message: str,
        ngrok_url: Optional[str] = None
    ):
        """Queue a notification for the user (async version with provided db session)"""
        notification = IssueNotificationQueue(
            issue_id=issue_id,
            user_id=user_id,
            event_type=event_type,
            message=message,
            ngrok_url=ngrok_url or self._get_ngrok_url()
        )
        db.add(notification)
        db.commit()
    
    def get_issue_stream(self, user_id: int):
        """Get stream of notifications for user (for SSE)"""
        notifications = self.db.query(IssueNotificationQueue).filter(
            IssueNotificationQueue.user_id == user_id,
            IssueNotificationQueue.was_delivered == False
        ).order_by(IssueNotificationQueue.created_at.desc()).all()
        
        for notification in notifications:
            notification.was_delivered = True
            notification.delivered_at = datetime.utcnow()
        
        self.db.commit()
        return notifications
    
    def get_issue_status(self, issue_id: int) -> Optional[Dict]:
        """Get current status of an issue"""
        issue = self.db.query(SelfHealingIssue).filter(
            SelfHealingIssue.id == issue_id
        ).first()
        
        if not issue:
            return None
        
        return {
            "id": issue.id,
            "title": issue.title,
            "status": issue.status,
            "priority": issue.priority,
            "copilot_response": issue.copilot_response,
            "files_modified": json.loads(issue.files_modified) if issue.files_modified else [],
            "git_commit_hash": issue.git_commit_hash,
            "ngrok_url": issue.ngrok_url,
            "created_at": issue.created_at.isoformat() if issue.created_at else None,
            "completed_at": issue.completed_at.isoformat() if issue.completed_at else None
        }
    
    def get_recent_issues(self, limit: int = 10) -> List[Dict]:
        """Get recent issues"""
        issues = self.db.query(SelfHealingIssue).order_by(
            SelfHealingIssue.created_at.desc()
        ).limit(limit).all()
        
        return [self.get_issue_status(issue.id) for issue in issues]
