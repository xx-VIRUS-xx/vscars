// ==================== GLOBAL STATE ====================
let currentUser = null;
let authToken = null;
let billingStatus = null;
let _sessionExpired = false;
let _tokenExpiryTimer = null;

// ==================== SESSION EXPIRY ====================

function handleSessionExpiry() {
    if (_sessionExpired) return; // prevent double-fire
    _sessionExpired = true;
    if (_tokenExpiryTimer) { clearTimeout(_tokenExpiryTimer); _tokenExpiryTimer = null; }
    localStorage.removeItem('authToken');
    localStorage.removeItem('currentUser');
    authToken = null;
    currentUser = null;
    hideLoading();
    // Close any open modals
    ['tool-modal','upgrade-modal','qr-modal','onboarding-modal'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    showToast('Session expired — please sign in again', 'warning', 5000);
    setTimeout(() => {
        _sessionExpired = false;
        showAuthView();
    }, 600);
}

function scheduleTokenExpiry(token) {
    if (_tokenExpiryTimer) { clearTimeout(_tokenExpiryTimer); _tokenExpiryTimer = null; }
    try {
        const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
        const expiresAt = payload.exp * 1000;
        const now = Date.now();
        const msLeft = expiresAt - now;
        if (msLeft <= 0) { handleSessionExpiry(); return; }
        // Warn 2 min before expiry
        if (msLeft > 120000) {
            setTimeout(() => showToast('Session expires in 2 minutes', 'warning', 6000), msLeft - 120000);
        }
        _tokenExpiryTimer = setTimeout(handleSessionExpiry, msLeft);
    } catch (e) { /* non-decodable token — ignore */ }
}

// ==================== THEME SYSTEM ====================
function getPreferredTheme() {
    const saved = localStorage.getItem('theme');
    if (saved && saved !== 'auto') return saved;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function setTheme(mode) {
    localStorage.setItem('theme', mode);
    const applied = mode === 'auto'
        ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
        : mode;
    document.documentElement.setAttribute('data-theme', applied);
    const meta = document.getElementById('meta-theme');
    if (meta) meta.content = applied === 'dark' ? '#1e1e1e' : '#dddddd';
    const btn = document.getElementById('theme-btn');
    if (btn) btn.textContent = applied === 'dark' ? '\u2600' : '\u263E';
    document.querySelectorAll('#chip-dark,#chip-light,#chip-auto').forEach(c => c.classList.remove('active'));
    const chip = document.getElementById('chip-' + mode);
    if (chip) chip.classList.add('active');
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    setTheme(current === 'dark' ? 'light' : 'dark');
}

// Apply theme immediately
setTheme(getPreferredTheme());

// ==================== WEBSOCKET STREAM ====================
let _streamWS = null;

function getStreamWS() {
    if (_streamWS && _streamWS.readyState === WebSocket.OPEN) return _streamWS;
    if (!authToken) return null;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    _streamWS = new WebSocket(`${proto}://${location.host}/ws/stream?token=${encodeURIComponent(authToken)}`);
    _streamWS.onclose = () => { _streamWS = null; };
    _streamWS.onerror = () => { _streamWS = null; };
    return _streamWS;
}

function streamCommand(command, cwd) {
    return new Promise((resolve) => {
        const ws = getStreamWS();
        if (!ws) { resolve(null); return; }

        const output = document.getElementById('result-output');
        const indicator = document.getElementById('stream-indicator');
        output.textContent = '';
        document.getElementById('tool-result').style.display = 'block';
        if (indicator) indicator.style.display = 'inline-block';

        let buffer = '';

        const onMessage = (evt) => {
            const msg = JSON.parse(evt.data);
            if (msg.type === 'output') {
                buffer += msg.data;
                output.textContent = buffer;
                output.scrollTop = output.scrollHeight;
            } else if (msg.type === 'error') {
                buffer += `\n❌ ${msg.data}\n`;
                output.textContent = buffer;
            } else if (msg.type === 'done') {
                if (indicator) indicator.style.display = 'none';
                ws.removeEventListener('message', onMessage);
                resolve(buffer);
            }
        };

        const ready = () => {
            ws.addEventListener('message', onMessage);
            ws.send(JSON.stringify({ command, cwd }));
        };

        if (ws.readyState === WebSocket.OPEN) {
            ready();
        } else {
            ws.addEventListener('open', ready, { once: true });
        }
    });
}

// ==================== DEVICE DETECTION ====================
// UA string covers most phones. Touch + coarse-pointer covers the rest
// (some Android WebViews don't include Android in UA).
// We intentionally exclude screen width so a narrow desktop window never triggers mobile layout.
const _mobileUA  = /Android|iPhone|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
const _iPadOS    = /Macintosh/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1;
const _iPad      = /iPad/i.test(navigator.userAgent);
const _coarse    = window.matchMedia('(pointer:coarse)').matches && navigator.maxTouchPoints > 0
                   && !/Win/i.test(navigator.userAgent); // exclude Windows touch laptops
const isMobile = _mobileUA || _iPadOS || _iPad || _coarse;
if (isMobile) document.body.classList.add('is-mobile');

// ==================== TOAST NOTIFICATION SYSTEM ====================

function showToast(message, type = 'info', duration = 3000) {
    // Strip emoji-heavy messages to keep UI clean
    const cleaned = message.replace(/[✅⚠️❌🔑🗑️✓⚠✕]/g, '').trim();
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = cleaned || message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(8px)';
        toast.style.transition = 'opacity 0.25s, transform 0.25s';
        setTimeout(() => toast.remove(), 280);
    }, duration);
}

// ==================== LOADING OVERLAY ====================

function showLoading(text = 'Loading...') {
    const overlay = document.getElementById('loading-overlay');
    document.getElementById('loading-text').textContent = text;
    overlay.style.display = 'flex';
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    overlay.style.display = 'none';
}

// ==================== INITIALIZATION ====================

window.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    checkAuthStatus();
    loadNgrokStatus();
    // React to OS theme changes
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
        if (localStorage.getItem('theme') === 'auto') setTheme('auto');
    });
});

function setupEventListeners() {
    // Navigation menu - use closest for child elements
    document.addEventListener('click', function(e) {
        const item = e.target.closest('.nav-item');
        if (item) {
            const view = item.getAttribute('data-view');
            if (view) {
                switchView(view);
            }
        }
    });

    // Enter key for form submission
    document.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
            const form = e.target.closest('form') || e.target.parentElement;
            const btn = form ? form.querySelector('button') : e.target.parentElement.querySelector('button');
            if (btn) btn.click();
        }
    });
}

// ==================== AUTH FUNCTIONS ====================

function checkAuthStatus() {
    const token = localStorage.getItem('authToken');
    const user = localStorage.getItem('currentUser');
    if (token && user) {
        authToken = token;
        currentUser = JSON.parse(user);
        scheduleTokenExpiry(token); // proactive expiry timer
        showMainView();
    } else {
        showAuthView();
    }
}

function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active from all buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab and mark button as active
    const tabElement = document.getElementById(`${tabName}-tab`);
    const btnElement = document.querySelector(`[data-tab="${tabName}"]`);
    
    if (tabElement) {
        tabElement.classList.add('active');
    }
    
    if (btnElement) {
        btnElement.classList.add('active');
    }
}

async function login() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errorElement = document.getElementById('login-error');

    errorElement.textContent = '';

    if (!username || !password) {
        errorElement.textContent = 'Username and password are required';
        return;
    }
    
    showLoading('Logging in...');
    
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Login failed');
        }
        
        const data = await response.json();
        authToken = data.access_token;
        currentUser = data.user;
        localStorage.setItem('authToken', authToken);
        localStorage.setItem('currentUser', JSON.stringify(currentUser));
        scheduleTokenExpiry(authToken); // start expiry countdown
        hideLoading();
        showToast('Login successful', 'success');
        showMainView();
    } catch (error) {
        hideLoading();
        errorElement.textContent = `❌ ${error.message}`;
        showToast(error.message, 'error');
    }
}

async function register() {
    const username = document.getElementById('register-username').value.trim();
    const email = document.getElementById('register-email').value.trim();
    const password = document.getElementById('register-password').value;
    const errorElement = document.getElementById('register-error');

    errorElement.textContent = '';

    if (!username || !email || !password) {
        errorElement.textContent = 'All fields are required';
        return;
    }

    if (password.length < 6) {
        errorElement.textContent = '⚠️ Password must be at least 6 characters';
        return;
    }

    if (!email.includes('@')) {
        errorElement.textContent = '⚠️ Please enter a valid email';
        return;
    }
    
    showLoading('Creating account...');
    
    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Registration failed');
        }
        
        const data = await response.json();
        authToken = data.access_token;
        currentUser = data.user;
        
        localStorage.setItem('authToken', authToken);
        localStorage.setItem('currentUser', JSON.stringify(currentUser));
        
        hideLoading();
        showToast('✓ Account created successfully!', 'success');
        showMainView();
    } catch (error) {
        hideLoading();
        errorElement.textContent = `❌ ${error.message}`;
        showToast(error.message, 'error');
    }
}

async function requestQRAccess() {
    const username = document.getElementById('qr-username').value.trim();
    const email = document.getElementById('qr-email').value.trim();
    const device_id = document.getElementById('qr-device-id').value.trim();
    const errorElement = document.getElementById('qr-error');
    
    errorElement.textContent = '';
    
    if (!username || !email || !device_id) {
        errorElement.textContent = '⚠️ All fields are required';
        return;
    }
    
    showLoading('Generating QR code...');
    
    try {
        const response = await fetch('/api/access/request-via-qr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username, email, device_id,
                request_type: 'qr_code'
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'QR request failed');
        }
        
        const data = await response.json();
        
        // Display QR code
        document.getElementById('qr-code-image').src = `data:image/png;base64,${data.qr_code_data}`;
        document.getElementById('qr-request-id').textContent = data.request_id;
        document.getElementById('qr-display').style.display = 'block';
        
        hideLoading();
        showToast('✓ QR code generated!', 'success');
    } catch (error) {
        hideLoading();
        errorElement.textContent = `❌ ${error.message}`;
        showToast(error.message, 'error');
    }
}

function logout() {
    if (_tokenExpiryTimer) { clearTimeout(_tokenExpiryTimer); _tokenExpiryTimer = null; }
    if (authToken) {
        fetchAPI('/api/auth/logout', { method: 'POST' }).catch(() => {});
    }
    localStorage.removeItem('authToken');
    localStorage.removeItem('currentUser');
    authToken = null;
    currentUser = null;
    clearErrors();
    showToast('Signed out', 'info');
    showAuthView();
}

// ==================== VIEW SWITCHING ====================

function showAuthView() {
    document.getElementById('auth-container').style.display = 'flex';
    document.getElementById('main-container').style.display = 'none';
}

function showMainView() {
    document.getElementById('auth-container').style.display = 'none';
    document.getElementById('main-container').style.display = 'flex';
    
    // Update user info
    document.getElementById('user-name').textContent = currentUser.username;
    const badge = document.getElementById('user-badge');
    if (currentUser.is_superuser) {
        badge.textContent = 'Superuser';
        badge.classList.add('superuser');
        document.getElementById('admin-nav').style.display = 'flex';
        const adminMobile = document.getElementById('admin-mobile-link');
        if (adminMobile) adminMobile.style.display = 'block';
    } else {
        badge.textContent = 'User';
        badge.classList.remove('superuser');
    }
    
    loadDashboard();
    loadTools();
    checkGitHubToken();
    loadBillingStatus();

    if (shouldShowOnboarding()) {
        setTimeout(showOnboarding, 600);
    }
}

function switchView(viewName) {
    // Hide all views
    document.querySelectorAll('.view').forEach(view => {
        view.classList.remove('active');
    });
    
    // Remove active from all nav items (sidebar + mobile)
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Show selected view
    const viewElement = document.getElementById(`${viewName}-view`);
    if (viewElement) viewElement.classList.add('active');
    
    // Set active on ALL matching nav items (sidebar + mobile nav)
    document.querySelectorAll(`[data-view="${viewName}"]`).forEach(el => el.classList.add('active'));
    
    // Update drawer current-view highlight
    if (typeof _updateDrawerCurrentView === 'function') _updateDrawerCurrentView();

    // Load view-specific data
    if (viewName === 'admin') {
        loadAdminPanel();
    } else if (viewName === 'activity') {
        loadActivityLog();
    } else if (viewName === 'conversations') {
        loadConversations();
    } else if (viewName === 'settings') {
        checkGitHubToken();
        loadWorkspace();
    }
}


// ==================== DASHBOARD ====================

async function loadDashboard() {
    try {
        // Load permissions
        const response = await fetchAPI('/api/auth/me');
        const user = response;
        
        // Display permissions
        const permissionsDisplay = document.getElementById('permissions-display');
        if (permissionsDisplay) {
            const perms = [
                { label: 'Copilot',  ok: user.can_run_copilot   },
                { label: 'Commands', ok: user.can_run_commands   },
                { label: 'Edit',     ok: user.can_edit_files     },
                { label: 'View',     ok: user.can_view_files     },
            ];
            permissionsDisplay.innerHTML = perms.map(p =>
                `<span class="perm-chip ${p.ok ? 'on' : 'off'}">${p.label}</span>`
            ).join('');
        }
    } catch (error) {
        console.error('Error loading dashboard:', error);
        showToast('Error loading dashboard', 'error');
    }
}

function quickOpen() {
    showToolModal('open_file', {
        filepath: { type: 'text', label: 'File Path', required: true },
        line: { type: 'number', label: 'Line Number (optional)', required: false }
    });
}

function quickRun() {
    showToolModal('run_command', {
        command: { type: 'text', label: 'Command', required: true },
        cwd: { type: 'text', label: 'Working Directory (optional)', required: false }
    });
}

function quickChat() {
    showToolModal('ask_copilot', {
        query: { type: 'textarea', label: 'Ask AI (GPT-4o)...', required: true }
    });
}

function quickGitStatus() {
    showToolModal('git_status', {
        repo_path: { type: 'text', label: 'Repo Path (blank = workspace)', required: false }
    });
}

function quickCreateProject() {
    showToolModal('create_project', {
        project_name: { type: 'text', label: 'Project Name', required: true },
        project_type: { type: 'text', label: 'Type (python/node/react/flask/fastapi)', required: false },
        parent_dir: { type: 'text', label: 'Parent Dir (blank = workspace)', required: false },
        copilot_prompt: { type: 'textarea', label: '🤖 Copilot Setup Prompt (optional — AI builds your project)', required: false }
    });
}

function quickWorkspaceInfo() {
    // Execute immediately, no form needed
    showToolModal('get_workspace_info', {});
    // Auto-submit empty form
    setTimeout(() => {
        const form = document.getElementById('tool-form');
        if (form) {
            form.dataset.tool = 'get_workspace_info';
            executeToolForm(new Event('submit'));
        }
    }, 100);
}

function quickCopilotAgent() {
    openCopilotAgentTool();
}

function quickBrowse() {
    showToolModal('browse_directory', {
        dirpath: { type: 'text', label: 'Directory Path (blank = workspace)', required: false },
        depth: { type: 'number', label: 'Tree Depth (default: 3)', required: false }
    });
}

// ==================== TOOLS ====================

async function loadTools() {
    try {
        const tools = await fetchAPI('/api/tools');
        const toolsContainer = document.getElementById('tools-container');
        if (!toolsContainer) return; // tools view redesigned — no legacy container
        toolsContainer.innerHTML = tools.tools.map(tool => `
            <div class="tool-card" onclick="showTool('${tool.name}')">
                <h3>${tool.name}</h3>
                <p>${tool.description}</p>
                <span class="tool-permission">Permission: ${tool.permission_required}</span>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading tools:', error);
        // Don't toast — this is a background call, not user-initiated
    }
}

function showTool(toolName) {
    const toolConfigs = {
        open_file: { filepath: { type: 'text', label: 'File Path', required: true }, line: { type: 'number', label: 'Line Number', required: false } },
        open_project: { project_path: { type: 'text', label: 'Project Path (blank = workspace)', required: false } },
        create_file: { filepath: { type: 'text', label: 'File Path', required: true }, content: { type: 'textarea', label: 'Content', required: true } },
        edit_file: { filepath: { type: 'text', label: 'File Path', required: true }, old_text: { type: 'textarea', label: 'Old Text', required: true }, new_text: { type: 'textarea', label: 'New Text', required: true } },
        delete_file: { filepath: { type: 'text', label: 'File Path', required: true } },
        read_file: { filepath: { type: 'text', label: 'File Path', required: true } },
        run_command: { command: { type: 'text', label: 'Command', required: true }, cwd: { type: 'text', label: 'Working Directory (blank = workspace)', required: false } },
        list_files: { dirpath: { type: 'text', label: 'Directory Path (blank = workspace)', required: false } },
        search_files: { pattern: { type: 'text', label: 'Search Pattern', required: true }, search_path: { type: 'text', label: 'Search In (blank = workspace)', required: false }, file_type: { type: 'text', label: 'File Extension (e.g. py, js)', required: false } },
        git_status: { repo_path: { type: 'text', label: 'Repo Path (blank = workspace)', required: false } },
        git_command: { command: { type: 'text', label: 'Git Command (e.g. add . / commit -m "msg" / push)', required: true }, repo_path: { type: 'text', label: 'Repo Path (blank = workspace)', required: false } },
        create_project: { project_name: { type: 'text', label: 'Project Name', required: true }, project_type: { type: 'text', label: 'Type (python/node/react/flask/fastapi)', required: false }, parent_dir: { type: 'text', label: 'Parent Dir (blank = workspace)', required: false }, copilot_prompt: { type: 'textarea', label: '🤖 Copilot Setup Prompt (optional — AI will build your project)', required: false } },
        open_terminal: { cwd: { type: 'text', label: 'Terminal Path (blank = workspace)', required: false } },
        get_workspace_info: {},
        copilot_agent: { prompt: { type: 'textarea', label: '🤖 What should Copilot do? (edit files, add features, fix bugs, refactor...)', required: true }, project_path: { type: 'text', label: 'Project Path (blank = workspace)', required: false }, model: { type: 'text', label: 'Model (default: claude-haiku-4.5 | claude-sonnet-4.6 / gpt-5.2)', required: false }, allow_tools: { type: 'text', label: 'Permissions (all / read / edit)', required: false } },
        browse_directory: { dirpath: { type: 'text', label: 'Directory Path (blank = workspace)', required: false }, depth: { type: 'number', label: 'Depth (default: 3)', required: false }, show_hidden: { type: 'text', label: 'Show hidden files? (true/false)', required: false } },
        ask_copilot: { query: { type: 'textarea', label: 'Ask AI (GPT-4o)...', required: true } },
        copilot_agent: {
            prompt:       { type: 'textarea', label: 'What should Copilot do? (edit files, add features, fix bugs…)', required: true },
            project_path: { type: 'text',     label: 'Project Path (blank = workspace)', required: false },
            model:        { type: 'select',   label: 'Model', source: 'copilot-models', required: false },
            allow_tools:  { type: 'text',     label: 'Permissions (all / read / edit)', required: false }
        }
    };

    // copilot_agent needs async model fetch — delegate to dedicated function
    if (toolName === 'copilot_agent') {
        openCopilotAgentTool();
        return;
    }

    showToolModal(toolName, toolConfigs[toolName] || {});
}

// Fetch available models then open copilot_agent modal with dynamic select
async function openCopilotAgentTool(prefillModel) {
    document.getElementById('modal-title').textContent = '⚡ Execute: copilot_agent';
    const inputsContainer = document.getElementById('tool-inputs');
    inputsContainer.innerHTML = '<p class="muted sm" style="padding:8px 0">Loading models…</p>';
    document.getElementById('tool-form').dataset.tool = 'copilot_agent';
    document.getElementById('tool-form').reset();
    document.getElementById('tool-result').style.display = 'none';
    document.getElementById('result-output').textContent = '';
    document.getElementById('tool-modal').classList.add('open');

    let models = [];
    let defaultModel = 'claude-haiku-4.5';
    try {
        const res = await fetchAPI('/api/copilot/models');
        models = res.models || [];
        defaultModel = res.default || defaultModel;
        if (res.message && models.length === 0) {
            inputsContainer.innerHTML = `<p class="muted sm" style="padding:12px 0;color:var(--error)">${res.message}</p>`;
            return;
        }
    } catch (e) {
        // Fallback static list if endpoint unreachable
        models = [
            {id:'claude-haiku-4.5', label:'Claude Haiku 4.5', speed:'Fast',   tier:'standard'},
            {id:'claude-sonnet-4.6',label:'Claude Sonnet 4.6',speed:'Balanced',tier:'standard'},
            {id:'gpt-4.1',          label:'GPT-4.1',          speed:'Balanced',tier:'standard'},
            {id:'gpt-5.2',          label:'GPT-5.2',          speed:'Smart',   tier:'premium'},
        ];
    }

    const selected = prefillModel || defaultModel;
    const modelOptions = models.map(m =>
        `<option value="${m.id}" ${m.id === selected ? 'selected' : ''}>${m.label} — ${m.speed}${m.tier === 'premium' ? ' ★' : ''}</option>`
    ).join('');

    inputsContainer.innerHTML = `
        <div>
            <label>What should Copilot do?</label>
            <textarea name="prompt" placeholder="Add dark mode toggle, refactor auth module, fix the login bug…" required rows="4" style="font-size:13px"></textarea>
        </div>
        <div>
            <label>Model</label>
            <select name="model" style="width:100%">${modelOptions}</select>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div>
                <label>Project Path <span class="muted" style="font-weight:400">(blank = workspace)</span></label>
                <input type="text" name="project_path" placeholder="~/PY/myproject" style="font-family:var(--mono);font-size:12px">
            </div>
            <div>
                <label>Permissions</label>
                <select name="allow_tools" style="width:100%">
                    <option value="all" selected>All (read + write + run)</option>
                    <option value="edit">Edit only</option>
                    <option value="read">Read only</option>
                </select>
            </div>
        </div>
    `;
}

function showToolModal(toolName, inputs) {
    document.getElementById('modal-title').textContent = `⚡ Execute: ${toolName}`;

    const inputsContainer = document.getElementById('tool-inputs');
    inputsContainer.innerHTML = Object.entries(inputs).map(([key, config]) => {
        if (config.type === 'textarea') {
            return `<div><label>${config.label}</label>
                <textarea name="${key}" placeholder="${config.label}" ${config.required ? 'required' : ''}></textarea></div>`;
        } else if (config.type === 'select') {
            const opts = (config.options || []).map(o =>
                `<option value="${o.value}">${o.label}</option>`).join('');
            return `<div><label>${config.label}</label>
                <select name="${key}" style="width:100%">${opts}</select></div>`;
        } else {
            return `<div><label>${config.label}</label>
                <input type="${config.type}" name="${key}" placeholder="${config.label}" ${config.required ? 'required' : ''} /></div>`;
        }
    }).join('');

    document.getElementById('tool-form').dataset.tool = toolName;
    document.getElementById('tool-form').reset();
    document.getElementById('tool-result').style.display = 'none';
    document.getElementById('result-output').textContent = '';
    document.getElementById('tool-modal').classList.add('open');
}

async function executeToolForm(e) {
    e.preventDefault();
    
    const formElement = document.getElementById('tool-form');
    const toolName = formElement.dataset.tool;
    const formData = new FormData(formElement);
    
    // CAPTURE all values IMMEDIATELY before anything async
    const params = { tool: toolName };
    for (let [key, value] of formData.entries()) {
        if (value) params[key] = value;
    }
    
    // Reset form inputs so user can type a new query immediately,
    // but KEEP dataset.tool so consecutive submits work without reopening modal
    formElement.reset();
    formElement.dataset.tool = toolName;
    document.getElementById('result-output').textContent = '';
    document.getElementById('tool-result').style.display = 'none';
    
    // Use WebSocket streaming for run_command — gives live output
    if (toolName === 'run_command' && authToken) {
        const ws = getStreamWS();
        if (ws) {
            showLoading(`Running command...`);
            const output = await streamCommand(params.command, params.cwd);
            hideLoading();
            if (output !== null) {
                showToast('Command finished', output && !output.includes('❌') ? 'success' : 'warning');
                return;
            }
            // Fall through to HTTP if WS failed
        }
    }

    showLoading(`Executing ${toolName}...`);

    // Show "check your laptop" hint after 30s for long-running requests
    const longRunTimer = setTimeout(() => {
        document.getElementById('loading-text').textContent =
            `⏳ ${toolName} is still running — check your laptop for progress`;
    }, 30000);

    try {
        const response = await fetchAPI('/api/tools/execute', {
            method: 'POST',
            body: JSON.stringify(params)
        });
        
        clearTimeout(longRunTimer);
        hideLoading();
        
        const output = response.result || response.error || '(No output)';
        const success = response.success || false;
        
        // Display result
        if (output && output.trim().length > 0) {
            document.getElementById('result-output').textContent = output;
            document.getElementById('tool-result').style.display = 'block';
        }
        
        // Toast
        if (success || output.includes('✅')) {
            showToast(`✅ ${toolName} executed!`, 'success');
        } else if (output.includes('⚠️')) {
            showToast(`⚠️ ${toolName} warning`, 'warning');
        } else if (output.includes('❌')) {
            showToast(`❌ ${toolName} error`, 'error');
        }
        
        // Show result directly — no more polling needed
        if (toolName === 'ask_copilot') {
            setTimeout(() => loadConversations(), 1000);
        }
    } catch (error) {
        clearTimeout(longRunTimer);
        hideLoading();

        if (error.status === 429) {
            // Quota exhausted — offer model alternatives instead of billing page
            const altModels = [
                { id: 'claude-haiku-4.5',   label: 'Claude Haiku 4.5',   badge: 'Fast' },
                { id: 'claude-sonnet-4.6',  label: 'Claude Sonnet 4.6',  badge: 'Smart' },
                { id: 'claude-opus-4.6',    label: 'Claude Opus 4.6',    badge: 'Powerful' },
                { id: 'gpt-5.2',            label: 'GPT-5.2',            badge: 'OpenAI' },
                { id: 'gpt-4.1',            label: 'GPT-4.1',            badge: 'OpenAI' },
            ];
            const modelHtml = altModels.map(m =>
                `<button onclick="retryWithModel('${m.id}')" style="display:flex;align-items:center;gap:8px;width:100%;padding:10px 12px;background:var(--g2);border:1px solid var(--b1);border-radius:8px;cursor:pointer;margin-bottom:6px;color:var(--t1);text-align:left;transition:background 0.15s" onmouseover="this.style.background='var(--g3)'" onmouseout="this.style.background='var(--g2)'">
                    <span style="flex:1;font-size:13px">${m.label}</span>
                    <span style="font-size:10px;padding:2px 7px;background:var(--a);color:#000;border-radius:10px;font-weight:700">${m.badge}</span>
                </button>`
            ).join('');
            document.getElementById('result-output').innerHTML = `<div style="font-size:13px;margin-bottom:12px;color:var(--t2)">Quota exhausted on current model. Pick an alternative:</div>${modelHtml}`;
            document.getElementById('tool-result').style.display = 'block';
            hideLoading();
            return;
        }

        if (error.status === 401) {
            // handleSessionExpiry() already called by fetchAPI
            return;
        }
        
        // Friendly message for timeout/network errors instead of raw error
        const isTimeout = error.name === 'AbortError' || 
                          error.message.includes('Failed to fetch') ||
                          error.message.includes('NetworkError') ||
                          error.message.includes('timeout') ||
                          error.message.includes('network');
        
        if (isTimeout) {
            const friendlyMsg = `⏳ Request is taking longer than expected.\nCheck your laptop — ${toolName} may still be running in the background.`;
            document.getElementById('result-output').textContent = friendlyMsg;
            document.getElementById('tool-result').style.display = 'block';
            showToast('Check your laptop — request is still processing', 'warning', 5000);
        } else {
            const errorMsg = `❌ ERROR: ${error.message}`;
            document.getElementById('result-output').textContent = errorMsg;
            document.getElementById('tool-result').style.display = 'block';
            showToast(`Error executing ${toolName}: ${error.message}`, 'error');
        }
    }
}

// ==================== COPILOT RESPONSE CAPTURE ====================

// (Copilot now uses direct API — no polling needed)

// ==================== SETTINGS & GITHUB TOKEN ====================

async function checkGitHubToken() {
    try {
        const result = await fetchAPI('/api/settings/github-token');
        const statusEl = document.getElementById('token-status');
        if (statusEl) {
            if (result.configured) {
                statusEl.innerHTML = `<span style="color:var(--success)">✓ Token configured (${escapeHtml(result.token_prefix)})</span>`;
            } else {
                statusEl.innerHTML = `<span style="color:var(--error)">✗ No token set — AI Chat disabled</span>`;
            }
        }
    } catch (e) { /* ignore */ }
}

async function saveGitHubToken() {
    const tokenInput = document.getElementById('github-token-input');
    const token = tokenInput.value.trim();
    
    if (!token) {
        showToast('Please enter your GitHub token', 'warning');
        return;
    }
    
    showLoading('Saving token...');
    
    try {
        const result = await fetchAPI('/api/settings/github-token', {
            method: 'POST',
            body: JSON.stringify({ token })
        });
        
        hideLoading();
        
        if (result.success) {
            showToast('✅ GitHub token saved! AI Chat is ready.', 'success');
            tokenInput.value = '';
            checkGitHubToken();
        } else {
            showToast(result.error || 'Failed to save token', 'error');
        }
    } catch (error) {
        hideLoading();
        showToast(`Error: ${error.message}`, 'error');
    }
}

// ==================== WORKSPACE PATH ====================

async function loadWorkspace() {
    try {
        const result = await fetchAPI('/api/settings/workspace');
        const statusEl = document.getElementById('workspace-status');
        const inputEl = document.getElementById('workspace-path-input');
        if (statusEl && result.workspace) {
            statusEl.innerHTML = `<span style="color:var(--success)">Current: <code style="color:var(--fg-link);background:var(--bg-input);padding:2px 6px;border-radius:3px;font-family:var(--font-mono)">${escapeHtml(result.workspace)}</code></span>`;
            if (inputEl) inputEl.placeholder = result.workspace;
        }
    } catch (e) {
        const statusEl = document.getElementById('workspace-status');
        if (statusEl) statusEl.innerHTML = '<span style="color:var(--fg-dim)">Could not load workspace</span>';
    }
}

async function saveWorkspace() {
    const input = document.getElementById('workspace-path-input');
    const path = input.value.trim();
    
    if (!path) {
        showToast('Please enter a workspace path', 'warning');
        return;
    }
    
    showLoading('Setting workspace...');
    
    try {
        const result = await fetchAPI('/api/settings/workspace', {
            method: 'POST',
            body: JSON.stringify({ workspace_path: path })
        });
        
        hideLoading();
        
        if (result.success) {
            showToast(`✅ Workspace set to: ${result.workspace}`, 'success');
            input.value = '';
            loadWorkspace();
        } else {
            showToast(result.error || 'Failed to set workspace', 'error');
        }
    } catch (error) {
        hideLoading();
        showToast(`Error: ${error.message}`, 'error');
    }
}

function setQuickWorkspace(path) {
    document.getElementById('workspace-path-input').value = path;
    saveWorkspace();
}

async function loadSystemInfo() {
    const el = document.getElementById('system-info');
    el.textContent = 'Loading...';
    
    try {
        const result = await fetchAPI('/api/tools/execute', {
            method: 'POST',
            body: JSON.stringify({ tool: 'get_workspace_info' })
        });
        el.textContent = result.result || result.error || 'No info available';
    } catch (e) {
        el.textContent = 'Error loading system info: ' + e.message;
    }
}

// ==================== RESET HISTORY ====================

async function resetAllHistory() {
    if (!confirm('⚠️ This will permanently delete ALL your conversations and activity logs. Continue?')) {
        return;
    }
    
    showLoading('Resetting history...');
    
    try {
        const result = await fetchAPI('/api/history/reset', {
            method: 'DELETE'
        });
        
        hideLoading();
        
        if (result.success) {
            showToast(`🗑️ ${result.message}`, 'success');
            // Refresh all views
            loadConversations();
            loadActivityLog();
        } else {
            showToast(result.error || 'Reset failed', 'error');
        }
    } catch (error) {
        hideLoading();
        showToast(`Error: ${error.message}`, 'error');
    }
}

// ==================== FILE BROWSER ====================

let currentBrowsePath = '';

async function browsePath(customPath) {
    const pathInput = document.getElementById('file-path-input');
    const path = customPath || (pathInput ? pathInput.value.trim() : '') || currentBrowsePath;

    if (!path) {
        showToast('Please enter a path', 'warning');
        return;
    }

    // Update input and display to show current path
    if (pathInput) pathInput.value = path;
    const display = document.getElementById('file-path-display');
    if (display) display.textContent = path;
    currentBrowsePath = path;
    
    showLoading('Browsing files...');
    
    try {
        const response = await fetchAPI('/api/tools/execute', {
            method: 'POST',
            body: JSON.stringify({
                tool: 'list_files',
                dirpath: path
            })
        });
        
        hideLoading();
        
        // Handle error responses (directory not found, etc.)
        if (!response.success || !response.result || response.result.startsWith('❌')) {
            const errorMsg = response.result || response.error || 'Could not browse this directory';
            document.getElementById('file-list').innerHTML = `<p class="placeholder">📭 ${escapeHtml(errorMsg)}</p>`;
            showToast(errorMsg, 'warning');
            return;
        }
        
        const lines = response.result.split('\n').filter(f => f.trim());
        const filesList = document.getElementById('file-list');
        
        // Parse: skip header lines (✅, 📊), extract clean names from "📁 name/" and "📄 name  (size)"
        const items = [];
        for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith('✅') || trimmed.startsWith('📊') || !trimmed) continue;
            
            if (trimmed.startsWith('📁')) {
                // Directory: "📁 dirname/"
                const name = trimmed.replace(/^📁\s*/, '').replace(/\/\s*$/, '').trim();
                if (name) items.push({ name, isDir: true });
            } else if (trimmed.startsWith('📄')) {
                // File: "📄 filename  (size)"  
                const name = trimmed.replace(/^📄\s*/, '').replace(/\s+\([\d.]+[BKMG]+B?\)\s*$/, '').trim();
                if (name) items.push({ name, isDir: false });
            }
        }
        
        if (items.length === 0) {
            filesList.innerHTML = '<p class="placeholder">📭 No files found</p>';
            return;
        }
        
        // Add parent directory navigation
        let html = '';
        const parentPath = path.replace(/\/[^\/]+\/?$/, '') || '/';
        if (path !== '/') {
            html += `
                <div class="file-item" onclick="browsePath('${parentPath.replace(/'/g, "\\'")}')">
                    <span class="file-icon">⬆️</span>
                    <span>.. (parent directory)</span>
                </div>
            `;
        }
        
        html += items.map(item => {
            const fullPath = path.replace(/\/+$/, '') + '/' + item.name;
            const escapedPath = fullPath.replace(/'/g, "\\'");
            if (item.isDir) {
                return `
                    <div class="file-item" onclick="browsePath('${escapedPath}')">
                        <span class="file-icon">📁</span>
                        <span>${item.name}/</span>
                    </div>
                `;
            } else {
                return `
                    <div class="file-item" onclick="openBrowserFile('${escapedPath}')">
                        <span class="file-icon">📄</span>
                        <span>${item.name}</span>
                    </div>
                `;
            }
        }).join('');
        
        filesList.innerHTML = html;
        showToast(`✓ Found ${items.length} items`, 'success');
    } catch (error) {
        hideLoading();
        const isTimeout = error.message.includes('Failed to fetch') ||
                          error.message.includes('NetworkError') ||
                          error.message.includes('timeout');
        if (isTimeout) {
            document.getElementById('file-list').innerHTML = `<p class="placeholder">⏳ Request timed out — check your laptop</p>`;
            showToast('Check your laptop — browse request timed out', 'warning');
        } else {
            document.getElementById('file-list').innerHTML = `<p class="placeholder">❌ Error: ${escapeHtml(error.message)}</p>`;
            showToast(error.message, 'error');
        }
    }
}

function showResult(content) {
    document.getElementById('result-output').textContent = content;
    document.getElementById('tool-result').style.display = 'block';
    document.getElementById('tool-modal').classList.add('open');
    document.getElementById('modal-title').textContent = 'File Content';
}

function openBrowserFile(filepath) {
    // Read the file content directly instead of opening a modal
    showLoading('Reading file...');
    fetchAPI('/api/tools/execute', {
        method: 'POST',
        body: JSON.stringify({
            tool: 'read_file',
            filepath: filepath
        })
    }).then(response => {
        hideLoading();
        showResult(response.result || 'Empty file');
        showToast('✓ File opened', 'success');
    }).catch(error => {
        hideLoading();
        // Fallback: try open_file
        showToolModal('open_file', {
            filepath: { type: 'text', label: 'File Path', required: true }
        });
        setTimeout(() => {
            const input = document.querySelector('input[name="filepath"]');
            if (input) input.value = filepath;
        }, 100);
    });
}

function openFile(filepath) {
    showToolModal('open_file', {
        filepath: { type: 'text', label: 'File Path', required: true }
    });
    setTimeout(() => {
        const input = document.querySelector('input[name="filepath"]');
        if (input) input.value = filepath;
    }, 100);
}

// ==================== ADMIN PANEL ====================

async function loadAdminPanel() {
    if (!currentUser.is_superuser) {
        showToast('Admin access denied', 'error');
        return;
    }
    
    try {
        // Load pending requests
        const requestsResponse = await fetchAPI('/api/access/pending-requests');
        const pendingRequests = document.getElementById('pending-requests');
        
        if (!requestsResponse.pending_requests || requestsResponse.pending_requests.length === 0) {
            pendingRequests.innerHTML = '<p class="placeholder">✓ No pending requests</p>';
        } else {
            pendingRequests.innerHTML = requestsResponse.pending_requests.map(req => `
                <div class="request-item pending">
                    <p><strong>ID:</strong> ${req.id}</p>
                    <p><strong>Type:</strong> ${req.request_type}</p>
                    <p><strong>Created:</strong> ${new Date(req.created_at).toLocaleString()}</p>
                    ${req.qr_code_data ? `<img src="data:image/png;base64,${req.qr_code_data}" alt="QR Code" style="max-width: 150px; margin: 10px 0; border-radius: 8px;">` : ''}
                    <div class="request-actions">
                        <button class="btn-approve" onclick="approveRequest(${req.id})">✓ Approve</button>
                        <button class="btn-reject" onclick="rejectRequest(${req.id})">✕ Reject</button>
                    </div>
                </div>
            `).join('');
        }

        // Load users list
        const response = await fetchAPI('/api/auth/me');
        loadUsersList();
    } catch (error) {
        console.error('Error loading admin panel:', error);
        showToast('Error loading admin panel', 'error');
    }
}

async function approveRequest(requestId) {
    showLoading('Approving request...');
    
    try {
        await fetchAPI(`/api/access/approve/${requestId}`, { method: 'POST' });
        hideLoading();
        showToast('✓ Request approved!', 'success');
        loadAdminPanel();
    } catch (error) {
        hideLoading();
        showToast(error.message, 'error');
    }
}

async function rejectRequest(requestId) {
    showLoading('Rejecting request...');
    
    try {
        await fetchAPI(`/api/access/reject/${requestId}`, { method: 'POST' });
        hideLoading();
        showToast('✓ Request rejected!', 'success');
        loadAdminPanel();
    } catch (error) {
        hideLoading();
        showToast(error.message, 'error');
    }
}

async function loadUsersList() {
    try {
        // This would load from a users endpoint
        const usersList = document.getElementById('users-list');
        usersList.innerHTML = '<p class="placeholder">👤 Users management coming soon</p>';
    } catch (error) {
        console.error('Error loading users list:', error);
    }
}

// ==================== NGROK ====================

async function loadNgrokStatus() {
    try {
        const health = await fetch('/api/health').then(r => r.json());
        const box = document.getElementById('ngrok-box');
        const dis = document.getElementById('ngrok-disabled');
        const urlEl = document.getElementById('public-url');
        if (health.ngrok_enabled && health.public_url) {
            if (urlEl) urlEl.value = health.public_url;
            if (box) box.style.display = 'flex';
            if (dis) dis.style.display = 'none';
        } else {
            if (box) box.style.display = 'none';
            if (dis) dis.style.display = 'block';
        }
    } catch (error) {
        // silent — tunnel is optional
    }
}

function copyToClipboard() {
    const url = document.getElementById('public-url');
    const text = url.value;
    
    // Try modern clipboard API first
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('✓ URL copied to clipboard!', 'success');
        }).catch(() => {
            fallbackCopy(url);
        });
    } else {
        fallbackCopy(url);
    }
}

function fallbackCopy(element) {
    element.select();
    document.execCommand('copy');
    showToast('✓ URL copied to clipboard!', 'success');
}

// ==================== UTILITY FUNCTIONS ====================

async function fetchAPI(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
    }
    
    try {
        const response = await fetch(endpoint, {
            ...options,
            headers
        });
        
        // Handle 401 — expired or revoked token
        if (response.status === 401) {
            handleSessionExpiry();
            const error = new Error('Session expired');
            error.status = 401;
            throw error;
        }
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            const detail = error.detail;
            const msg = typeof detail === 'string' ? detail : (detail?.message || response.statusText);
            const errorMessage = new Error(msg);
            errorMessage.status = response.status;
            errorMessage.body = error;
            throw errorMessage;
        }
        
        return response.json();
    } catch (error) {
        if (error.status === 401) {
            // Re-throw to let caller handle 401
            throw error;
        }
        throw error;
    }
}

async function loadActivityLog() {
    try {
        const response = await fetchAPI('/api/tools/history');
        const logContainer = document.getElementById('activity-log');
        
        if (!response.history || response.history.length === 0) {
            logContainer.innerHTML = '<p class="placeholder">📭 No activity yet</p>';
            return;
        }
        
        logContainer.innerHTML = response.history.map((log, index) => {
            const timestamp = new Date(log.timestamp);
            const timeStr = timestamp.toLocaleString();
            const statusIcon = log.status === 'success' ? '✅' : '❌';
            const device = log.device || 'Unknown';
            const action = escapeHtml(log.action || '');
            const result = escapeHtml(log.result || '');
            
            return `
                <div class="activity-item ${escapeHtml(log.status)}" onclick="toggleActivityDetail(this)" role="button" tabindex="0">
                    <div class="activity-header">
                        <span class="activity-status">${statusIcon}</span>
                        <span class="activity-tool">${escapeHtml(log.tool)}</span>
                        <span class="activity-time">${timeStr}</span>
                        <span class="activity-expand">▶</span>
                    </div>
                    <div class="activity-body" style="display: none;">
                        <p class="activity-action"><strong>Action:</strong> ${action}</p>
                        <pre class="activity-result">${result}</pre>
                        <p class="activity-device">📱 ${escapeHtml(device)}</p>
                        <button class="btn-copy-sm" onclick="event.stopPropagation(); copyToClipboard('${result.replace(/'/g, "\\'")}')">📋 Copy Result</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        document.getElementById('activity-log').innerHTML = `
            <p class="placeholder">⚠️ Error loading activity: ${escapeHtml(error.message)}</p>
        `;
    }
}

function toggleActivityDetail(el) {
    const body = el.querySelector('.activity-body');
    const expand = el.querySelector('.activity-expand');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        expand.textContent = '▼';
        el.classList.add('expanded');
    } else {
        body.style.display = 'none';
        expand.textContent = '▶';
        el.classList.remove('expanded');
    }
}

async function loadExecutionLogs() {
    try {
        const response = await fetchAPI('/api/tools/execution-log?lines=200');
        const logsContainer = document.getElementById('execution-logs-display');
        
        if (response.status !== 'success' || !response.logs || response.logs.length === 0) {
            logsContainer.innerHTML = '<p class="placeholder">📭 No execution logs available yet</p>';
            return;
        }
        
        const logsHtml = `
            <div class="logs-header">
                <p class="logs-info">📊 Total Lines: ${response.total_lines} | Displayed: ${response.displayed_lines}</p>
                <p class="logs-path">📁 Log File: ${response.log_file}</p>
            </div>
            <div class="logs-content">
                <pre class="logs-text">${response.logs.map(line => escapeHtml(line)).join('\n')}</pre>
            </div>
        `;
        
        logsContainer.innerHTML = logsHtml;
    } catch (error) {
        document.getElementById('execution-logs-display').innerHTML = `
            <p class="placeholder">⚠️ Error loading execution logs: ${error.message}</p>
        `;
    }
}

function clearExecutionLogs() {
    // This just refreshes the view, clearing the cache display
    loadExecutionLogs();
}

async function loadConversations() {
    try {
        const response = await fetchAPI('/api/tools/conversations?limit=100');
        const conversationsContainer = document.getElementById('conversations-list');
        
        if (!response.conversations || response.conversations.length === 0) {
            conversationsContainer.innerHTML = '<p class="placeholder">💬 No conversations yet. Start asking Copilot!</p>';
            return;
        }
        
        conversationsContainer.innerHTML = response.conversations.map((conv, index) => {
            const timestamp = new Date(conv.timestamp);
            const timeStr = timestamp.toLocaleString();
            const statusIcon = conv.status === 'success' ? '✅' : '❌';
            
            return `
                <div class="conversation-item ${conv.status}">
                    <div class="conversation-header">
                        <span class="conversation-status">${statusIcon}</span>
                        <span class="conversation-time">${timeStr}</span>
                    </div>
                    <div class="conversation-body">
                        <div class="conversation-query">
                            <p class="query-label">📝 Your Question:</p>
                            <p class="query-text">${escapeHtml(conv.query)}</p>
                        </div>
                        <div class="conversation-response">
                            <p class="response-label">💬 Response:</p>
                            <div class="response-text">${escapeHtml(conv.response).replace(/\n/g, '<br>')}</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        document.getElementById('conversations-list').innerHTML = `
            <p class="placeholder">⚠️ Error loading conversations: ${error.message}</p>
        `;
    }
}

function clearConversations() {
    resetAllHistory();
}

// ==================== BUG TRACKER ====================

async function loadBugs() {
    try {
        const response = await fetchAPI('/api/bugs');
        const bugsContainer = document.getElementById('bugs-list');
        
        if (!response.bugs || response.bugs.length === 0) {
            bugsContainer.innerHTML = '<p class="placeholder">🎉 No bugs tracked yet!</p>';
            return;
        }
        
        bugsContainer.innerHTML = response.bugs.map(bug => {
            const severityColors = {
                'low': '#10b981',
                'medium': '#f59e0b',
                'high': '#f97316',
                'critical': '#ef4444'
            };
            const statusIcons = {
                'open': '🔴',
                'fixed': '✅',
                'reopened': '🔄',
                'in_progress': '🔧'
            };
            const sevColor = severityColors[bug.severity] || '#94a3b8';
            const statusIcon = statusIcons[bug.status] || '❓';
            
            return `
                <div class="bug-item bug-${bug.status}" data-bug-id="${bug.id}">
                    <div class="bug-header">
                        <span class="bug-id">#${bug.id}</span>
                        <span class="bug-status">${statusIcon} ${bug.status.toUpperCase()}</span>
                        <span class="bug-severity" style="color: ${sevColor}; border-color: ${sevColor}">
                            ${bug.severity.toUpperCase()}
                        </span>
                    </div>
                    <div class="bug-body">
                        <h4 class="bug-title">${escapeHtml(bug.title)}</h4>
                        <p class="bug-desc">${escapeHtml(bug.description)}</p>
                        ${bug.fix_details ? `<p class="bug-fix"><strong>Fix:</strong> ${escapeHtml(bug.fix_details)}</p>` : ''}
                        ${bug.root_cause ? `<p class="bug-cause"><strong>Root Cause:</strong> ${escapeHtml(bug.root_cause)}</p>` : ''}
                    </div>
                    <div class="bug-footer">
                        <span class="bug-occurrences">🔁 ${bug.occurrences}x reported</span>
                        <span class="bug-date">📅 ${bug.last_reported}</span>
                        ${bug.status === 'fixed' ? `<button onclick="reopenBug(${bug.id})" class="btn-reopen">🔄 Reopen</button>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        document.getElementById('bugs-list').innerHTML = `
            <p class="placeholder">⚠️ Error loading bugs: ${error.message}</p>
        `;
    }
}

function showReportBugForm() {
    const form = document.getElementById('bug-report-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function submitBugReport() {
    const title = document.getElementById('bug-title').value.trim();
    const desc = document.getElementById('bug-desc').value.trim();
    const severity = document.getElementById('bug-severity').value;
    
    if (!title) {
        showToast('Bug title is required', 'warning');
        return;
    }
    
    try {
        const response = await fetchAPI('/api/bugs/report', {
            method: 'POST',
            body: JSON.stringify({ title, description: desc, severity })
        });
        
        if (response.success) {
            showToast(`🐛 ${response.message}`, 'success');
            document.getElementById('bug-report-form').style.display = 'none';
            document.getElementById('bug-title').value = '';
            document.getElementById('bug-desc').value = '';
            loadBugs();
        } else {
            showToast(response.error || 'Failed to report bug', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

async function reopenBug(bugId) {
    try {
        const response = await fetchAPI('/api/bugs/report', {
            method: 'POST',
            body: JSON.stringify({ bug_id: bugId })
        });
        
        if (response.success) {
            showToast(`🔄 ${response.message}`, 'warning');
            loadBugs();
        } else {
            showToast(response.error || 'Failed to reopen bug', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function clearErrors() {
    document.querySelectorAll('.error-msg').forEach(el => {
        el.textContent = '';
    });
}

function closeModal() {
    document.getElementById('tool-modal').classList.remove('open');
}

// ==================== BILLING ====================

const PLAN_COLORS = {
    free:        '#6e6e6e',
    pro:         '#007acc',
    team:        '#9b59b6',
    self_hosted: '#27ae60',
};

const PLAN_FEATURES = {
    free:        ['View files only', '20 API calls / day', 'No Copilot / Commands'],
    pro:         ['All tools + Copilot Agent', '500 API calls / day', 'Full file editing'],
    team:        ['Unlimited API calls', 'Multi-user workspace', 'Priority support'],
    self_hosted: ['Your own server', 'Unlimited everything', 'One-time OR monthly'],
};

async function loadBillingStatus() {
    try {
        const data = await fetchAPI('/api/billing/status');
        billingStatus = data;

        // Update plan badge in header
        const badge = document.getElementById('plan-badge');
        if (badge) {
            badge.textContent = data.plan_label;
            badge.style.background = PLAN_COLORS[data.plan] || '#6e6e6e';
        }

        _renderBillingStatusBar(data);
        _renderPricingCards('pricing-cards', data.plan);

        // Show/hide manage billing section
        const manageSection = document.getElementById('manage-billing-section');
        if (manageSection) {
            manageSection.style.display = data.has_stripe_customer ? 'block' : 'none';
        }
    } catch (e) {
        // Non-critical — silently fail
    }
}

function _renderBillingStatusBar(data) {
    const bar = document.getElementById('billing-status-bar');
    if (!bar) return;
    bar.style.display = 'block';

    document.getElementById('bsb-plan-label').textContent = data.plan_label + ' Plan';

    const limit = data.daily_limit;
    const used = data.daily_api_calls;
    const callsLabel = document.getElementById('bsb-calls-label');
    const fill = document.getElementById('usage-fill');

    if (limit === -1) {
        callsLabel.textContent = `${used} calls today (unlimited)`;
        fill.style.width = '5%';
        fill.style.background = PLAN_COLORS[data.plan] || '#27ae60';
    } else {
        callsLabel.textContent = `${used} / ${limit} calls today`;
        const pct = Math.min((used / limit) * 100, 100);
        fill.style.width = pct + '%';
        fill.style.background = pct >= 90 ? '#e74c3c' : (PLAN_COLORS[data.plan] || '#007acc');
    }
}

function _renderPricingCards(containerId, currentPlan, compact = false) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const plans = [
        { key: 'free',        label: 'Free',        price: '$0',   sub: 'forever',     checkout: null },
        { key: 'pro',         label: 'Pro',         price: '$9',   sub: '/month',      checkout: 'pro' },
        { key: 'team',        label: 'Team',        price: '$29',  sub: '/month',      checkout: 'team' },
        { key: 'self_hosted', label: 'Self-Hosted', price: '$19',  sub: '/mo or $49 once', checkout: 'self_hosted_monthly' },
    ];

    container.innerHTML = plans.map(p => {
        const isCurrent = p.key === currentPlan;
        const features = PLAN_FEATURES[p.key] || [];
        const btnHtml = isCurrent
            ? `<button class="btn-plan-current" disabled>Current Plan</button>`
            : (p.checkout
                ? `<button class="btn-plan-upgrade" onclick="startCheckout('${p.checkout}')" style="background:${PLAN_COLORS[p.key]}">Upgrade</button>`
                : `<button class="btn-plan-current" disabled>Free</button>`);

        const lifetimeBadge = p.key === 'self_hosted'
            ? `<div class="plan-also">or <strong>$49</strong> one-time lifetime</div>` : '';

        return `
        <div class="plan-card ${isCurrent ? 'plan-card-active' : ''}" style="--plan-color:${PLAN_COLORS[p.key]}">
            <div class="plan-header">
                <span class="plan-name">${p.label}</span>
                <span class="plan-price">${p.price}<span class="plan-sub">${p.sub}</span></span>
            </div>
            ${lifetimeBadge}
            <ul class="plan-features">
                ${features.map(f => `<li>${f}</li>`).join('')}
            </ul>
            ${btnHtml}
        </div>`;
    }).join('');

    // For self-hosted, also show lifetime button
    const shCard = container.querySelector('.plan-card:last-child');
    if (shCard && currentPlan !== 'self_hosted') {
        const upgradeBtn = shCard.querySelector('.btn-plan-upgrade');
        if (upgradeBtn) {
            upgradeBtn.insertAdjacentHTML('afterend',
                `<button class="btn-plan-secondary" onclick="startCheckout('self_hosted_lifetime')" style="border-color:${PLAN_COLORS.self_hosted};color:${PLAN_COLORS.self_hosted}">Buy Lifetime ($49)</button>`
            );
        }
    }
}

async function startCheckout(planKey) {
    showLoading('Redirecting to checkout...');
    try {
        const data = await fetchAPI('/api/billing/checkout', {
            method: 'POST',
            body: JSON.stringify({ plan: planKey }),
        });
        hideLoading();
        if (data.checkout_url) {
            window.location.href = data.checkout_url;
        }
    } catch (e) {
        hideLoading();
        showToast(e.message || 'Checkout failed', 'error');
    }
}

async function activateLicense() {
    const input = document.getElementById('license-key-input');
    const statusEl = document.getElementById('license-status');
    const key = input ? input.value.trim() : '';

    if (!key) {
        if (statusEl) statusEl.textContent = 'Please enter a license key.';
        return;
    }

    showLoading('Activating license...');
    try {
        const data = await fetchAPI('/api/billing/validate-license', {
            method: 'POST',
            body: JSON.stringify({ license_key: key }),
        });
        hideLoading();
        if (statusEl) statusEl.textContent = '';
        if (input) input.value = '';
        showToast('License activated! Welcome to Self-Hosted plan.', 'success', 4000);
        await loadBillingStatus();
    } catch (e) {
        hideLoading();
        if (statusEl) statusEl.textContent = e.message || 'Activation failed.';
        showToast(e.message || 'Activation failed', 'error');
    }
}

async function openBillingPortal() {
    showLoading('Opening billing portal...');
    try {
        const data = await fetchAPI('/api/billing/portal');
        hideLoading();
        window.open(data.portal_url, '_blank');
    } catch (e) {
        hideLoading();
        showToast(e.message || 'Could not open billing portal', 'error');
    }
}

function showUpgradeModal(detail) {
    const modal = document.getElementById('upgrade-modal');
    const reason = document.getElementById('upgrade-reason');
    if (!modal) return;

    const msg = typeof detail === 'string' ? detail : (detail?.message || 'Upgrade to continue.');
    if (reason) reason.textContent = msg;

    const currentPlan = billingStatus?.plan || 'free';
    _renderPricingCards('upgrade-pricing-cards', currentPlan, true);

    modal.style.display = 'flex';
}

function closeUpgradeModal() {
    const modal = document.getElementById('upgrade-modal');
    if (modal) modal.style.display = 'none';
}

// ==================== FORGOT / RESET PASSWORD ====================

function showForgotPassword(e) {
    if (e) e.preventDefault();
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const ft = document.getElementById('forgot-tab');
    if (ft) { ft.style.display = 'block'; ft.classList.add('active'); }
}

function showLogin(e) {
    if (e) e.preventDefault();
    const ft = document.getElementById('forgot-tab');
    if (ft) { ft.style.display = 'none'; ft.classList.remove('active'); }
    switchTab('login');
}

async function sendForgotPassword() {
    const email = document.getElementById('forgot-email').value.trim();
    const statusEl = document.getElementById('forgot-status');
    if (!email) { statusEl.textContent = 'Please enter your email.'; return; }

    statusEl.textContent = 'Sending...';
    try {
        const res = await fetch('/api/auth/forgot-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email }),
        });
        const data = await res.json();
        statusEl.textContent = data.message || 'Reset link sent.';
    } catch (e) {
        statusEl.textContent = 'Something went wrong. Try again.';
    }
}

function closeResetModal() {
    document.getElementById('reset-modal').style.display = 'none';
}

async function submitResetPassword() {
    const pwd = document.getElementById('reset-new-password').value;
    const confirm = document.getElementById('reset-confirm-password').value;
    const statusEl = document.getElementById('reset-status');
    const token = new URLSearchParams(location.search).get('reset_token');

    if (pwd !== confirm) { statusEl.textContent = 'Passwords do not match.'; return; }
    if (pwd.length < 8) { statusEl.textContent = 'Password must be at least 8 characters.'; return; }

    statusEl.textContent = 'Saving...';
    try {
        const res = await fetch('/api/auth/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, new_password: pwd }),
        });
        const data = await res.json();
        if (res.ok) {
            statusEl.textContent = data.message;
            // Clean URL, close modal, show login after 2s
            setTimeout(() => {
                history.replaceState({}, '', '/');
                closeResetModal();
                switchTab('login');
            }, 2000);
        } else {
            statusEl.textContent = data.detail || 'Reset failed.';
        }
    } catch (e) {
        statusEl.textContent = 'Something went wrong.';
    }
}

// On page load, check for reset_token in URL
(function checkResetToken() {
    const token = new URLSearchParams(location.search).get('reset_token');
    if (token) {
        window.addEventListener('DOMContentLoaded', () => {
            const modal = document.getElementById('reset-modal');
            if (modal) modal.style.display = 'flex';
        });
    }
})();

// ==================== ONBOARDING WIZARD ====================

function shouldShowOnboarding() {
    return !localStorage.getItem('onboarding_done');
}

function showOnboarding() {
    const modal = document.getElementById('onboarding-modal');
    if (modal) modal.style.display = 'flex';
}

function _obSetDot(step) {
    document.querySelectorAll('.ob-dot').forEach((d, i) => {
        d.classList.toggle('ob-dot-active', i + 1 === step);
    });
}

async function obNextStep(step) {
    if (step === 1) {
        const ws = document.getElementById('ob-workspace').value.trim();
        if (ws) {
            try {
                await fetchAPI('/api/settings/workspace', {
                    method: 'POST',
                    body: JSON.stringify({ workspace_path: ws }),
                });
            } catch (e) { /* non-blocking */ }
        }
    } else if (step === 2) {
        const tok = document.getElementById('ob-github-token').value.trim();
        if (tok) {
            try {
                await fetchAPI('/api/settings/github-token', {
                    method: 'POST',
                    body: JSON.stringify({ token: tok }),
                });
            } catch (e) { /* non-blocking */ }
        }
    }

    document.getElementById(`ob-step-${step}`).style.display = 'none';
    document.getElementById(`ob-step-${step + 1}`).style.display = 'block';
    _obSetDot(step + 1);
}

function obSkipStep(step) {
    document.getElementById(`ob-step-${step}`).style.display = 'none';
    document.getElementById(`ob-step-${step + 1}`).style.display = 'block';
    _obSetDot(step + 1);
}

function obFinish() {
    localStorage.setItem('onboarding_done', '1');
    document.getElementById('onboarding-modal').style.display = 'none';
    loadBillingStatus();
    checkGitHubToken();
}

// ==================== VSCARS NEW FEATURES v11.0 ====================

// ==================== FAB (Floating Action Button) ====================

let _fabOpen = false;

function toggleFAB() {
    _fabOpen = !_fabOpen;
    const btn = document.getElementById('fab-btn');
    const sheet = document.getElementById('fab-sheet');
    if (btn) btn.classList.toggle('open', _fabOpen);
    if (sheet) sheet.classList.toggle('open', _fabOpen);
}

function closeFAB() {
    _fabOpen = false;
    const btn = document.getElementById('fab-btn');
    const sheet = document.getElementById('fab-sheet');
    if (btn) btn.classList.remove('open');
    if (sheet) sheet.classList.remove('open');
}

// Close FAB on outside click
document.addEventListener('click', function(e) {
    if (_fabOpen && !e.target.closest('#fab-btn') && !e.target.closest('#fab-sheet')) {
        closeFAB();
    }
});

function quickIdeaCapture() {
    closeFAB();
    switchView('ideas');
    setTimeout(() => {
        const ta = document.getElementById('idea-body');
        if (ta) ta.focus();
    }, 150);
}

// ==================== MORNING BRIEF (Dashboard widgets) ====================

async function loadMorningBrief() {
    try {
        const data = await fetchAPI('/api/dashboard/brief');
        const el = (id) => document.getElementById(id);
        if (el('brief-commands')) el('brief-commands').textContent = data.commands_today ?? '0';
        if (el('brief-ideas'))    el('brief-ideas').textContent    = data.ideas_pending ?? '0';
        const planLabels = {free:'Free',pro:'Pro',team:'Team',self_hosted:'Self-Hosted'};
        if (el('brief-plan')) el('brief-plan').textContent = planLabels[data.plan] || (data.plan || 'Free');
        if (el('dash-git-status')) el('dash-git-status').textContent = data.git_status || '(no git repo)';

        // workflows count from cache if available
        const cachedWf = JSON.parse(localStorage.getItem('vscars_workflows') || '[]');
        if (el('brief-workflows')) el('brief-workflows').textContent = cachedWf.length;
    } catch (e) {
        // non-fatal — widgets just stay at '—'
    }
}

async function loadDashboardGit() {
    const el = document.getElementById('dash-git-status');
    if (!el) return;
    el.textContent = 'Loading...';
    try {
        const data = await fetchAPI('/api/git/status');
        el.textContent = data.output || '(clean)';
    } catch (e) {
        el.textContent = 'Could not load git status';
    }
}

// ==================== IDEA VAULT ====================

let _allIdeas = [];
let _ideaFilter = 'all';

async function loadIdeas() {
    try {
        const data = await fetchAPI('/api/ideas');
        _allIdeas = data.ideas || [];
        renderIdeas();
    } catch (e) {
        document.getElementById('ideas-list').innerHTML = '<p class="placeholder">Could not load ideas</p>';
    }
}

function filterIdeas(type) {
    _ideaFilter = type;
    document.querySelectorAll('[id^="idea-filter-"]').forEach(el => el.classList.remove('active'));
    const btn = document.getElementById('idea-filter-' + type);
    if (btn) btn.classList.add('active');
    renderIdeas();
}

function renderIdeas() {
    const list = document.getElementById('ideas-list');
    if (!list) return;
    let ideas = _allIdeas;
    if (_ideaFilter === 'pending') ideas = ideas.filter(i => !i.is_done);
    if (_ideaFilter === 'done')    ideas = ideas.filter(i =>  i.is_done);
    if (!ideas.length) {
        list.innerHTML = '<p class="placeholder">&#128161; ' + (_ideaFilter === 'all' ? 'No ideas yet. Capture your first one above.' : 'No ideas in this filter.') + '</p>';
        return;
    }
    list.innerHTML = ideas.map(idea => {
        const tags = idea.tags ? idea.tags.split(',').map(t => `<span class="idea-tag">${escapeHtml(t.trim())}</span>`).join('') : '';
        const timeStr = new Date(idea.created_at).toLocaleDateString(undefined, { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
        return `
        <div class="idea-card ${idea.is_done ? 'done' : ''}" id="idea-card-${idea.id}">
            <div class="idea-card-head">
                <span class="idea-card-title">${idea.title ? escapeHtml(idea.title) : '&#128161; Idea'}</span>
                <div class="idea-actions">
                    <button onclick="toggleIdeaDone(${idea.id}, ${!idea.is_done})" class="btn-sm" title="${idea.is_done ? 'Mark pending' : 'Mark shipped'}">${idea.is_done ? '↩' : '✓'}</button>
                    <button onclick="deleteIdea(${idea.id})" class="btn-sm btn-danger" title="Delete">×</button>
                </div>
            </div>
            <div class="idea-card-body">${escapeHtml(idea.body)}</div>
            <div class="idea-card-meta">
                <span class="idea-card-time">${timeStr}</span>
                ${tags}
            </div>
        </div>`;
    }).join('');
}

async function saveIdea() {
    const body  = document.getElementById('idea-body').value.trim();
    const title = document.getElementById('idea-title').value.trim();
    const tags  = document.getElementById('idea-tags').value.trim();
    if (!body) { showToast('Write something first!', 'warning'); return; }
    try {
        const idea = await fetchAPI('/api/ideas', {
            method: 'POST',
            body: JSON.stringify({ body, title: title || null, tags: tags || null })
        });
        _allIdeas.unshift(idea);
        renderIdeas();
        document.getElementById('idea-body').value = '';
        document.getElementById('idea-title').value = '';
        document.getElementById('idea-tags').value = '';
        showToast('Idea saved!', 'success');
        // Update brief count
        const el = document.getElementById('brief-ideas');
        if (el) el.textContent = _allIdeas.filter(i => !i.is_done).length;
    } catch (e) {
        showToast('Failed to save idea: ' + e.message, 'error');
    }
}

async function toggleIdeaDone(id, isDone) {
    try {
        await fetchAPI(`/api/ideas/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({ is_done: isDone })
        });
        const idx = _allIdeas.findIndex(i => i.id === id);
        if (idx >= 0) _allIdeas[idx].is_done = isDone;
        renderIdeas();
        showToast(isDone ? 'Marked as shipped ✓' : 'Back to pending', 'success');
    } catch (e) {
        showToast('Update failed', 'error');
    }
}

async function deleteIdea(id) {
    if (!confirm('Delete this idea?')) return;
    try {
        await fetchAPI(`/api/ideas/${id}`, { method: 'DELETE' });
        _allIdeas = _allIdeas.filter(i => i.id !== id);
        renderIdeas();
        showToast('Idea deleted', 'info');
    } catch (e) {
        showToast('Delete failed', 'error');
    }
}

// ==================== GIT PANEL ====================

async function loadGitPanel() {
    const out = document.getElementById('git-status-output');
    if (out) out.textContent = 'Loading...';
    try {
        const data = await fetchAPI('/api/git/status');
        if (out) out.textContent = data.output || '(clean)';
    } catch (e) {
        if (out) out.textContent = 'Could not load git status: ' + e.message;
    }
}

async function loadGitDiff(staged = false) {
    const out = document.getElementById('git-diff-output');
    if (out) out.textContent = 'Loading...';
    try {
        const data = await fetchAPI(`/api/git/diff?staged=${staged}`);
        if (out) out.textContent = data.output || '(no changes)';
    } catch (e) {
        if (out) out.textContent = 'Error: ' + e.message;
    }
}

async function loadGitLog() {
    const out = document.getElementById('git-log-output');
    if (out) out.textContent = 'Loading...';
    try {
        const data = await fetchAPI('/api/git/log?n=15');
        if (out) out.textContent = data.output || '(no commits)';
    } catch (e) {
        if (out) out.textContent = 'Error: ' + e.message;
    }
}

async function gitStageAll() {
    try {
        await fetchAPI('/api/git/stage', {
            method: 'POST',
            body: JSON.stringify({ files: ['.'] })
        });
        showToast('Staged all changes', 'success');
        loadGitPanel();
    } catch (e) {
        showToast('Stage failed: ' + e.message, 'error');
    }
}

async function generateAICommitMsg() {
    const btn = document.querySelector('.commit-ai-btn');
    if (btn) { btn.textContent = '⏳ Generating...'; btn.disabled = true; }
    try {
        const data = await fetchAPI('/api/git/ai-commit-message', {
            method: 'POST',
            body: JSON.stringify({})
        });
        if (data.output) {
            const ta = document.getElementById('commit-message');
            if (ta) ta.value = data.success ? data.output : '';
            if (data.success) showToast('AI commit message ready!', 'success');
            else showToast(data.output, 'warning');
        }
    } catch (e) {
        showToast('AI message failed: ' + e.message, 'error');
    } finally {
        if (btn) { btn.textContent = '🤖 AI'; btn.disabled = false; }
    }
}

async function doCommit() {
    const msg = (document.getElementById('commit-message')?.value || '').trim();
    if (!msg) { showToast('Enter a commit message first', 'warning'); return; }
    showLoading('Committing...');
    try {
        const data = await fetchAPI('/api/git/commit', {
            method: 'POST',
            body: JSON.stringify({ message: msg })
        });
        hideLoading();
        if (data.success) {
            showToast('Committed!', 'success');
            document.getElementById('commit-message').value = '';
            loadGitPanel();
        } else {
            showToast('Commit failed: ' + data.output, 'error');
        }
    } catch (e) {
        hideLoading();
        showToast('Commit error: ' + e.message, 'error');
    }
}

async function doPush() {
    showLoading('Pushing...');
    try {
        const data = await fetchAPI('/api/git/push', {
            method: 'POST',
            body: JSON.stringify({})
        });
        hideLoading();
        if (data.success) showToast('Pushed!', 'success');
        else showToast('Push failed: ' + data.output, 'error');
    } catch (e) {
        hideLoading();
        showToast('Push error: ' + e.message, 'error');
    }
}

async function doCommitAndPush() {
    const msg = (document.getElementById('commit-message')?.value || '').trim();
    if (!msg) { showToast('Enter a commit message first', 'warning'); return; }
    showLoading('Committing & pushing...');
    try {
        const commitData = await fetchAPI('/api/git/commit', {
            method: 'POST',
            body: JSON.stringify({ message: msg })
        });
        if (!commitData.success) { hideLoading(); showToast('Commit failed: ' + commitData.output, 'error'); return; }
        const pushData = await fetchAPI('/api/git/push', {
            method: 'POST',
            body: JSON.stringify({})
        });
        hideLoading();
        if (pushData.success) {
            showToast('Committed & pushed! 🚀', 'success');
            document.getElementById('commit-message').value = '';
            loadGitPanel();
        } else {
            showToast('Committed but push failed: ' + pushData.output, 'warning');
        }
    } catch (e) {
        hideLoading();
        showToast('Error: ' + e.message, 'error');
    }
}

// ==================== SAVED WORKFLOWS ====================

let _workflows = [];
let _selectedIcon = '⚡';

function selectIcon(el) {
    document.querySelectorAll('.icon-opt').forEach(o => o.classList.remove('selected'));
    el.classList.add('selected');
    _selectedIcon = el.dataset.icon;
}

function toggleAddWorkflow() {
    const form = document.getElementById('add-workflow-form');
    if (!form) return;
    const isOpen = form.classList.contains('open');
    form.classList.toggle('open', !isOpen);
    const btn = document.getElementById('add-wf-btn');
    if (btn) btn.textContent = isOpen ? '+ New Workflow' : '✕ Cancel';
}

async function loadWorkflows() {
    try {
        const data = await fetchAPI('/api/workflows');
        _workflows = data.workflows || [];
        localStorage.setItem('vscars_workflows', JSON.stringify(_workflows));
        renderWorkflows();
        const el = document.getElementById('brief-workflows');
        if (el) el.textContent = _workflows.length;
    } catch (e) {
        document.getElementById('workflow-grid').innerHTML = '<p class="placeholder">Could not load workflows</p>';
    }
}

function renderWorkflows() {
    const grid = document.getElementById('workflow-grid');
    if (!grid) return;
    if (!_workflows.length) {
        grid.innerHTML = '<p class="placeholder">&#128640; No workflows yet.<br>Save your most-used commands as one-tap shortcuts.</p>';
        return;
    }
    grid.innerHTML = _workflows.map(wf => `
        <div class="workflow-card" id="wf-card-${wf.id}">
            <button class="workflow-del-btn" onclick="deleteWorkflow(event, ${wf.id})" title="Delete">×</button>
            <div class="workflow-icon">${escapeHtml(wf.icon || '⚡')}</div>
            <div class="workflow-name">${escapeHtml(wf.name)}</div>
            <div class="workflow-cmd" title="${escapeHtml(wf.command)}">${escapeHtml(wf.command)}</div>
            <div class="workflow-meta">
                <span>${wf.run_count || 0} runs</span>
                <span>${wf.last_run_at ? new Date(wf.last_run_at).toLocaleDateString() : 'never'}</span>
            </div>
            <button onclick="runWorkflow(${wf.id})" class="workflow-run-btn">&#9654; Run</button>
        </div>
    `).join('');
}

async function saveWorkflow() {
    const name    = document.getElementById('wf-name')?.value.trim();
    const command = document.getElementById('wf-command')?.value.trim();
    const cwd     = document.getElementById('wf-cwd')?.value.trim();
    if (!name || !command) { showToast('Name and command are required', 'warning'); return; }
    try {
        const wf = await fetchAPI('/api/workflows', {
            method: 'POST',
            body: JSON.stringify({ name, command, cwd: cwd || null, icon: _selectedIcon })
        });
        _workflows.unshift(wf);
        localStorage.setItem('vscars_workflows', JSON.stringify(_workflows));
        renderWorkflows();
        toggleAddWorkflow();
        // clear form
        ['wf-name','wf-command','wf-cwd'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        showToast('Workflow saved!', 'success');
    } catch (e) {
        showToast('Save failed: ' + e.message, 'error');
    }
}

async function runWorkflow(id) {
    const wf = _workflows.find(w => w.id === id);
    if (!wf) return;
    showLoading(`Running: ${wf.name}...`);
    try {
        const data = await fetchAPI(`/api/workflows/${id}/run`, { method: 'POST' });
        hideLoading();
        const output = data.result || data.output || data.error || '(no output)';
        document.getElementById('result-output').textContent = output;
        document.getElementById('tool-result').style.display = 'block';
        document.getElementById('tool-modal').classList.add('open');
        document.getElementById('modal-title').textContent = `⚡ ${wf.name}`;
        // update run count locally
        const idx = _workflows.findIndex(w => w.id === id);
        if (idx >= 0) { _workflows[idx].run_count = (wf.run_count || 0) + 1; renderWorkflows(); }
        showToast(`${wf.name} finished`, data.success !== false ? 'success' : 'warning');
    } catch (e) {
        hideLoading();
        showToast('Workflow error: ' + e.message, 'error');
    }
}

async function deleteWorkflow(e, id) {
    e.stopPropagation();
    if (!confirm('Delete this workflow?')) return;
    try {
        await fetchAPI(`/api/workflows/${id}`, { method: 'DELETE' });
        _workflows = _workflows.filter(w => w.id !== id);
        localStorage.setItem('vscars_workflows', JSON.stringify(_workflows));
        renderWorkflows();
        showToast('Workflow deleted', 'info');
    } catch (e) {
        showToast('Delete failed', 'error');
    }
}

// ==================== SESSIONS ====================

async function loadSessions() {
    const el = document.getElementById('sessions-list');
    if (!el) return;
    el.innerHTML = '<p class="muted sm">Loading...</p>';
    try {
        const data = await fetchAPI('/api/auth/sessions');
        const sessions = data.sessions || [];
        if (!sessions.length) { el.innerHTML = '<p class="muted sm">No active sessions</p>'; return; }
        el.innerHTML = sessions.map(s => {
            const ua = s.device_info ? s.device_info.substring(0, 60) : 'Unknown device';
            const lastSeen = new Date(s.last_seen_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            return `
            <div class="session-item">
                <div>
                    <div class="session-device">${escapeHtml(ua)}</div>
                    <div class="session-meta">${escapeHtml(s.ip_address || '?')} · Last seen ${lastSeen}</div>
                </div>
                <button onclick="revokeSession(${s.id})" class="btn-sm btn-danger" title="Revoke">Revoke</button>
            </div>`;
        }).join('');
    } catch (e) {
        el.innerHTML = '<p class="muted sm">Could not load sessions</p>';
    }
}

async function revokeSession(id) {
    if (!confirm('Revoke this session? That device will be signed out.')) return;
    try {
        await fetchAPI(`/api/auth/sessions/${id}`, { method: 'DELETE' });
        showToast('Session revoked', 'success');
        loadSessions();
    } catch (e) {
        showToast('Revoke failed', 'error');
    }
}

// ==================== PATCH: extend switchView for new views ====================

const _origSwitchView = switchView;
switchView = function(viewName) {
    _origSwitchView(viewName);
    if (viewName === 'ideas')     { loadIdeas(); }
    if (viewName === 'git')       { loadGitPanel(); }
    if (viewName === 'workflows') { loadWorkflows(); }
    if (viewName === 'settings')  { loadSessions(); }
};

// ==================== PATCH: extend showMainView for new widgets ====================

const _origShowMainView = showMainView;
showMainView = function() {
    _origShowMainView();
    loadMorningBrief();
    loadDashboardGit();
};

// ====================================================================================
// VSCARS v11.2 — ANIMATION ENGINE
// ====================================================================================

// ---- CANVAS PARTICLE SYSTEM ----
(function initParticles() {
    const canvas = document.getElementById('vscars-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let W, H, particles = [], raf;
    const COUNT = 55;
    const COLORS = ['rgba(124,58,237,', 'rgba(6,182,212,', 'rgba(139,92,246,'];

    function resize() {
        W = canvas.width  = window.innerWidth;
        H = canvas.height = window.innerHeight;
    }

    function rand(min, max) { return min + Math.random() * (max - min); }

    function makeParticle() {
        return {
            x: rand(0, W || window.innerWidth),
            y: rand(0, H || window.innerHeight),
            r: rand(1, 2.8),
            vx: rand(-0.18, 0.18),
            vy: rand(-0.22, -0.06),
            alpha: rand(0.15, 0.55),
            color: COLORS[Math.floor(Math.random() * COLORS.length)],
            life: rand(0, 1),
            maxLife: rand(80, 220),
        };
    }

    function init() {
        resize();
        particles = Array.from({ length: COUNT }, makeParticle);
        window.addEventListener('resize', resize);
        loop();
    }

    function loop() {
        ctx.clearRect(0, 0, W, H);
        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];
            p.life++;
            if (p.life > p.maxLife) { particles[i] = makeParticle(); continue; }
            const fade = p.life < 30 ? p.life / 30 : p.life > p.maxLife - 30 ? (p.maxLife - p.life) / 30 : 1;
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = p.color + (p.alpha * fade) + ')';
            ctx.fill();
            p.x += p.vx;
            p.y += p.vy;
            if (p.y < -10) { p.y = H + 10; p.x = rand(0, W); }
            if (p.x < -10) p.x = W + 10;
            if (p.x > W + 10) p.x = -10;
        }
        // subtle connecting lines
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 90) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = 'rgba(124,58,237,' + (0.06 * (1 - dist / 90)) + ')';
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }
        raf = requestAnimationFrame(loop);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

// ---- LIVE CLOCK + HERO GREETING ----
function updateHeroClock() {
    const el = document.getElementById('hero-clock');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function setHeroGreeting() {
    const greetEl = document.getElementById('hero-greeting');
    const nameEl  = document.getElementById('hero-name');
    if (!greetEl) return;
    const h = new Date().getHours();
    greetEl.textContent = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
    // Prefer live currentUser, fall back to cached
    const name = (currentUser && currentUser.username)
        || window._currentUser
        || JSON.parse(localStorage.getItem('currentUser') || '{}').username
        || '';
    if (nameEl) nameEl.textContent = name;
}

function initHero() {
    setHeroGreeting();
    updateHeroClock();
    setInterval(updateHeroClock, 10000);
    // dot — green when authenticated
    const dot = document.getElementById('conn-dot');
    const lbl = document.getElementById('conn-label');
    if (dot) {
        const ok = !!localStorage.getItem('authToken');
        dot.style.background = ok ? 'var(--ok)' : 'var(--err)';
        dot.style.boxShadow   = ok ? '0 0 6px var(--ok)' : 'none';
        if (lbl) lbl.textContent = ok ? 'Active' : 'Offline';
    }
}

// ---- RIPPLE EFFECT ----
function attachRipple(el) {
    el.addEventListener('click', function(e) {
        const rect = el.getBoundingClientRect();
        const wave = document.createElement('span');
        wave.className = 'ripple-wave';
        wave.style.cssText = `left:${e.clientX - rect.left}px;top:${e.clientY - rect.top}px`;
        el.appendChild(wave);
        wave.addEventListener('animationend', () => wave.remove());
    });
}

function attachRippleToAll() {
    document.querySelectorAll('.action-card,.btn-primary,.btn-secondary,.nav-item,.brief-card')
        .forEach(el => {
            if (!el.dataset.ripple) {
                el.dataset.ripple = '1';
                el.style.position = 'relative';
                el.style.overflow = 'hidden';
                attachRipple(el);
            }
        });
}

// ---- STAGGER CARD ENTRANCE ----
function triggerStagger(containerSelector) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    container.classList.add('stagger');
    const children = container.children;
    for (let i = 0; i < children.length; i++) {
        const child = children[i];
        child.style.animationDelay = (i * 0.07) + 's';
        child.style.animation = 'card-rise 0.55s cubic-bezier(0.22,1,0.36,1) both';
    }
}

// ---- VIEW TRANSITION ANIMATION ----
function animateViewIn(viewEl) {
    if (!viewEl) return;
    viewEl.style.animation = 'none';
    viewEl.offsetHeight; // reflow
    viewEl.style.animation = 'view-enter 0.38s cubic-bezier(0.22,1,0.36,1) both';
}

// ---- COUNTER ROLL-UP ANIMATION ----
function animateCounter(el, target) {
    if (!el || isNaN(parseInt(target))) {
        if (el) el.textContent = target;
        return;
    }
    const end = parseInt(target);
    const dur = 800;
    const start = performance.now();
    function tick(now) {
        const t = Math.min((now - start) / dur, 1);
        const ease = 1 - Math.pow(1 - t, 3);
        el.textContent = Math.round(ease * end);
        if (t < 1) requestAnimationFrame(tick);
        else el.textContent = target;
    }
    requestAnimationFrame(tick);
}

// ---- SKELETON LOADER HELPERS ----
function showSkeleton(containerId, rows = 3) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = Array.from({ length: rows }, () =>
        `<div class="skeleton" style="height:48px;border-radius:10px;margin-bottom:10px"></div>`
    ).join('');
}

// ---- PATCH: view transitions + stagger on switch ----
(function patchViewAnimations() {
    const _prev = switchView;
    switchView = function(viewName) {
        _prev(viewName);
        const el = document.getElementById(viewName + '-view');
        animateViewIn(el);
        // stagger child cards per view
        const staggerMap = {
            dashboard: '.action-grid',
            ideas: '#ideas-list',
            workflows: '#workflows-list',
            git: '.git-panel-inner',
        };
        if (staggerMap[viewName]) {
            setTimeout(() => triggerStagger(staggerMap[viewName]), 80);
        }
        setTimeout(attachRippleToAll, 120);
    };
})();

// ---- PATCH: init hero + ripples on login ----
(function patchShowMainViewAnimations() {
    const _prev = showMainView;
    showMainView = function() {
        _prev();
        initHero();
        setTimeout(attachRippleToAll, 200);
        setTimeout(() => triggerStagger('.morning-brief'), 150);
        setTimeout(() => triggerStagger('.action-grid'), 250);
        // store username for greeting
        try {
            const raw = localStorage.getItem('token');
            if (raw) {
                const payload = JSON.parse(atob(raw.split('.')[1]));
                window._currentUser = payload.sub || '';
                setHeroGreeting();
                const nameEl = document.getElementById('hero-name');
                if (nameEl) nameEl.textContent = window._currentUser;
            }
        } catch(e) {}
    };
})();

// ---- PATCH: counter animations in morning brief ----
(function patchMorningBrief() {
    const _prev = loadMorningBrief;
    loadMorningBrief = async function() {
        await _prev();
        // after brief loads, animate the numbers
        requestAnimationFrame(() => {
            ['brief-commands','brief-ideas','brief-workflows'].forEach(id => {
                const el = document.getElementById(id);
                if (el && el.textContent.trim() !== '—') {
                    animateCounter(el, el.textContent.trim());
                }
            });
        });
    };
})();


// ---- QUICK CAPTURE (aside panel) ----
async function quickCaptureIdea() {
    const ta = document.getElementById('quick-idea-text');
    if (!ta) return;
    const body = ta.value.trim();
    if (!body) return;
    try {
        const r = await apiFetch('/api/ideas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body, title: '', tags: '' }) });
        if (r.ok) {
            ta.value = '';
            showToast('Idea saved!', 'success');
            loadMorningBrief();
        }
    } catch(e) { showToast('Failed to save idea', 'error'); }
}

// ═══════════════════════════════════════════════════════════
// VSCARS v13.0 — UI BRIDGE PATCHES
// ═══════════════════════════════════════════════════════════

// ── TAB LABEL UPDATE ────────────────────────────────────────
const VIEW_LABELS = {
  dashboard:'Home', ideas:'Idea Vault', git:'Git Panel',
  tools:'Terminal', workflows:'Workflows', 'file-browser':'Files',
  conversations:'AI Chat', activity:'Logs', settings:'Settings',
  billing:'Plan & Billing', admin:'Admin',
};
(function patchSwitchViewV13() {
  const _prev = switchView;
  switchView = function(viewName) {
    _prev(viewName);
    const lbl = document.getElementById('active-tab-label');
    if (lbl) lbl.textContent = VIEW_LABELS[viewName] || viewName;
  };
})();

// ── AVATAR + STATUS BAR UPDATE ──────────────────────────────
(function patchShowMainViewV13() {
  const _prev = showMainView;
  showMainView = function() {
    _prev();
    // Avatar initial
    const av = document.getElementById('actbar-avatar');
    if (av && window.currentUser) {
      av.textContent = (currentUser.username || '?')[0].toUpperCase();
    }
    // Status bar plan
    const sbPlan = document.getElementById('sb-plan');
    if (sbPlan && window.currentUser) sbPlan.textContent = currentUser.plan || 'Free';
  };
})();

// ── WORKSPACE → STATUS BAR SYNC ─────────────────────────────
(function patchWorkspaceSync() {
  const origSave = typeof saveWorkspace === 'function' ? saveWorkspace : null;
  function syncSbWorkspace() {
    const inp = document.getElementById('workspace-path-input');
    const sb  = document.getElementById('sb-workspace');
    if (inp && sb && inp.value) sb.textContent = inp.value;
  }
  setInterval(syncSbWorkspace, 3000);
})();

// ── GIT BRANCH → STATUS STRIP ───────────────────────────────
(function patchGitBranchStrip() {
  const _origLoad = loadDashboardGit;
  loadDashboardGit = async function() {
    await _origLoad();
    const pre = document.getElementById('dash-git-status');
    if (!pre) return;
    const match = pre.textContent.match(/## ([^\s.]+)/);
    const branchEl = document.getElementById('dash-branch');
    if (branchEl && match) branchEl.textContent = match[1];
  };
})();

// ── LIVE CLOCK ───────────────────────────────────────────────
(function liveClock() {
  function tick() {
    const el = document.getElementById('hero-clock');
    if (!el) return;
    const n = new Date();
    el.textContent = n.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
  }
  tick();
  setInterval(tick, 10000);
})();

// ── GREETING ────────────────────────────────────────────────
(function setGreeting() {
  function apply() {
    const el = document.getElementById('hero-greeting');
    if (!el) return;
    const h = new Date().getHours();
    el.textContent = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  }
  apply();
  const _prev = showMainView;
  showMainView = function() { _prev(); apply(); };
})();

// ── QUICK CAPTURE (aside) ────────────────────────────────────
async function quickCaptureIdea() {
  const ta = document.getElementById('quick-idea-text');
  if (!ta || !ta.value.trim()) return;
  try {
    const r = await apiFetch('/api/ideas', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ body: ta.value.trim(), title:'', tags:'' }),
    });
    if (r.ok) { ta.value = ''; showToast('Idea saved', 'success'); loadMorningBrief(); }
  } catch(e) { showToast('Failed to save', 'error'); }
}

// ── RIPPLE ON INTERACTIVE ELEMENTS ──────────────────────────
(function attachRipples() {
  function ripple(el) {
    if (el.dataset.rip) return;
    el.dataset.rip = '1';
    el.style.position = el.style.position || 'relative';
    el.style.overflow  = 'hidden';
    el.addEventListener('click', e => {
      const r   = el.getBoundingClientRect();
      const w   = document.createElement('span');
      w.className = 'ripple-wave';
      w.style.left = (e.clientX - r.left) + 'px';
      w.style.top  = (e.clientY - r.top)  + 'px';
      el.appendChild(w);
      w.addEventListener('animationend', () => w.remove());
    });
  }
  function attachAll() {
    document.querySelectorAll('.action-card,.nav-item,.stat-card,.btn-primary').forEach(ripple);
  }
  document.addEventListener('DOMContentLoaded', attachAll);
  const _prev = showMainView;
  showMainView = function() { _prev(); setTimeout(attachAll, 300); };
})();

// ═══════════════════════════════════════════════════════════
// VSCARS v14.0 — MODAL + BUG FIXES
// ═══════════════════════════════════════════════════════════

// Tool modal now uses style.display (consistent with other modals)
// Patch classList-based open/close to use display instead
(function patchToolModal() {
    const _origShow = showToolModal;
    showToolModal = function(toolName, inputs) {
        _origShow(toolName, inputs);
        // classList.add('open') was called by original — override with display
        const m = document.getElementById('tool-modal');
        if (m) { m.classList.remove('open'); m.style.display = 'flex'; }
    };
})();

// closeTool → was closeModal
function closeTool() {
    const m = document.getElementById('tool-modal');
    if (m) { m.style.display = 'none'; m.classList.remove('open'); }
    const form = document.getElementById('tool-form');
    if (form) { form.reset(); form.dataset.tool = ''; }
    const r = document.getElementById('tool-result');
    if (r) r.style.display = 'none';
}

// Also patch the internal closeModal call
const _origCloseModal = typeof closeModal === 'function' ? closeModal : null;
closeModal = closeTool;

// copyResult
function copyResult() {
    const pre = document.getElementById('result-output');
    if (!pre) return;
    navigator.clipboard.writeText(pre.textContent).then(() => showToast('Copied', 'success'));
}

// finishOnboarding (simple version)
function finishOnboarding() {
    localStorage.setItem('onboarding_done', '1');
    const m = document.getElementById('onboarding-modal');
    if (m) m.style.display = 'none';
}

// closeQRModal
function closeQRModal() {
    const m = document.getElementById('qr-modal');
    if (m) m.style.display = 'none';
}

// Fix showUpgradeModal — new modal uses upgrade-modal-msg not upgrade-reason
(function patchUpgradeModal() {
    const _orig = showUpgradeModal;
    showUpgradeModal = function(detail) {
        const modal = document.getElementById('upgrade-modal');
        if (!modal) return;
        const msg = typeof detail === 'string' ? detail : (detail?.message || 'You have reached your daily limit.');
        const msgEl = document.getElementById('upgrade-modal-msg');
        if (msgEl) msgEl.textContent = msg;
        modal.style.display = 'flex';
    };
})();

// Tool modal close on classList.remove('open') still called by old code paths
const _MO = new MutationObserver(() => {
    const m = document.getElementById('tool-modal');
    if (m && m.classList.contains('open') && m.style.display === 'none') {
        m.style.display = 'flex';
    }
});
document.addEventListener('DOMContentLoaded', () => {
    const m = document.getElementById('tool-modal');
    if (m) _MO.observe(m, { attributes: true, attributeFilter: ['class'] });
});

// ==================== MOBILE DRAWER ====================

function openMobDrawer() {
    const drawer   = document.getElementById('mob-drawer');
    const backdrop = document.getElementById('mob-drawer-backdrop');
    if (!drawer) return;
    _updateDrawerCurrentView();
    requestAnimationFrame(() => {
        drawer.classList.add('open');
        if (backdrop) backdrop.classList.add('open');
    });
}

function closeMobDrawer() {
    const drawer   = document.getElementById('mob-drawer');
    const backdrop = document.getElementById('mob-drawer-backdrop');
    if (drawer)   drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
}

function toggleMobDrawer() {
    const drawer = document.getElementById('mob-drawer');
    if (!drawer) return;
    drawer.classList.contains('open') ? closeMobDrawer() : openMobDrawer();
}

// Highlight the currently active view in the drawer
function _updateDrawerCurrentView() {
    const active = document.querySelector('.view.active');
    const viewId = active ? active.id.replace('-view','') : '';
    document.querySelectorAll('.mob-drawer-item').forEach(el => {
        const v = el.dataset.view;
        el.classList.toggle('is-current-view', v === viewId);
    });
    const label = document.getElementById('mob-drawer-current');
    if (label) label.textContent = viewId || '';
}

// Wire drawer items — navigate + close
document.addEventListener('DOMContentLoaded', () => {
    // Pill tap
    const pill = document.getElementById('mob-pill');
    if (pill) pill.addEventListener('click', openMobDrawer);

    // Drawer item tap
    document.querySelectorAll('.mob-drawer-item.nav-item').forEach(el => {
        el.addEventListener('click', () => closeMobDrawer());
    });

    // ── Drag-up on pill to open ──────────────────────────────────
    let _pilDragStart = null;
    if (pill) {
        pill.addEventListener('touchstart', e => {
            _pilDragStart = e.touches[0].clientY;
            pill.classList.add('dragging');
        }, { passive: true });

        pill.addEventListener('touchmove', e => {
            if (_pilDragStart === null) return;
            const dy = _pilDragStart - e.touches[0].clientY; // positive = dragged up
            if (dy > 30) { openMobDrawer(); _pilDragStart = null; }
        }, { passive: true });

        pill.addEventListener('touchend', () => {
            _pilDragStart = null;
            pill.classList.remove('dragging');
        }, { passive: true });
    }

    // ── Drag-down on drawer handle to close ──────────────────────
    const handle = document.getElementById('mob-drawer-handle');
    const drawer = document.getElementById('mob-drawer');
    if (handle && drawer) {
        let _dragStartY = null;
        let _currentY   = 0;

        handle.addEventListener('touchstart', e => {
            _dragStartY = e.touches[0].clientY;
            drawer.classList.add('dragging');
        }, { passive: true });

        handle.addEventListener('touchmove', e => {
            if (_dragStartY === null) return;
            const dy = e.touches[0].clientY - _dragStartY; // positive = dragged down
            if (dy < 0) return; // don't allow dragging up past open
            _currentY = dy;
            drawer.style.transform = `translateY(${dy}px)`;
        }, { passive: true });

        handle.addEventListener('touchend', () => {
            drawer.classList.remove('dragging');
            drawer.style.transform = '';
            if (_currentY > 100) {
                closeMobDrawer();
            }
            _dragStartY = null;
            _currentY   = 0;
        }, { passive: true });
    }
});

// ==================== FILE BROWSER HELPERS ====================

function goUpDirectory() {
    const path = currentBrowsePath || document.getElementById('file-path-input')?.value?.trim();
    if (!path || path === '/') return;
    const parent = path.replace(/\/+$/, '').replace(/\/[^\/]+$/, '') || '/';
    browsePath(parent);
}

// Filter visible file items without re-fetching
function filterFileList(query) {
    const q = query.toLowerCase();
    const items = document.querySelectorAll('#file-list .file-item');
    items.forEach(el => {
        const name = el.textContent.toLowerCase();
        el.style.display = (!q || name.includes(q)) ? '' : 'none';
    });
}

// Init file browser when view opens — load workspace root
(function patchFileBrowserInit() {
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelector('[data-view="file-browser"]')?.addEventListener('click', () => {
            if (!currentBrowsePath) {
                // Load workspace on first open
                fetchAPI('/api/settings/workspace').then(r => {
                    const ws = r.workspace || '~';
                    document.getElementById('file-path-input').value = ws;
                    browsePath(ws);
                }).catch(() => {
                    document.getElementById('file-path-input').value = '~';
                    browsePath('~');
                });
            }
        });
    });
})();

// ==================== QUOTA MODEL PICKER ====================

function retryWithModel(modelId) {
    document.getElementById('result-output').innerHTML = '';
    document.getElementById('tool-result').style.display = 'none';
    openCopilotAgentTool(modelId);
    showToast(`Switched to ${modelId}`, 'success');
}

// Show copy button when result arrives
(function patchResultDisplay() {
    const _orig = executeToolForm;
    // wrap after DOM ready since executeToolForm is defined inline
    document.addEventListener('DOMContentLoaded', () => {
        const resultEl = document.getElementById('tool-result');
        if (!resultEl) return;
        const obs = new MutationObserver(() => {
            const copyRow = document.getElementById('copy-result-row');
            if (copyRow) copyRow.style.display = resultEl.style.display !== 'none' ? 'block' : 'none';
        });
        obs.observe(resultEl, { attributes: true, attributeFilter: ['style'] });
    });
})();

