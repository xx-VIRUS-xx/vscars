# AGENT ASYNC TEST

- Timestamp: 2026-04-01T17:15:59.792383+00:00

## run_command_http
- Input: `{'tool': 'run_command', 'command': 'echo TERM_HTTP_OK'}`
- Output: `{'success': True, 'result_head': '✅ SUCCESS\n📁 CWD: /Users/xxvirusxx\n\nTERM_HTTP_OK\n'}`

## ask_agent_async_queue
- Input: `{'tool': 'ask_agent', 'prompt': 'Reply exactly: THREAD_ASYNC_OK', 'agent': 'codex', 'model': 'gpt-5.3-codex', 'allow_tools': 'all'}`
- Output: `{'success': True, 'status': 'queued', 'task_id': 3, 'crawler_url': 'http://localhost:8000/api/agent/tasks/3', 'result_head': '⏳ Task queued: #3\nTrack progress: http://localhost:8000/api/agent/tasks/3\nYou will get a notification when the task finishes.'}`

## ask_agent_async_complete
- Input: `{'task_id': 3}`
- Output: `{'status': 'completed', 'result_head': '🧭 Agent: Codex\n🎯 Requested Model: gpt-5.3-codex\n\n🤖 COPILOT AGENT RESPONSE\n📁 Project: /Users/xxvirusxx\n🧠 Model: gpt-5.3-codex\n🔧 Permissions: all\n\nTHREAD_ASYNC_OK'}`

## agent_notifications
- Input: `{}`
- Output: `{'count': 1, 'first': {'task_id': 3, 'tool': 'ask_agent', 'status': 'completed', 'message': 'Task #3 finished successfully', 'crawler_url': 'http://localhost:8000/api/agent/tasks/3', 'finished_at': '2026-04-01T17:16:11.652535'}}`
