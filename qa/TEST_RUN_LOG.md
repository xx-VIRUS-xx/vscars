# VSCARS Test Run Log

## Run 2026-03-31 21:06:03 UTC

Summary: **12 passed**, **0 failed**, total **12**

### WEB-001 - Landing page is reachable [PASS]

Expected:
`200 and page contains VSCARS`

Input:
```json
{
  "method": "GET",
  "path": "/"
}
```

Output:
```json
{
  "status_code": 200,
  "contains": "VSCARS"
}
```

### WEB-002 - Setup page is reachable [PASS]

Expected:
`200 and setup page loads`

Input:
```json
{
  "method": "GET",
  "path": "/setup"
}
```

Output:
```json
{
  "status_code": 200,
  "contains": "Setup"
}
```

### WEB-003 - Connector install script is reachable [PASS]

Expected:
`200 and shell script shebang present`

Input:
```json
{
  "method": "GET",
  "path": "/static/install-connector.sh"
}
```

Output:
```json
{
  "status_code": 200,
  "first_line": "#!/usr/bin/env bash"
}
```

### AUTH-001 - First user register (superuser bootstrap) [PASS]

Expected:
`200`

Input:
```json
{
  "path": "/api/auth/register",
  "username": "qa_admin"
}
```

Output:
```json
{
  "status_code": 200,
  "body": {
    "access_token": "eyJhbG...ALyk",
    "token_type": "***",
    "user": {
      "id": 1,
      "username": "qa_admin",
      "email": "qa_admin@test.local",
      "is_superuser": true
    }
  }
}
```

### AUTH-002 - Second user register (free plan) [PASS]

Expected:
`200`

Input:
```json
{
  "path": "/api/auth/register",
  "username": "qa_user"
}
```

Output:
```json
{
  "status_code": 200,
  "body": {
    "access_token": "eyJhbG...5zVs",
    "token_type": "***",
    "user": {
      "id": 2,
      "username": "qa_user",
      "email": "qa_user@test.local",
      "is_superuser": false
    }
  }
}
```

### BILL-001 - Free plan status and limit [PASS]

Expected:
`plan=free and daily_limit=50`

Input:
```json
{
  "method": "GET",
  "path": "/api/billing/status"
}
```

Output:
```json
{
  "status_code": 200,
  "plan": "free",
  "daily_limit": 50
}
```

### BILL-002 - Free user blocked from API key generation [PASS]

Expected:
`403`

Input:
```json
{
  "method": "POST",
  "path": "/api/auth/api-key/generate"
}
```

Output:
```json
{
  "status_code": 403,
  "body": {
    "detail": {
      "message": "CLI API keys require a Pro plan or above.",
      "code": "plan_required",
      "upgrade_url": "/billing"
    }
  }
}
```

### MACH-001 - Free user blocked from machine registration [PASS]

Expected:
`403`

Input:
```json
{
  "method": "POST",
  "path": "/api/machines/register",
  "json": {
    "machine_id": "qa-machine-1"
  }
}
```

Output:
```json
{
  "status_code": 403,
  "body": {
    "detail": {
      "message": "Machine registration requires a Pro plan or above.",
      "code": "plan_required",
      "upgrade_url": "https://vscars.latenightstack.com/#pricing"
    }
  }
}
```

### BILL-003 - Pro user can generate API key [PASS]

Expected:
`200 with api_key`

Input:
```json
{
  "method": "POST",
  "path": "/api/auth/api-key/generate"
}
```

Output:
```json
{
  "status_code": 200,
  "api_key_prefix": "vscars...s..."
}
```

### MACH-002 - Pro user machine registration via API key [PASS]

Expected:
`200 with machine token`

Input:
```json
{
  "method": "POST",
  "path": "/api/machines/register",
  "headers": {
    "X-VSCARS-Key": "***"
  },
  "json": {
    "machine_id": "qa-machine-pro-1",
    "name": "QA MacBook"
  }
}
```

Output:
```json
{
  "status_code": 200,
  "body": {
    "machine_id": "qa-machine-pro-1",
    "token": "zwdl9-...LcUY",
    "name": "QA MacBook"
  }
}
```

### TRUST-001 - Sensitive command requires approval [PASS]

Expected:
`200 with approval_required=true`

Input:
```json
{
  "method": "POST",
  "path": "/api/tools/execute",
  "json": {
    "tool": "run_command",
    "command": "echo hello"
  }
}
```

Output:
```json
{
  "status_code": 200,
  "body": {
    "success": false,
    "tool": "run_command",
    "result": null,
    "error": "Approval required before execution. Request #1 is pending.",
    "approval_required": true,
    "approval_id": 1
  }
}
```

### MACH-003 - After approval, command blocked until agent starts [PASS]

Expected:
`retry returns 503 code=no_machine and setup_url/install_cmd`

Input:
```json
{
  "approve": {
    "method": "POST",
    "path": "/api/trust/approvals/1/approve"
  },
  "retry": {
    "method": "POST",
    "path": "/api/tools/execute",
    "json": {
      "tool": "run_command",
      "command": "echo hello"
    }
  }
}
```

Output:
```json
{
  "approve_status": 200,
  "retry_status": 503,
  "retry_detail": {
    "message": "No machine connected. Install the vscars CLI on your laptop and run `vscars start` to connect it.",
    "code": "no_machine",
    "install_cmd": "curl -fsSL https://qa.vscars.local/static/install-connector.sh | bash && vscars init",
    "setup_url": "https://qa.vscars.local/setup"
  }
}
```


## 2026-04-01T04:26:24.791118+00:00
- ask_agent copilot -> http=200 success=False out=
- ask_agent claude -> http=200 success=False out=
- ask_agent codex -> http=200 success=False out=

## 2026-04-01T04:27:20.978608+00:00
- ask_agent copilot input=Reply exactly: API_OK_COPILOT -> http=200 success=False error=None output=❌ Error: VSCodeTools.ask_agent() got an unexpected keyword argument 'params'
- ask_agent claude input=Reply exactly: API_OK_CLAUDE -> http=200 success=False error=None output=❌ Error: VSCodeTools.ask_agent() got an unexpected keyword argument 'params'
- ask_agent codex input=Reply exactly: API_OK_CODEX -> http=200 success=False error=None output=❌ Error: VSCodeTools.ask_agent() got an unexpected keyword argument 'params'

## 2026-04-01T04:27:47.112603+00:00
- ask_agent copilot input=Reply exactly: API_OK_COPILOT -> http=200 success=True error=None output=🧭 Agent: Copilot Agent
🎯 Requested Model: gpt-5.2

🤖 COPILOT AGENT RESPONSE
📁 Project: /var/folders/
- ask_agent claude input=Reply exactly: API_OK_CLAUDE -> http=200 success=True error=None output=🧭 Agent: Claude Code
🎯 Requested Model: claude-sonnet-4.6

🤖 COPILOT AGENT RESPONSE
📁 Project: /var/
- ask_agent codex input=Reply exactly: API_OK_CODEX -> http=200 success=True error=None output=🧭 Agent: Codex
🎯 Requested Model: gpt-5.3-codex

🤖 COPILOT AGENT RESPONSE
📁 Project: /var/folders/ys

## 2026-04-01T17:09:41.717128+00:00
- run_command_http input={'tool': 'run_command', 'command': 'echo TERM_HTTP_OK'} output={'http': 200, 'success': True, 'output_head': '✅ SUCCESS\n📁 CWD: /Users/xxvirusxx\n\nTERM_HTTP_OK\n'}
- ask_agent_async_queue input={'tool': 'ask_agent', 'prompt': 'Reply exactly: ASYNC_OK', 'agent': 'codex', 'model': 'gpt-5.3-codex', 'allow_tools': 'all'} output={'http': 200, 'success': True, 'status': 'queued', 'task_id': 1, 'crawler_url': 'http://localhost:8000/api/agent/tasks/1', 'output_head': '⏳ Task queued: #1\nTrack progress: http://localhost:8000/api/agent/tasks/1\nYou will get a notification when the task finishes.'}
- ask_agent_async_complete input={'task_id': 1} output={'status': None, 'result_head': ''}
- agent_notifications input={} output={'http': 200, 'count': 0, 'head': {}}

## 2026-04-01T17:15:59.792383+00:00
- run_command_http input={'tool': 'run_command', 'command': 'echo TERM_HTTP_OK'} output={'success': True, 'result_head': '✅ SUCCESS\n📁 CWD: /Users/xxvirusxx\n\nTERM_HTTP_OK\n'}
- ask_agent_async_queue input={'tool': 'ask_agent', 'prompt': 'Reply exactly: THREAD_ASYNC_OK', 'agent': 'codex', 'model': 'gpt-5.3-codex', 'allow_tools': 'all'} output={'success': True, 'status': 'queued', 'task_id': 3, 'crawler_url': 'http://localhost:8000/api/agent/tasks/3', 'result_head': '⏳ Task queued: #3\nTrack progress: http://localhost:8000/api/agent/tasks/3\nYou will get a notification when the task finishes.'}
- ask_agent_async_complete input={'task_id': 3} output={'status': 'completed', 'result_head': '🧭 Agent: Codex\n🎯 Requested Model: gpt-5.3-codex\n\n🤖 COPILOT AGENT RESPONSE\n📁 Project: /Users/xxvirusxx\n🧠 Model: gpt-5.3-codex\n🔧 Permissions: all\n\nTHREAD_ASYNC_OK'}
- agent_notifications input={} output={'count': 1, 'first': {'task_id': 3, 'tool': 'ask_agent', 'status': 'completed', 'message': 'Task #3 finished successfully', 'crawler_url': 'http://localhost:8000/api/agent/tasks/3', 'finished_at': '2026-04-01T17:16:11.652535'}}

## 2026-04-01T17:16:34.741956+00:00
- ws_stream_valid input={'command':'echo WS_OK','cwd':'/Users/xxvirusxx'} output=[{'type':'start'},{'type':'output','data':'WS_OK\n'},{'type':'done','exit_code':0}]
- ws_stream_invalid_cwd input={'command':'echo SHOULD_FAIL','cwd':'/definitely/not/allowed'} output=[{'type':'error','data':'Invalid working directory...'}, {'type':'done','exit_code':1}]

## host-link-check
- execute_tool crawler_url=http://192.168.1.11:8000/api/agent/tasks/5
- list_tasks first_url=http://192.168.1.11:8000/api/agent/tasks/5

## 2026-04-01T18:11:04.807527Z
- bugfix_create_idea_null_title: patched app/main.py to guard None for title/body/tags
- local_testclient_create_idea: input={'body':'idea one','title':None,'tags':None} output=200
- local_testclient_create_idea_blank_body: input={'body':'   '} output=400 'Idea body required'
- local_testclient_patch_idea_null_fields: output=200

## 2026-04-01T18:18:08.558478Z
- fix_agent_tasks_401: switched crawler UI to authenticated fetch via openTaskTracker(taskId)

## 2026-04-01T18:32:46.791605Z
- removed_token_exposure: crawler_url no longer includes token query
- added_agent_sessions_api: /api/agent/sessions, /api/agent/sessions/{id}
- ask_agent_session_context: stores user+assistant messages and reuses context prompt
- notifications_poll_interval: 2s with BroadcastChannel cross-tab relay

## 2026-04-01T18:50:23.592158Z
- added_agent_inbox_tab: nav + mobile drawer + dedicated view
- added_inbox_session_list_preview: message_count + last_message_preview
- added_inbox_thread_continue: open session + send prompt continues context

## 2026-04-01T22:30:48.980033Z
- inbox_send_server_authoritative: added POST /api/agent/sessions/{id}/send
- session_agent_lock_verified: session codex stayed codex in inbox send

## 2026-04-02T21:46:45.789733Z
- edgefix_agent_sessions_permissions: list/create/send now enforce copilot permission
- edgefix_agent_sessions_plan_limits: send now enforces plan limits
- edgefix_agent_sessions_trust: send now enforces trust policy + approval gate
- edgefix_invalid_agent_create: invalid agent normalized to copilot
