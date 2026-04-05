#!/usr/bin/env python3
"""Run subscription + setup flow checks in isolated environment and write a test log."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path


@dataclass
class CaseResult:
    case_id: str
    description: str
    input: dict
    output: dict
    expected: str
    status: str


SENSITIVE_KEYS = {
    "access_token",
    "token",
    "api_key",
    "authorization",
    "x-vscars-key",
}


def _redact_value(v: str) -> str:
    if len(v) <= 10:
        return "***"
    return v[:6] + "..." + v[-4:]


def sanitize(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in SENSITIVE_KEYS or "token" in kl or "api_key" in kl or "authorization" in kl:
                if isinstance(v, str):
                    out[k] = _redact_value(v)
                else:
                    out[k] = "***"
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    return obj


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    work = tempfile.mkdtemp(prefix="vscars_qa_")

    # Isolated runtime config
    os.environ["DATABASE_URL"] = f"sqlite:///{work}/qa.db"
    os.environ["SECRET_KEY"] = "qa-secret-key-1234567890-abcdefghijklmnopqrstuvwxyz"
    os.environ["APP_BASE_URL"] = "https://qa.vscars.local"
    os.environ["ALLOWED_ORIGINS"] = "*"
    os.environ["FORCE_HTTPS"] = "false"

    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal, User
    from app.billing.plan_limits import apply_plan_to_permissions

    client = TestClient(app)
    results: list[CaseResult] = []

    def add(case_id: str, description: str, inp: dict, output: dict, expected: str, ok: bool) -> None:
        results.append(
            CaseResult(
                case_id=case_id,
                description=description,
                input=inp,
                output=output,
                expected=expected,
                status="PASS" if ok else "FAIL",
            )
        )

    # 1) Landing route
    r = client.get("/")
    add(
        "WEB-001",
        "Landing page is reachable",
        {"method": "GET", "path": "/"},
        {"status_code": r.status_code, "contains": "VSCARS" if "VSCARS" in r.text else "missing"},
        "200 and page contains VSCARS",
        r.status_code == 200 and "VSCARS" in r.text,
    )

    # 2) Setup route
    r = client.get("/setup")
    add(
        "WEB-002",
        "Setup page is reachable",
        {"method": "GET", "path": "/setup"},
        {"status_code": r.status_code, "contains": "Setup" if "Setup" in r.text else "missing"},
        "200 and setup page loads",
        r.status_code == 200 and "Setup" in r.text,
    )

    # 3) Installer script route
    r = client.get("/static/install-connector.sh")
    add(
        "WEB-003",
        "Connector install script is reachable",
        {"method": "GET", "path": "/static/install-connector.sh"},
        {"status_code": r.status_code, "first_line": (r.text.splitlines()[0] if r.text else "")},
        "200 and shell script shebang present",
        r.status_code == 200 and r.text.startswith("#!/usr/bin/env bash"),
    )

    # 4) Register admin and free user
    r_admin = client.post(
        "/api/auth/register",
        json={"username": "qa_admin", "email": "qa_admin@test.local", "password": "password123", "device_id": "qa-admin-device"},
    )
    add(
        "AUTH-001",
        "First user register (superuser bootstrap)",
        {"path": "/api/auth/register", "username": "qa_admin"},
        {"status_code": r_admin.status_code, "body": r_admin.json() if r_admin.headers.get("content-type", "").startswith("application/json") else {}},
        "200",
        r_admin.status_code == 200,
    )

    r_free = client.post(
        "/api/auth/register",
        json={"username": "qa_user", "email": "qa_user@test.local", "password": "password123", "device_id": "qa-user-device"},
    )
    free_json = r_free.json() if r_free.status_code == 200 else {}
    add(
        "AUTH-002",
        "Second user register (free plan)",
        {"path": "/api/auth/register", "username": "qa_user"},
        {"status_code": r_free.status_code, "body": free_json},
        "200",
        r_free.status_code == 200,
    )

    if r_free.status_code != 200:
        # still write logs with failure context
        return write_logs(results)

    token = free_json["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 5) Billing status free
    r = client.get("/api/billing/status", headers=auth_headers)
    body = r.json() if r.status_code == 200 else {}
    add(
        "BILL-001",
        "Free plan status and limit",
        {"method": "GET", "path": "/api/billing/status"},
        {"status_code": r.status_code, "plan": body.get("plan"), "daily_limit": body.get("daily_limit")},
        "plan=free and daily_limit=50",
        r.status_code == 200 and body.get("plan") == "free" and body.get("daily_limit") == 50,
    )

    # 6) Free cannot generate API key
    r = client.post("/api/auth/api-key/generate", headers=auth_headers)
    add(
        "BILL-002",
        "Free user blocked from API key generation",
        {"method": "POST", "path": "/api/auth/api-key/generate"},
        {"status_code": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else {}},
        "403",
        r.status_code == 403,
    )

    # 7) Free cannot register machine
    r = client.post(
        "/api/machines/register",
        headers=auth_headers,
        json={"machine_id": "qa-machine-1", "name": "QA Laptop"},
    )
    add(
        "MACH-001",
        "Free user blocked from machine registration",
        {"method": "POST", "path": "/api/machines/register", "json": {"machine_id": "qa-machine-1"}},
        {"status_code": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else {}},
        "403",
        r.status_code == 403,
    )

    # Upgrade user to pro (test simulation)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "qa_user").first()
        user.plan = "pro"
        db.commit()
        apply_plan_to_permissions(user, db)

    # 8) Pro can generate API key
    r = client.post("/api/auth/api-key/generate", headers=auth_headers)
    body = r.json() if r.status_code == 200 else {}
    api_key = body.get("api_key")
    add(
        "BILL-003",
        "Pro user can generate API key",
        {"method": "POST", "path": "/api/auth/api-key/generate"},
        {"status_code": r.status_code, "api_key_prefix": (api_key[:10] + "...") if api_key else None},
        "200 with api_key",
        r.status_code == 200 and bool(api_key),
    )

    # 9) Register machine with API key
    r = client.post(
        "/api/machines/register",
        headers={"X-VSCARS-Key": api_key or ""},
        json={"machine_id": "qa-machine-pro-1", "name": "QA MacBook", "hostname": "qa-host", "os_info": "macOS"},
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    add(
        "MACH-002",
        "Pro user machine registration via API key",
        {
            "method": "POST",
            "path": "/api/machines/register",
            "headers": {"X-VSCARS-Key": "<redacted>"},
            "json": {"machine_id": "qa-machine-pro-1", "name": "QA MacBook"},
        },
        {"status_code": r.status_code, "body": body},
        "200 with machine token",
        r.status_code == 200 and bool(body.get("token")),
    )

    # 10) First command requires approval
    r = client.post("/api/tools/execute", headers=auth_headers, json={"tool": "run_command", "command": "echo hello"})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    approval_id = body.get("approval_id")
    add(
        "TRUST-001",
        "Sensitive command requires approval",
        {"method": "POST", "path": "/api/tools/execute", "json": {"tool": "run_command", "command": "echo hello"}},
        {"status_code": r.status_code, "body": body},
        "200 with approval_required=true",
        r.status_code == 200 and body.get("approval_required") is True and bool(approval_id),
    )

    # 11) Approve and retry => no_machine (agent not started)
    r_approve = client.post(f"/api/trust/approvals/{approval_id}/approve", headers=auth_headers)
    r_retry = client.post("/api/tools/execute", headers=auth_headers, json={"tool": "run_command", "command": "echo hello"})
    retry_body = r_retry.json() if r_retry.headers.get("content-type", "").startswith("application/json") else {}
    detail = retry_body.get("detail", {})
    add(
        "MACH-003",
        "After approval, command blocked until agent starts",
        {
            "approve": {"method": "POST", "path": f"/api/trust/approvals/{approval_id}/approve"},
            "retry": {"method": "POST", "path": "/api/tools/execute", "json": {"tool": "run_command", "command": "echo hello"}},
        },
        {
            "approve_status": r_approve.status_code,
            "retry_status": r_retry.status_code,
            "retry_detail": detail,
        },
        "retry returns 503 code=no_machine and setup_url/install_cmd",
        (
            r_approve.status_code == 200
            and r_retry.status_code == 503
            and isinstance(detail, dict)
            and detail.get("code") == "no_machine"
            and bool(detail.get("setup_url"))
            and bool(detail.get("install_cmd"))
        ),
    )

    return write_logs(results)


def write_logs(results: list[CaseResult]) -> int:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    safe_results = [sanitize(asdict(r)) for r in results]
    out_json = {
        "generated_at": now,
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "PASS"),
        "failed": sum(1 for r in results if r.status == "FAIL"),
        "results": safe_results,
    }

    qa_dir = Path("qa")
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / "latest_test_results.json").write_text(json.dumps(out_json, indent=2))

    md_path = qa_dir / "TEST_RUN_LOG.md"
    header = "# VSCARS Test Run Log\n\n"
    if not md_path.exists():
        md_path.write_text(header)

    lines = []
    lines.append(f"## Run {now}")
    lines.append("")
    lines.append(f"Summary: **{out_json['passed']} passed**, **{out_json['failed']} failed**, total **{out_json['total']}**")
    lines.append("")

    for r in out_json["results"]:
        lines.append(f"### {r['case_id']} - {r['description']} [{r['status']}]")
        lines.append("")
        lines.append("Expected:")
        lines.append(f"`{r['expected']}`")
        lines.append("")
        lines.append("Input:")
        lines.append("```json")
        lines.append(json.dumps(r["input"], indent=2))
        lines.append("```")
        lines.append("")
        lines.append("Output:")
        lines.append("```json")
        lines.append(json.dumps(r["output"], indent=2))
        lines.append("```")
        lines.append("")

    with md_path.open("a") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"summary": {k: out_json[k] for k in ["generated_at", "total", "passed", "failed"]}}, indent=2))
    return 0 if out_json["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
