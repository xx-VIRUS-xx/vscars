# AGENT TOGGLE TEST

- Timestamp: 2026-04-01T04:27:47.112603+00:00
- Summary: total=3 passed=3 failed=0

## Case 1
- Input: `{'tool': 'ask_agent', 'prompt': 'Reply exactly: API_OK_COPILOT', 'agent': 'copilot', 'model': 'gpt-5.2', 'allow_tools': 'all', 'project_path': ''}`
- HTTP: `200`
- Success: `True`
- Error: `None`
- Output(head): `🧭 Agent: Copilot Agent
🎯 Requested Model: gpt-5.2

🤖 COPILOT AGENT RESPONSE
📁 Project: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_agent_toggle_8tdp9e9p/ws
🧠 Model: gpt-5.2
🔧 Permissions: all

API_OK_COPILOT`

## Case 2
- Input: `{'tool': 'ask_agent', 'prompt': 'Reply exactly: API_OK_CLAUDE', 'agent': 'claude', 'model': 'claude-sonnet-4.6', 'allow_tools': 'all', 'project_path': ''}`
- HTTP: `200`
- Success: `True`
- Error: `None`
- Output(head): `🧭 Agent: Claude Code
🎯 Requested Model: claude-sonnet-4.6

🤖 COPILOT AGENT RESPONSE
📁 Project: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_agent_toggle_8tdp9e9p/ws
🧠 Model: claude-sonnet-4.6
🔧 Permissions: al`

## Case 3
- Input: `{'tool': 'ask_agent', 'prompt': 'Reply exactly: API_OK_CODEX', 'agent': 'codex', 'model': 'gpt-5.3-codex', 'allow_tools': 'all', 'project_path': ''}`
- HTTP: `200`
- Success: `True`
- Error: `None`
- Output(head): `🧭 Agent: Codex
🎯 Requested Model: gpt-5.3-codex

🤖 COPILOT AGENT RESPONSE
📁 Project: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_agent_toggle_8tdp9e9p/ws
🧠 Model: gpt-5.3-codex
🔧 Permissions: all

API_OK_CODE`
