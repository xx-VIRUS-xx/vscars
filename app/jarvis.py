"""
JARVIS - Natural Language Command Interpreter for Mac
Converts natural language to shell commands without requiring API keys
"""

import subprocess
import os
import re
import logging
from typing import Tuple
from datetime import datetime
import json

# Setup logging to file
LOG_FILE = "/tmp/jarvis_execution.log"
log_handler = logging.FileHandler(LOG_FILE)
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger('JARVIS')
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)

class JARVISInterpreter:
    """
    Interprets natural language commands and executes them on Mac
    Can be upgraded with Claude API for better NLP
    """
    
    @staticmethod
    def interpret_command(user_query: str) -> Tuple[str, str]:
        """
        Convert natural language to shell command
        Returns: (shell_command, description)
        """
        query = user_query.lower().strip()
        
        # File operations
        if 'create file' in query or 'create a file' in query:
            match = re.search(r'(?:create|make).*file.*["\']?([^"\']+)["\']?\s*(?:with|containing|content)?\s*["\']?([^"\']*)["\']?', query)
            if match:
                filename = match.group(1).strip()
                content = match.group(2).strip() if match.group(2) else "# New file"
                cmd = f"echo '{content}' > '{filename}'"
                return cmd, f"Creating file: {filename}"
        
        if 'create directory' in query or 'create folder' in query or 'mkdir' in query:
            match = re.search(r'(?:create|make)\s+(?:directory|folder)\s+["\']?([^"\']+)["\']?', query)
            if match:
                dirname = match.group(1).strip()
                cmd = f"mkdir -p '{dirname}'"
                return cmd, f"Creating directory: {dirname}"
        
        if 'delete file' in query or 'remove file' in query:
            match = re.search(r'(?:delete|remove)\s+file\s+["\']?([^"\']+)["\']?', query)
            if match:
                filename = match.group(1).strip()
                cmd = f"rm '{filename}'"
                return cmd, f"Deleting file: {filename}"
        
        if 'list files' in query or 'show files' in query or 'ls' in query:
            match = re.search(r'(?:list|show)\s+(?:files|contents)\s+(?:in|of)?\s*["\']?([^"\']*)["\']?', query)
            path = match.group(1).strip() if match and match.group(1) else "."
            cmd = f"ls -lah '{path}'"
            return cmd, f"Listing files in: {path}"
        
        # Directory navigation
        if 'go to' in query or 'change directory' in query:
            match = re.search(r'(?:go to|cd|change.*to)\s+["\']?([^"\']+)["\']?', query)
            if match:
                path = match.group(1).strip()
                return f"cd '{path}' && pwd", f"Changing to directory: {path}"
        
        # Run commands
        if 'run' in query and 'command' in query:
            match = re.search(r'run\s+(?:command|cmd)?\s*["\']?([^"\']+)["\']?', query)
            if match:
                cmd = match.group(1).strip()
                return cmd, f"Running command: {cmd}"
        
        if 'install' in query:
            match = re.search(r'install\s+["\']?([^"\']+)["\']?', query)
            if match:
                package = match.group(1).strip()
                cmd = f"brew install {package}"
                return cmd, f"Installing: {package}"
        
        if 'python' in query or 'run python' in query:
            match = re.search(r'(?:run|execute)\s+python\s+["\']?([^"\']+)["\']?', query)
            if match:
                script = match.group(1).strip()
                cmd = f"python3 '{script}'"
                return cmd, f"Running Python script: {script}"
        
        if 'show' in query and 'file' in query:
            match = re.search(r'show\s+["\']?([^"\']+)["\']?', query)
            if match:
                filename = match.group(1).strip()
                cmd = f"cat '{filename}'"
                return cmd, f"Reading file: {filename}"
        
        # Disk info
        if 'disk space' in query or 'storage' in query:
            return "df -h", "Checking disk usage"
        
        if 'find file' in query:
            match = re.search(r'find\s+(?:file)?\s*["\']?([^"\']+)["\']?', query)
            if match:
                filename = match.group(1).strip()
                cmd = f"find ~ -name '{filename}' 2>/dev/null | head -20"
                return cmd, f"Searching for: {filename}"
        
        # System info
        if 'system info' in query or 'mac info' in query:
            return "system_profiler SPSoftwareDataType | head -10", "Showing system info"
        
        if 'memory' in query or 'ram' in query:
            return "vm_stat", "Checking memory usage"
        
        # Default: treat as direct shell command
        if any(cmd in query for cmd in ['ls', 'cd', 'cat', 'grep', 'find', 'echo', 'mkdir', 'rm', 'cp', 'mv']):
            return query, f"Executing: {query}"
        
        return None, f"❌ Could not interpret: '{user_query}'\n\nSupported commands:\n- create file [name] with [content]\n- create directory [name]\n- delete file [name]\n- list files in [path]\n- show file [name]\n- find file [name]\n- run command [cmd]\n- install [package]\n- system info\n\nOr type raw shell commands directly!"

    @staticmethod
    def execute_command(shell_cmd: str) -> str:
        """Execute shell command and return output"""
        try:
            # Block dangerous patterns
            import re as _re
            BLOCKED = [
                r'\brm\s+-rf\s+[/~]', r'\bmkfs\b', r'\bdd\s+if=',
                r':(){ :\|:& };:', r'\b>/dev/sd',
            ]
            for pattern in BLOCKED:
                if _re.search(pattern, shell_cmd):
                    return "❌ ERROR: Blocked dangerous command"
            
            result = subprocess.run(
                shell_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = result.stdout or result.stderr or "(Command completed with no output)"
            
            if result.returncode == 0:
                status = "✅ SUCCESS"
                log_msg = f"SUCCESS | Command: {shell_cmd} | Output Length: {len(output)} chars"
            else:
                status = f"⚠️ COMPLETED WITH STATUS {result.returncode}"
                log_msg = f"WARNING (Code {result.returncode}) | Command: {shell_cmd} | Output: {output[:200]}"
            
            logger.info(log_msg)
            return f"{status}:\n\n{output}"
        except subprocess.TimeoutExpired:
            error_msg = "TIMEOUT | Command exceeded 30 seconds"
            logger.error(f"{error_msg} | Command: {shell_cmd}")
            return "❌ ERROR: Command timed out (30 seconds)"
        except Exception as e:
            error_msg = f"ERROR | {str(e)}"
            logger.error(f"{error_msg} | Command: {shell_cmd}")
            return f"❌ ERROR: {str(e)}"
    
    @staticmethod
    def jarvis_query(user_query: str) -> str:
        """
        Main JARVIS interface
        Takes natural language, converts to command, executes, returns result
        """
        logger.info(f"NEW_QUERY | User Query: {user_query}")
        
        shell_cmd, description = JARVISInterpreter.interpret_command(user_query)
        
        if shell_cmd is None:
            logger.warning(f"INTERPRETATION_FAILED | Could not interpret: {user_query}")
            return description
        
        logger.info(f"INTERPRETED | Command: {shell_cmd} | Description: {description}")
        
        output = JARVISInterpreter.execute_command(shell_cmd)
        
        result = f"""🤖 JARVIS Command Execution

📝 Your Command: {user_query}

🔧 Interpreted as: {shell_cmd}

📊 Result:
{output}"""
        
        logger.info("=" * 80)
        return result
