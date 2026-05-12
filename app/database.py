from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.config import DATABASE_URL
import logging

log = logging.getLogger(__name__)

# Database engine with proper connection pooling
# pool_size: Number of connections to keep in the pool
# max_overflow: Maximum overflow on top of pool_size
# pool_pre_ping: Test connection before using to detect stale connections
# pool_recycle: Recycle connections after 25 seconds (before 30s timeout)
if "sqlite" in DATABASE_URL:
    # SQLite doesn't use connection pooling
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    # For remote databases (PostgreSQL, MySQL, etc.)
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=25,
        connect_args={"timeout": 30}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    device_id = Column(String, unique=True)  # Phone/Device ID
    is_superuser = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Billing
    plan = Column(String, default="free")  # free | pro | team | self_hosted
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)
    daily_api_calls = Column(Integer, default=0)
    daily_reset_at = Column(DateTime, default=datetime.utcnow)
    # CLI API key — issued on pro+ activation; SHA256 stored, raw shown once
    api_key_hash = Column(String, nullable=True, index=True)

class UserAIConfig(Base):
    """Per-user AI provider configuration — supports any OpenAI-compatible API."""
    __tablename__ = "user_ai_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, unique=True)
    # Active provider: anthropic | openai | groq | together | ollama | custom
    provider = Column(String, default="anthropic")
    # API key (stored in plaintext — user's own key, no billing risk)
    api_key = Column(String, nullable=True)
    # Base URL for OpenAI-compatible APIs (Ollama: http://localhost:11434/v1, Groq: https://api.groq.com/openai/v1, etc.)
    base_url = Column(String, nullable=True)
    # Model name override (e.g. "llama3", "mixtral-8x7b", "claude-sonnet-4-6")
    model = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

class UserPermission(Base):
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    can_run_copilot = Column(Boolean, default=False)
    can_run_commands = Column(Boolean, default=False)
    can_edit_files = Column(Boolean, default=False)
    can_view_files = Column(Boolean, default=False)
    can_use_machine = Column(Boolean, default=False)  # pro+ only: register & relay through own machine
    created_at = Column(DateTime, default=datetime.utcnow)

class AccessRequest(Base):
    __tablename__ = "access_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    request_type = Column(String)  # 'qr_code' or 'direct'
    qr_code_data = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

class CommandLog(Base):
    __tablename__ = "command_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    tool_name = Column(String)  # e.g., 'run_command', 'ask_copilot', 'open_file'
    action = Column(String)  # Description of what was done
    input_params = Column(Text)  # JSON string of input parameters
    result = Column(Text)  # Result/output of the command
    status = Column(String)  # 'success' or 'error'
    device_id = Column(String)  # Which device initiated the command
    created_at = Column(DateTime, default=datetime.utcnow)

class ConversationHistory(Base):
    __tablename__ = "conversation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    query = Column(Text)  # What user asked
    response = Column(Text)  # What Copilot/system replied
    tool_used = Column(String, default="ask_copilot")  # Which tool was used
    status = Column(String, default="success")  # success or error
    device_id = Column(String)  # Which device sent the query
    created_at = Column(DateTime, default=datetime.utcnow)

class SelfHealingIssue(Base):
    __tablename__ = "self_healing_issues"
    
    id = Column(Integer, primary_key=True, index=True)
    issue_type = Column(String, index=True)  # 'bug' or 'feature_request'
    title = Column(String)  # Bug title or feature name
    description = Column(Text)  # Detailed description
    affected_file = Column(String, nullable=True)  # File path affected (for bugs)
    error_message = Column(Text, nullable=True)  # Error stack trace
    reproduction_steps = Column(Text, nullable=True)  # How to reproduce
    requested_by = Column(Integer, index=True)  # user_id
    status = Column(String, index=True, default="reported")  # reported, in-progress, fixing, testing, completed, deployed
    priority = Column(String, default="medium")  # low, medium, high, critical
    assigned_to = Column(String, default="copilot_agent")  # Who's fixing it
    copilot_response = Column(Text, nullable=True)  # What Copilot proposed
    fix_summary = Column(Text, nullable=True)  # Summary of changes made
    files_modified = Column(Text, nullable=True)  # JSON list of modified files
    git_commit_hash = Column(String, nullable=True)  # Commit that fixed it
    server_restart_time = Column(DateTime, nullable=True)  # When server was restarted
    ngrok_url = Column(String, nullable=True)  # URL that was generated after fix
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    in_progress_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class IssueNotificationQueue(Base):
    __tablename__ = "issue_notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, index=True)  # Reference to SelfHealingIssue
    user_id = Column(Integer, index=True)  # Who to notify
    event_type = Column(String)  # 'reported', 'in_progress', 'fix_found', 'deploying', 'completed'
    message = Column(Text)  # Notification message
    qr_code_url = Column(String, nullable=True)  # Dynamic QR code URL
    ngrok_url = Column(String, nullable=True)  # Current ngrok URL
    was_delivered = Column(Boolean, default=False)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class TokenBlacklist(Base):
    """Revoked tokens — checked on every authenticated request"""
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, index=True)
    token_jti = Column(String, unique=True, index=True)  # JWT ID or hash
    user_id = Column(Integer, index=True)
    revoked_at = Column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    """Single-use password reset tokens sent via email"""
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    token = Column(String, unique=True, index=True)
    expires_at = Column(DateTime)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class LicenseKey(Base):
    """Self-hosted license keys — one-time or monthly"""
    __tablename__ = "license_keys"

    id = Column(Integer, primary_key=True, index=True)
    key_hash = Column(String, unique=True, index=True)   # SHA256 of raw key
    edition = Column(String, default="self_hosted")
    issued_to = Column(String, nullable=True)            # email or identifier
    is_active = Column(Boolean, default=True)
    max_activations = Column(Integer, default=3)
    activation_count = Column(Integer, default=0)
    payment_type = Column(String, nullable=True)         # one_time | monthly
    stripe_payment_intent_id = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)         # null = lifetime
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)


class IdeaNote(Base):
    __tablename__ = "idea_notes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    title = Column(String, nullable=True)           # optional short title
    body = Column(Text)                              # the idea content
    tags = Column(String, nullable=True)             # comma-separated tags
    is_done = Column(Boolean, default=False)         # converted to code?
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

class SavedWorkflow(Base):
    __tablename__ = "saved_workflows"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    name = Column(String)                            # "Deploy to staging"
    command = Column(Text)                           # "npm run build && git push"
    cwd = Column(String, nullable=True)              # optional working dir
    icon = Column(String, default="⚡")             # emoji icon
    run_count = Column(Integer, default=0)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    session_token_hash = Column(String, unique=True, index=True)  # SHA256 of JWT
    device_info = Column(String, nullable=True)      # User-Agent
    ip_address = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)


class RegisteredMachine(Base):
    """A user's own laptop/desktop running the vscars CLI agent.
    Pro+ users register their machine once; all FS/terminal/git tool calls
    are proxied to it over a persistent WebSocket — the server host FS is
    never touched for non-superuser requests."""
    __tablename__ = "registered_machines"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    machine_id = Column(String, unique=True, index=True)  # UUID generated by CLI on first init
    name = Column(String)                                  # "MacBook Pro", "Dev Box"
    hostname = Column(String, nullable=True)
    os_info = Column(String, nullable=True)
    token_hash = Column(String, unique=True, index=True)   # SHA256 of machine auth token
    is_active = Column(Boolean, default=True)
    is_connected = Column(Boolean, default=False)          # agent currently online?
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    autodetect = Column(Text, nullable=True)               # JSON: workspace, git_repos, agents

class TrustPolicy(Base):
    __tablename__ = "trust_policies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True)
    profile = Column(String, default="balanced")  # safe | balanced | power
    require_approval = Column(Boolean, default=True)
    block_destructive = Column(Boolean, default=True)
    allow_network = Column(Boolean, default=True)
    kill_switch = Column(Boolean, default=False)
    allowed_command_prefixes = Column(Text, nullable=True)  # comma/newline separated
    updated_at = Column(DateTime, default=datetime.utcnow)

class ToolApproval(Base):
    __tablename__ = "tool_approvals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)                # requester
    tool_name = Column(String, index=True)
    input_params = Column(Text)                          # JSON payload
    request_fingerprint = Column(String, index=True)     # dedupe + one-time approvals
    sensitivity_reason = Column(String, nullable=True)
    status = Column(String, default="pending", index=True)  # pending | approved | rejected | consumed
    approved_by = Column(Integer, nullable=True)         # approver user_id
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)

class ScrumItem(Base):
    __tablename__ = "scrum_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    item_type = Column(String, index=True)
    title = Column(String)
    description = Column(Text, nullable=True)
    status = Column(String, default="todo", index=True)
    priority = Column(String, default="medium")
    parent_id = Column(Integer, index=True, nullable=True)
    story_points = Column(Integer, nullable=True)
    tags = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    tool_name = Column(String, index=True)  # ask_agent | copilot_agent
    input_params = Column(Text)             # JSON payload
    status = Column(String, default="queued", index=True)  # queued|running|completed|failed
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    notified = Column(Boolean, default=False, index=True)
    agent_session_id = Column(Integer, index=True, nullable=True)
    scrum_item_id = Column(Integer, index=True, nullable=True)


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    name = Column(String, nullable=True)
    agent = Column(String, default="copilot")       # copilot|claude|codex
    model = Column(String, nullable=True)
    project_path = Column(String, nullable=True)
    allow_tools = Column(String, default="all")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
    last_task_id = Column(Integer, nullable=True)


class AgentSessionMessage(Base):
    __tablename__ = "agent_session_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)
    role = Column(String)                            # user | assistant | system
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

# Create tables + run lightweight column migrations for SQLite
def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_add_billing_columns()
    _migrate_add_machine_columns()
    _migrate_add_api_key_column()
    _migrate_add_trust_policy_columns()
    _migrate_add_tool_approval_columns()
    _migrate_add_agent_session_columns()
    _migrate_add_agent_task_columns()
    _migrate_add_scrum_columns()
    _migrate_add_user_ai_config()


def _migrate_add_user_ai_config():
    """Create user_ai_configs table columns if it already exists but is missing columns."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("PRAGMA table_info(user_ai_configs)"))
            existing = {row[1] for row in result}
        except Exception:
            return

        new_cols = [
            ("provider", "VARCHAR DEFAULT 'anthropic'"),
            ("api_key", "VARCHAR"),
            ("base_url", "VARCHAR"),
            ("model", "VARCHAR"),
            ("updated_at", "DATETIME"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in existing:
                try:
                    conn.execute(sa.text(
                        f"ALTER TABLE user_ai_configs ADD COLUMN {col_name} {col_def}"
                    ))
                    conn.commit()
                    log.info("Migration: added column user_ai_configs.%s", col_name)
                except Exception as exc:
                    log.debug("Migration skip user_ai_configs.%s: %s", col_name, exc)


def _migrate_add_billing_columns():
    """Add billing columns to existing 'users' table if they don't exist yet.
    SQLite supports ALTER TABLE ADD COLUMN for nullable/default columns."""
    import sqlalchemy as sa
    new_cols = [
        ("plan",                    "VARCHAR DEFAULT 'free'"),
        ("stripe_customer_id",      "VARCHAR"),
        ("stripe_subscription_id",  "VARCHAR"),
        ("trial_ends_at",           "DATETIME"),
        ("daily_api_calls",         "INTEGER DEFAULT 0"),
        ("daily_reset_at",          "DATETIME"),
    ]
    with engine.connect() as conn:
        result = conn.execute(sa.text("PRAGMA table_info(users)"))
        existing = {row[1] for row in result}
        for col_name, col_def in new_cols:
            if col_name not in existing:
                try:
                    conn.execute(sa.text(
                        f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"
                    ))
                    conn.commit()
                    log.info("Migration: added column users.%s", col_name)
                except Exception as exc:
                    log.debug("Migration skip %s: %s", col_name, exc)


def _migrate_add_api_key_column():
    import sqlalchemy as sa
    with engine.connect() as conn:
        result = conn.execute(sa.text("PRAGMA table_info(users)"))
        existing = {row[1] for row in result}
        if "api_key_hash" not in existing:
            try:
                conn.execute(sa.text("ALTER TABLE users ADD COLUMN api_key_hash VARCHAR"))
                conn.commit()
                log.info("Migration: added column users.api_key_hash")
            except Exception as exc:
                log.debug("Migration skip api_key_hash: %s", exc)


def _migrate_add_machine_columns():
    """Add can_use_machine to user_permissions if missing (SQLite-safe)."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        result = conn.execute(sa.text("PRAGMA table_info(user_permissions)"))
        existing = {row[1] for row in result}
        if "can_use_machine" not in existing:
            try:
                conn.execute(sa.text(
                    "ALTER TABLE user_permissions ADD COLUMN can_use_machine BOOLEAN DEFAULT 0"
                ))
                conn.commit()
                log.info("Migration: added column user_permissions.can_use_machine")
            except Exception as exc:
                log.debug("Migration skip can_use_machine: %s", exc)

def _migrate_add_trust_policy_columns():
    """Add trust policy columns for existing deployments if needed."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("PRAGMA table_info(trust_policies)"))
            existing = {row[1] for row in result}
        except Exception:
            return

        new_cols = [
            ("profile", "VARCHAR DEFAULT 'balanced'"),
            ("require_approval", "BOOLEAN DEFAULT 1"),
            ("block_destructive", "BOOLEAN DEFAULT 1"),
            ("allow_network", "BOOLEAN DEFAULT 1"),
            ("kill_switch", "BOOLEAN DEFAULT 0"),
            ("allowed_command_prefixes", "TEXT"),
            ("updated_at", "DATETIME"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in existing:
                try:
                    conn.execute(sa.text(
                        f"ALTER TABLE trust_policies ADD COLUMN {col_name} {col_def}"
                    ))
                    conn.commit()
                    log.info("Migration: added column trust_policies.%s", col_name)
                except Exception as exc:
                    log.debug("Migration skip trust_policies.%s: %s", col_name, exc)

def _migrate_add_tool_approval_columns():
    """Add tool approval columns for existing deployments if needed."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("PRAGMA table_info(tool_approvals)"))
            existing = {row[1] for row in result}
        except Exception:
            return

        new_cols = [
            ("request_fingerprint", "VARCHAR"),
            ("sensitivity_reason", "VARCHAR"),
            ("approved_by", "INTEGER"),
            ("resolved_at", "DATETIME"),
            ("consumed_at", "DATETIME"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in existing:
                try:
                    conn.execute(sa.text(
                        f"ALTER TABLE tool_approvals ADD COLUMN {col_name} {col_def}"
                    ))
                    conn.commit()
                    log.info("Migration: added column tool_approvals.%s", col_name)
                except Exception as exc:
                    log.debug("Migration skip tool_approvals.%s: %s", col_name, exc)


def _migrate_add_agent_task_columns():
    """Add agent task columns for existing deployments if needed."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("PRAGMA table_info(agent_tasks)"))
            existing = {row[1] for row in result}
        except Exception:
            return

        new_cols = [
            ("agent_session_id", "INTEGER"),
            ("scrum_item_id", "INTEGER"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in existing:
                try:
                    conn.execute(sa.text(
                        f"ALTER TABLE agent_tasks ADD COLUMN {col_name} {col_def}"
                    ))
                    conn.commit()
                    log.info("Migration: added column agent_tasks.%s", col_name)
                except Exception as exc:
                    log.debug("Migration skip agent_tasks.%s: %s", col_name, exc)


def _migrate_add_scrum_columns():
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("PRAGMA table_info(scrum_items)"))
            existing = {row[1] for row in result}
        except Exception:
            return

        new_cols = [
            ("description", "TEXT"),
            ("status", "VARCHAR DEFAULT 'todo'"),
            ("priority", "VARCHAR DEFAULT 'medium'"),
            ("parent_id", "INTEGER"),
            ("story_points", "INTEGER"),
            ("tags", "VARCHAR"),
            ("updated_at", "DATETIME"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in existing:
                try:
                    conn.execute(sa.text(
                        f"ALTER TABLE scrum_items ADD COLUMN {col_name} {col_def}"
                    ))
                    conn.commit()
                    log.info("Migration: added column scrum_items.%s", col_name)
                except Exception as exc:
                    log.debug("Migration skip scrum_items.%s: %s", col_name, exc)


def _migrate_add_agent_session_columns():
    """Add agent session/message columns for existing deployments if needed."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        table_columns = {
            "agent_sessions": [
                ("last_task_id", "INTEGER"),
            ],
            "agent_session_messages": [
                ("created_at", "DATETIME"),
            ],
        }
        for table_name, columns in table_columns.items():
            try:
                result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
                existing = {row[1] for row in result}
            except Exception:
                continue

            for col_name, col_def in columns:
                if col_name not in existing:
                    try:
                        conn.execute(sa.text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"
                        ))
                        conn.commit()
                        log.info("Migration: added column %s.%s", table_name, col_name)
                    except Exception as exc:
                        log.debug("Migration skip %s.%s: %s", table_name, col_name, exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
