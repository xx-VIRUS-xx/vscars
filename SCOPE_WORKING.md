# VSCARS Scope Working Doc

This file is the editable scope source of truth for the product.

How to use:
- Review the `Current Scope` section and edit anything that feels inaccurate.
- Use `Keep`, `Redefine`, `Defer`, or `Remove` next to each area.
- Add new ideas in `New Scope Candidates`.
- When you want implementation work, point me to this file and I will use it to plan and build.

Suggested status labels:
- `Keep`
- `Redefine`
- `Defer`
- `Remove`
- `New`

---

## Product Direction

### Working product summary
VSCARS is a mobile-first remote developer control platform that lets a user access AI tools, files, terminal commands, git actions, and machine-linked workflows from a web app, with permissions, trust controls, and plan-based access.

### Editing notes
- Primary product identity:
- Primary target user:
- Secondary target user:
- What this product should become:
- What this product should stop trying to be:

---

## Current Scope

### 1. Platform Core
Status: `Redefine`

Current scope:
- FastAPI backend
- SQLite/SQLAlchemy persistence
- Static web frontend
- CLI connector for user machines
- WebSocket relay architecture
- health endpoint
- CORS/security headers
- request size limiting
- rate limiting

Redefine notes:
- better DB

Enhancement ideas:
- Postgre

### 2. Authentication & Account
Status: `Redefine`

Current scope:
- user registration
- user login
- JWT auth
- logout/token revocation
- current-user profile endpoint
- forgot-password flow
- password reset flow
- session tracking
- session revocation
- first-user bootstrap as superuser
- device ID capture

Redefine notes:
- maybe we need better security than JWT
- forgot password and password reset flow is not available on frontend

Enhancement ideas:
- 

### 3. Roles, Permissions, Plans
Status: `Remove` & `Redefine`

Current scope:
- superuser and regular-user roles
- per-user permissions:
  - view files
  - edit files
  - run commands
  - run Copilot/agents
  - use registered machine
- plan model:
  - free
  - pro
  - team
  - self_hosted
- plan-based limits and permissions
- daily API usage counters
- model access by plan

Redefine notes:
- keep plans in archived status right now , we need something to be implemented before we make our tool with pricing models
- we need to test regular-user roles

Enhancement ideas:
- 

### 4. Access Requests & Admin Controls
Status: `Enhance`

Current scope:
- QR-based access request creation
- pending request review
- approve/reject access requests
- superuser permission management

Redefine notes:
- 

Enhancement ideas:
- we need 2-FA as well

### 5. Trust & Safety
Status: `Redefine`

Current scope:
- trust profiles: safe / balanced / power
- approval requirement for sensitive actions
- destructive command blocking
- network command blocking
- command prefix allowlist
- kill switch
- approval queue
- trust audit trail

Redefine notes:
- We need scope for all the trust profiles , also we need to test them and enforce them
- We need to test each one of these features

Enhancement ideas:
- 

### 6. Remote Machine Control
Status: `Redefine`

Current scope:
- machine registration
- machine listing and removal
- CLI init/start/stop/status/logs/workspace commands
- persistent agent WebSocket connection
- relay tool execution on user-owned machine
- machine-connected gating for non-superusers

Redefine notes:
- We need CLI testing

Enhancement ideas:
- 

### 7. Workspace & Settings
Status: `Redefine`

Current scope:
- save/read workspace path
- save/check GitHub token
- API key status
- API key generation/regeneration

Redefine notes:
- Workspace, we need to have a suggestion based thing , once CLI install is done 
- API key status and API key generation is not there yet , we need to see how many API key active and API Key need to be generated on website not the Application

Enhancement ideas:
- 

### 8. File & Workspace Tools
Status: `Redefine`

Current scope:
- open file in VS Code
- open project in VS Code
- read file
- create file
- edit file by find/replace
- delete file
- list files
- browse directory tree
- search files
- workspace/system info
- workspace path sandboxing
- file size limits

Redefine notes:
- We are relying on VS code too much , consumes too much resource for every small task , also we can easily use better ways and consume less resources.

Enhancement ideas:
- 

### 9. Command & Terminal
Status: `Redefine`

Current scope:
- run shell commands
- working directory support
- timeout handling
- dangerous command pattern blocking
- stdout/stderr capture
- open terminal at path
- execution logging
- WebSocket stream endpoint

Redefine notes:
- We need suggestion on shell commands , based on the machine 

Enhancement ideas:
- 

### 10. AI & Agent Experience
Status: `Redefine`

Current scope:
- `ask_copilot`
- `ask_ai`
- `copilot_agent`
- `ask_agent`
- async agent task queue
- task status tracking
- agent notifications
- persistent agent sessions
- send message into agent session
- session message history
- model catalogue
- plan-based model gating

Redefine notes:
- ask_copilot is actually listing hardcoded agents and not trying to find agents in my system although we want to keep everything as it is , but we have to restrict 

Enhancement ideas:
- 

### 11. Git Features
Status: `Keep`

Current scope:
- git status
- git diff
- git stage
- git unstage
- git commit
- git push
- git log
- git branches
- AI commit message generation

Redefine notes:
- 

Enhancement ideas:
- 

### 12. Project Creation & Dev Bootstrap
Status: `Redefine`

Current scope:
- create project from templates
- template types:
  - python
  - node
  - react
  - flask
  - fastapi
- optional AI prompt during project creation
- git init during project setup

Redefine notes:
- 

Enhancement ideas:
- 

### 13. Ideas & Workflow Management
Status: `Keep`

Current scope:
- idea vault
- create/list/update/delete ideas
- tags on ideas
- mark idea done/pending
- saved workflows
- create/list/delete workflows
- one-tap workflow run
- workflow usage stats

Redefine notes:
- 

Enhancement ideas:
- 

### 14. History, Logs & Dashboard
Status: `Keep`

Current scope:
- tool history
- conversation history
- execution log
- reset history
- dashboard brief stats
- commands-today count
- ideas-pending count
- git summary widgets

Redefine notes:
- 

Enhancement ideas:
- 

### 15. Bug Tracking
Status: `Defer`

Current scope:
- bug list
- bug reporting
- reopen/recurring occurrence tracking
- severity and status fields
- stored root-cause/fix detail fields

Redefine notes:
- 

Enhancement ideas:
- 

### 16. Billing & Commercial
Status: `Keep`

Current scope:
- billing status
- Stripe checkout
- Stripe billing portal
- Stripe webhooks
- self-hosted license validation
- admin license generation
- plan/pricing metadata

Redefine notes:
- 

Enhancement ideas:
- 

### 17. Remote Access & Deployment
Status: `Keep`

Current scope:
- ngrok support
- public URL endpoint
- landing page
- setup page
- deployment scripts/configs

Redefine notes:
- 

Enhancement ideas:
- 

### 18. Frontend Views
Status: `Keep`

Current scope:
- dashboard
- ideas
- git
- terminal/tools
- workflows
- file browser
- conversations/chat
- agent inbox
- activity/logs
- machines
- settings
- billing
- admin

Redefine notes:
- 

Enhancement ideas:
- 

---

## Scope Decisions

### Must-Have Scope
- 

### Nice-to-Have Scope
- 

### Premium-Only Scope
- 

### Out of Scope
- 

---

## New Scope Candidates

Use this section to define anything new you want added.

### Candidate 1
Status: `New`
Name:
Problem:
Why it matters:
Target user:
High-level behavior:
Dependencies:
Risks:
Success criteria:

### Candidate 2
Status: `New`
Name:
Problem:
Why it matters:
Target user:
High-level behavior:
Dependencies:
Risks:
Success criteria:

### Candidate 3
Status: `New`
Name:
Problem:
Why it matters:
Target user:
High-level behavior:
Dependencies:
Risks:
Success criteria:

---

## Build Queue

List features here in the order you want me to implement them.

1. 
2. 
3. 
4. 
5. 

---

## Notes For Codex

When I ask for implementation work, use this file as the source of truth.

Current priorities:
- 

Constraints:
- 

Do not change:
- 

Definition of done:
- 
