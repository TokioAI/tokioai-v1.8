#!/usr/bin/env python3.11
"""
Sandbox runner tools para Tokio Pro.
Ejecuta comandos en el runner existente con restricciones de seguridad.
"""

import os
import subprocess
from typing import Dict, Any, Optional


RUNNER_BASE_URL = os.getenv("RUNNER_BASE_URL", "").strip()
RUNNER_TOKEN = os.getenv("RUNNER_TOKEN", "").strip()
SANDBOX_IMAGE = os.getenv("TOKIO_PRO_SANDBOX_IMAGE", os.getenv("RUNNER_IMAGE", "tokio-sandbox:latest"))
SANDBOX_TIMEOUT = int(os.getenv("TOKIO_PRO_TIMEOUT", "120"))
SANDBOX_NETWORK = os.getenv("TOKIO_PRO_NETWORK", "none")
SANDBOX_READONLY = os.getenv("TOKIO_PRO_READONLY", "true").lower() == "true"
SANDBOX_CPU = os.getenv("TOKIO_PRO_CPU", "1")
SANDBOX_MEM = os.getenv("TOKIO_PRO_MEM", "512m")
SANDBOX_PIDS = os.getenv("TOKIO_PRO_PIDS", "256")
SANDBOX_USER = os.getenv("TOKIO_PRO_USER", "1000:1000").strip()


def _build_workspace_cmd(command: str, workspace_id: str) -> str:
    safe_workspace = "".join(c for c in workspace_id if c.isalnum() or c in ("-", "_"))
    workdir = f"/workspace/tokio-pro/{safe_workspace}"
    return f"bash -lc \"mkdir -p {workdir} && cd {workdir} && {command}\""


async def tool_sandbox_exec_tokio(
    command: str,
    workspace_id: Optional[str] = None,
    timeout_sec: Optional[int] = None
) -> Dict[str, Any]:
    """
    Ejecuta un comando dentro del sandbox Tokio Pro.
    - Sin red por defecto
    - FS readonly salvo /workspace
    - Límites CPU/RAM/PIDs
    """
    if not command or not isinstance(command, str):
        return {"success": False, "error": "Comando vacío"}

    workspace_id = workspace_id or "default"
    timeout_sec = int(timeout_sec or SANDBOX_TIMEOUT)
    safe_workspace = "".join(c for c in workspace_id if c.isalnum() or c in ("-", "_")) or "default"
    sandbox_cmd = _build_workspace_cmd(command, safe_workspace)

    # Runner remoto
    if RUNNER_BASE_URL:
        import requests
        headers = {}
        if RUNNER_TOKEN:
            headers["X-Runner-Token"] = RUNNER_TOKEN
        resp = requests.post(
            f"{RUNNER_BASE_URL.rstrip('/')}/run",
            json={"command": sandbox_cmd},
            headers=headers,
            timeout=timeout_sec + 10
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"Runner remoto error: {resp.status_code} {resp.text[:200]}"}
        payload = resp.json()
        if not payload.get("success"):
            return {"success": False, "error": payload.get("error") or "Runner remoto falló"}
        result = payload.get("result", {})
        return {
            "success": True,
            "workspace_id": safe_workspace,
            "result": result
        }

    # Runner local (fallback)
    os.makedirs("/tmp/tokio_runner", exist_ok=True)
    try:
        os.chmod("/tmp/tokio_runner", 0o777)
    except Exception:
        pass

    runner_cmd = [
        "docker", "run", "--rm",
        "--network", SANDBOX_NETWORK,
        "--pids-limit", str(SANDBOX_PIDS),
        "--memory", SANDBOX_MEM,
        "--cpus", SANDBOX_CPU,
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--tmpfs", "/var/tmp:rw,noexec,nosuid,nodev,size=32m",
        "-v", "/tmp/tokio_runner:/workspace:rw",
        "-w", f"/workspace/tokio-pro/{safe_workspace}",
    ]
    if SANDBOX_READONLY:
        runner_cmd.insert(3, "--read-only")
    if SANDBOX_USER:
        runner_cmd.extend(["--user", SANDBOX_USER])
    runner_cmd.extend([SANDBOX_IMAGE, "bash", "-lc", sandbox_cmd])

    completed = subprocess.run(runner_cmd, capture_output=True, text=True, timeout=timeout_sec)
    return {
        "success": True,
        "workspace_id": safe_workspace,
        "result": {
            "exit_code": completed.returncode,
            "stdout": (completed.stdout or "")[:20000],
            "stderr": (completed.stderr or "")[:20000]
        }
    }
