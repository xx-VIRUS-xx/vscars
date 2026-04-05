# Tools Smoke Test Log

## Run 2026-03-31 21:10:04 UTC

Summary: total=18, passed=6, soft_fail=2, hard_fail=10

- FAIL `open_file` (http 200) :: Approval required before execution. Request #1 is pending.
- PASS `open_project` (http 200) :: ✅ Project opened in VS Code 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke_1fhlkg5q/ws
- FAIL `create_file` (http 200) :: Approval required before execution. Request #2 is pending.
- FAIL `edit_file` (http 200) :: Approval required before execution. Request #3 is pending.
- FAIL `delete_file` (http 200) :: Approval required before execution. Request #4 is pending.
- FAIL `read_file` (http 200) :: Approval required before execution. Request #5 is pending.
- FAIL `run_command` (http 200) :: Approval required before execution. Request #6 is pending.
- PASS `list_files` (http 200) :: ✅ Contents of /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke_1fhlkg5q/ws 📊 0 folders, 1 files  📄 seed.txt  (18B)
- PASS `search_files` (http 200) :: 🔍 Search Results (1 matches) 📁 In: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke_1fhlkg5q/ws 🔎 Pattern: hello  /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/
- FAIL `git_status` (http 200) :: ❌ Not a git repository: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke_1fhlkg5q/ws
- FAIL `git_command` (http 200) :: Approval required before execution. Request #7 is pending.
- FAIL `create_project` (http 200) :: Approval required before execution. Request #8 is pending.
- FAIL `open_terminal` (http 200) :: Approval required before execution. Request #9 is pending.
- FAIL `get_workspace_info` (http 200) :: ❌ Error: Command '['copilot', '--version']' timed out after 5 seconds
- FAIL `copilot_agent` (http 200) :: Approval required before execution. Request #10 is pending.
- PASS `browse_directory` (http 200) :: 📂 Directory: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke_1fhlkg5q/ws 📊 0 folders, 1 files (18B)  📁 ws/ └── 📝 seed.txt  (18B)
- PASS `ask_copilot` (http 200) :: 🤖 COPILOT RESPONSE  Sure! Here's a simple "Hello" in Python:  ```python print("Hello!") ```  Or, if you want it in a different language, let me know! 😊  ─────────────────── 📊 Model
- PASS `ask_ai` (http 200) :: 🤖 COPILOT RESPONSE  Hello! How can I assist you with your coding or development needs today? 😊  ─────────────────── 📊 Model: gpt-4o-2024-11-20 | Tokens: 69

## Run 2026-03-31 21:13:00 UTC (approval disabled + git repo)

Summary: total=18, passed=17, failed=1

- PASS `open_file` (http 200) :: ✅ SUCCESS: File opened in VS Code 📄 File: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws/seed.txt 📍 Line: 1
- PASS `open_project` (http 200) :: ✅ Project opened in VS Code 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws
- PASS `create_file` (http 200) :: ✅ File created: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws/new.txt 📊 Size: 3 bytes
- PASS `edit_file` (http 200) :: ✅ SUCCESS: File edited 📄 File: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws/new.txt 📝 Changes: +0 bytes
- PASS `delete_file` (http 200) :: ✅ SUCCESS: File deleted: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws/new.txt
- PASS `read_file` (http 200) :: ✅ File: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws/seed.txt 📊 Lines: 3  hello world line2 
- PASS `run_command` (http 200) :: ✅ SUCCESS 📁 CWD: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws  smoke_ok 
- PASS `list_files` (http 200) :: ✅ Contents of /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws 📊 0 folders, 1 files  📄 seed.txt  (18B)
- PASS `search_files` (http 200) :: 🔍 Search Results (1 matches) 📁 In: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws 🔎 Pattern: hello  /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn
- PASS `git_status` (http 200) :: ✅ Git Status 📁 Repo: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws 🌿 Branch: master  📊 Changes: (Clean — no changes)  📜 Recent Commits: b39253a i
- PASS `git_command` (http 200) :: ✅ SUCCESS 📁 Repo: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws 🔧 Command: git status  On branch master nothing to commit, working tree clean 
- PASS `create_project` (http 200) :: ✅ Project created: smokeproj 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws/smokeproj 🔧 Type: python 📦 Git initialized 💻 Opened in VS Code
- PASS `open_terminal` (http 200) :: ✅ Terminal opened 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws
- FAIL `get_workspace_info` (http 200) :: ❌ Error: Command '['copilot', '--version']' timed out after 5 seconds
- PASS `copilot_agent` (http 200) :: 🤖 COPILOT AGENT RESPONSE 📁 Project: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws 🧠 Model: gpt-4.1 🔧 Permissions: read  I was unable to create th
- PASS `browse_directory` (http 200) :: 📂 Directory: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke2_wr9so1fk/ws 📊 3 folders, 4 files (204B) 🌿 Git branch: master  📁 ws/ ├── 📁 smokeproj/ │   ├── 📁 src
- PASS `ask_copilot` (http 200) :: 🤖 COPILOT RESPONSE  ```python print("Hello!") ```  ─────────────────── 📊 Model: gpt-4o-2024-11-20 | Tokens: 64
- PASS `ask_ai` (http 200) :: 🤖 COPILOT RESPONSE  ```python print("Hello!") ```  ─────────────────── 📊 Model: gpt-4o-2024-11-20 | Tokens: 64


## Run 2026-03-31 21:15:33 UTC (post-fix get_workspace_info)

Summary: total=18, passed=18, failed=0

- PASS `open_file` (http 200) :: ✅ SUCCESS: File opened in VS Code 📄 File: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws/seed.txt 📍 Line: 1
- PASS `open_project` (http 200) :: ✅ Project opened in VS Code 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws
- PASS `create_file` (http 200) :: ✅ File created: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws/new.txt 📊 Size: 3 bytes
- PASS `edit_file` (http 200) :: ✅ SUCCESS: File edited 📄 File: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws/new.txt 📝 Changes: +0 bytes
- PASS `delete_file` (http 200) :: ✅ SUCCESS: File deleted: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws/new.txt
- PASS `read_file` (http 200) :: ✅ File: /private/var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws/seed.txt 📊 Lines: 3  hello world line2 
- PASS `run_command` (http 200) :: ✅ SUCCESS 📁 CWD: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws  smoke_ok 
- PASS `list_files` (http 200) :: ✅ Contents of /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 📊 0 folders, 1 files  📄 seed.txt  (18B)
- PASS `search_files` (http 200) :: 🔍 Search Results (1 matches) 📁 In: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 🔎 Pattern: hello  /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn
- PASS `git_status` (http 200) :: ✅ Git Status 📁 Repo: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 🌿 Branch: master  📊 Changes: (Clean — no changes)  📜 Recent Commits: a71ace2 i
- PASS `git_command` (http 200) :: ✅ SUCCESS 📁 Repo: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 🔧 Command: git status  On branch master nothing to commit, working tree clean 
- PASS `create_project` (http 200) :: ✅ Project created: smokeproj 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws/smokeproj 🔧 Type: python 📦 Git initialized 💻 Opened in VS Code
- PASS `open_terminal` (http 200) :: ✅ Terminal opened 📁 Path: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws
- PASS `get_workspace_info` (http 200) :: 📁 Workspace: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 🖥️  System: Darwin (Prabhats-MacBook-Air.local) 🐍 Python: 3.12.4 💻 VS Code: 1.113.0 📦 
- PASS `copilot_agent` (http 200) :: 🤖 COPILOT AGENT RESPONSE 📁 Project: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 🧠 Model: gpt-4.1 🔧 Permissions: read  I was unable to create th
- PASS `browse_directory` (http 200) :: 📂 Directory: /var/folders/ys/xq1c6fhd2252wf2wx7tvf0xc0000gn/T/vscars_tools_smoke3_ozwlj5ja/ws 📊 3 folders, 4 files (204B) 🌿 Git branch: master  📁 ws/ ├── 📁 smokeproj/ │   ├── 📁 src
- PASS `ask_copilot` (http 200) :: 🤖 COPILOT RESPONSE  ```python print("Hello!") ```  ─────────────────── 📊 Model: gpt-4o-2024-11-20 | Tokens: 64
- PASS `ask_ai` (http 200) :: 🤖 COPILOT RESPONSE  ```python print("Hello!") ```  ─────────────────── 📊 Model: gpt-4o-2024-11-20 | Tokens: 64

