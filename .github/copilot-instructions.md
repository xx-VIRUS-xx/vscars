# VS Code Copilot Mobile Controller - Project Instructions

## Overview
This is an MCP (Model Context Protocol) server that provides HTTP-based access to control VS Code and Copilot from mobile devices or remote clients through REST API endpoints.

## Project Structure

### Main Files
- `src/index.ts` - MCP server with stdio transport (for Claude/Copilot integration)
- `src/http-bridge.ts` - Express HTTP server for mobile client access
- `package.json` - Project dependencies and build scripts
- `tsconfig.json` - TypeScript configuration
- `.vscode/mcp.json` - MCP server configuration for VS Code

### Available Tools
1. **open_file** - Open a file in VS Code
2. **create_file** - Create a new file with content
3. **edit_file** - Edit existing file content via find-replace
4. **delete_file** - Delete a file
5. **read_file** - Read file contents
6. **run_command** - Execute shell commands
7. **list_files** - List files in a directory
8. **ask_copilot** - Send queries to Copilot Chat

## Setup Instructions

### Installation
1. Install dependencies: `npm install`
2. Build the project: `npm run build`

### Running the Server

#### Option 1: MCP Server (for Claude/Copilot integration)
```bash
npm run start
```

#### Option 2: HTTP Bridge (for mobile access)
```bash
node build/http-bridge.js
```
The HTTP bridge listens on port 3000 by default. Set the `PORT` environment variable to use a different port.

## API Usage (HTTP Bridge)

### Endpoints

#### Health Check
```
GET /health
```

#### List Available Tools
```
GET /tools
```

#### Get Tool Details
```
GET /tools/{toolName}
```

#### Execute Tool
```
POST /execute/{toolName}
Body: { "filepath": "...", "content": "...", ... }
```

#### Simple Query Interface
```
POST /query
Body: { "tool": "toolName", "params": { "filepath": "...", ... } }
```

## Example Mobile Requests

### Open a file
```json
POST /execute/open_file
{
  "filepath": "/path/to/file.js",
  "line": 42
}
```

### Create a file
```json
POST /execute/create_file
{
  "filepath": "/path/to/new-file.ts",
  "content": "console.log('Hello from mobile!');"
}
```

### Run a command
```json
POST /execute/run_command
{
  "command": "npm run build"
}
```

### Ask Copilot
```json
POST /execute/ask_copilot
{
  "query": "How do I create a React component?"
}
```

## Configuration

### MCP Server Configuration (.vscode/mcp.json)
The MCP server can be configured in VS Code settings for use with Claude or other MCP clients.

## Development

### Build & Watch
```bash
npm run watch
```

### Code Style
- Language: TypeScript
- Strict mode enabled
- Target: ES2020

## Mobile Client Examples

### cURL
```bash
curl -X POST http://localhost:3000/execute/open_file \
  -H "Content-Type: application/json" \
  -d '{"filepath":"/path/to/file.js"}'
```

### JavaScript/Node
```javascript
const response = await fetch('http://localhost:3000/execute/run_command', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ command: 'npm run build' })
});
const result = await response.json();
console.log(result);
```

### Python
```python
import requests
response = requests.post(
  'http://localhost:3000/execute/read_file',
  json={'filepath': 'src/index.ts'}
)
print(response.json())
```

## Testing

1. Start the HTTP bridge: `node build/http-bridge.js`
2. Test health endpoint: `curl http://localhost:3000/health`
3. List tools: `curl http://localhost:3000/tools`
4. Execute tools via the provided endpoints above

## Notes

- The MCP server uses stdio transport for integration with Claude/Copilot
- The HTTP bridge provides convenient REST API access for any client including mobile apps
- File paths should be absolute or relative to the current working directory
- The Copilot integration requires VS Code to be installed and the Copilot extension enabled
