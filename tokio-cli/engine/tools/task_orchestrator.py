"""
Task Orchestrator Tool — v2
Autonomous operational playbooks with persisted state, auto-detection,
robust error handling, and optional Telegram notifications.

Supported playbook types:
  - script_cron:       Create a bash script + cron job (periodic)
  - script_once:       Create a bash script and run it once
  - install_packages:  Install system packages via apt

The orchestrator auto-detects playbook type when not specified:
  - If `schedule` is provided → script_cron
  - If `packages` is provided → install_packages
  - Otherwise               → script_once
"""
from __future__ import annotations

import json
import os
import re
import uuid
import requests
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from .host_tools import host_control

_TASKS_PATH = Path(os.getenv("TOKIO_TASKS_PATH", "/workspace/cli/tasks/state.json"))
_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_ID", "").strip()

VALID_PLAYBOOKS = {"script_cron", "install_packages", "script_once"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().isoformat()


def _load_state() -> Dict[str, Any]:
    try:
        if _TASKS_PATH.exists():
            data = json.loads(_TASKS_PATH.read_text())
            if isinstance(data, dict):
                data.setdefault("tasks", {})
                return data
    except Exception:
        pass
    return {"tasks": {}}


def _save_state(state: Dict[str, Any]) -> None:
    _TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TASKS_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _notify(chat_id: str, message: str) -> None:
    if not _BOT_TOKEN or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def _new_task(kind: str, payload: Dict[str, Any], chat_id: str = "") -> Dict[str, Any]:
    task_id = f"tsk-{uuid.uuid4().hex[:10]}"
    return {
        "id": task_id,
        "kind": kind,
        "status": "planned",
        "created_at": _now(),
        "updated_at": _now(),
        "payload": payload,
        "idempotency_key": str(payload.get("idempotency_key", "")).strip(),
        "chat_id": chat_id or _OWNER_CHAT_ID or "",
        "steps": [],
        "result": {},
        "error": "",
    }


def _update_task(
    state: Dict[str, Any],
    task: Dict[str, Any],
    status: str,
    step: str = "",
    result: Optional[Dict[str, Any]] = None,
    error: str = "",
) -> None:
    task["status"] = status
    task["updated_at"] = _now()
    if step:
        task["steps"].append({"at": _now(), "status": status, "step": step})
    if result is not None:
        task["result"] = result
    if error:
        task["error"] = error
    state["tasks"][task["id"]] = task
    _save_state(state)


def _host_call(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params)
    params.setdefault("confirm", True)
    raw = host_control(action, params)
    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(data.get("error", f"host_control {action} failed"))
    return data.get("result", {})


def _find_by_idempotency(state: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    tasks = state.get("tasks", {})
    for _id, t in tasks.items():
        if str(t.get("idempotency_key", "")).strip() == key:
            return t
    return None


# ---------------------------------------------------------------------------
# Auto-detect playbook type
# ---------------------------------------------------------------------------

def _auto_detect_playbook(params: Dict[str, Any]) -> str:
    """
    Infer the playbook type from the provided parameters:
      - If `schedule` or `cron` key present    → script_cron
      - If `packages` key present              → install_packages
      - Otherwise                              → script_once
    Also normalizes common LLM mistakes:
      - 'cron', 'cron_script', 'bash_cron'    → script_cron
      - 'once', 'run_once', 'bash_once'       → script_once
      - 'apt', 'install', 'packages'          → install_packages
    """
    raw = str(params.get("playbook", "")).strip().lower()

    # Direct match
    if raw in VALID_PLAYBOOKS:
        return raw

    # Fuzzy match common LLM mistakes
    cron_aliases = {"cron", "cron_script", "bash_cron", "script-cron", "cronjob", "cron_job"}
    once_aliases = {"once", "run_once", "bash_once", "script-once", "run", "bash", "shell"}
    pkg_aliases = {"apt", "install", "packages", "install-packages", "apt-get", "pkg"}

    if raw in cron_aliases:
        return "script_cron"
    if raw in once_aliases:
        return "script_once"
    if raw in pkg_aliases:
        return "install_packages"

    # Infer from available fields
    if params.get("schedule") or params.get("cron"):
        return "script_cron"
    if params.get("packages"):
        return "install_packages"
    if params.get("script_content") or params.get("command"):
        return "script_once"

    # Default: if there is a schedule somewhere in the params string representation
    params_str = json.dumps(params)
    if re.search(r'[*/]\d', params_str):
        return "script_cron"

    return "script_once"


# ---------------------------------------------------------------------------
# Ensure script_content is valid bash
# ---------------------------------------------------------------------------

def _ensure_bash_script(content: str) -> str:
    """Ensure the script starts with a shebang and has set -e for safety."""
    content = content.strip()
    if not content:
        return "#!/bin/bash\nset -e\necho 'Empty script'\n"
    if not content.startswith("#!"):
        content = "#!/bin/bash\nset -e\n" + content
    return content + "\n"


# ---------------------------------------------------------------------------
# Playbook Runners
# ---------------------------------------------------------------------------

def _run_script_cron(task: Dict[str, Any]) -> Dict[str, Any]:
    payload = task["payload"]
    script_path = payload.get("script_path", f"/opt/tokioai/task_{task['id']}.sh")
    script_content = _ensure_bash_script(payload.get("script_content", ""))
    schedule = payload.get("schedule") or payload.get("cron", "")
    tag = payload.get("tag", f"tokio-{task['id']}")
    notify = bool(payload.get("notify_telegram", True))
    chat_id = payload.get("telegram_chat_id", task.get("chat_id", ""))

    if not schedule:
        raise ValueError("schedule es requerido para script_cron (ej: '*/10 * * * *')")

    # Write script file
    wr = _host_call("write_file", {
        "path": script_path,
        "content": script_content,
        "chmod": "755",
        "mkdir_parents": True,
    })

    # Add cron entry
    cr = _host_call("cron_add", {
        "schedule": schedule,
        "command": script_path,
        "tag": tag,
        "notify_telegram": notify,
        "telegram_chat_id": chat_id,
    })

    # Verify cron was added
    cl = _host_call("cron_list", {"user": str(payload.get("user", ""))})
    tag_marker = f"# tokio:{tag}"
    cron_content = str(cl.get("content", ""))
    if tag_marker not in cron_content:
        raise RuntimeError(f"No se pudo verificar entrada cron para tag={tag}")

    return {"write_file": wr, "cron_add": cr, "cron_verified": True, "script_path": script_path}


def _run_install_packages(task: Dict[str, Any]) -> Dict[str, Any]:
    pkgs = task["payload"].get("packages", [])
    if isinstance(pkgs, str):
        pkgs = [p.strip() for p in pkgs.replace(",", " ").split() if p.strip()]
    if not pkgs:
        raise ValueError("packages es requerido (lista de paquetes a instalar)")
    out = _host_call("install_packages", {"packages": pkgs})
    return {"install_packages": out, "packages": pkgs}


def _run_script_once(task: Dict[str, Any]) -> Dict[str, Any]:
    payload = task["payload"]
    script_path = payload.get("script_path", f"/opt/tokioai/once_{task['id']}.sh")
    script_content = _ensure_bash_script(
        payload.get("script_content") or payload.get("command", "")
    )
    if script_content.strip() in ("#!/bin/bash\nset -e\necho 'Empty script'\n", ""):
        raise ValueError("script_content es requerido para script_once")

    wr = _host_call("write_file", {
        "path": script_path,
        "content": script_content,
        "chmod": "755",
        "mkdir_parents": True,
    })
    rn = _host_call("run", {"command": script_path})
    return {"write_file": wr, "run": rn, "script_path": script_path}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

PLAYBOOK_RUNNERS = {
    "script_cron": _run_script_cron,
    "install_packages": _run_install_packages,
    "script_once": _run_script_once,
}


def task_orchestrator(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Orchestrate autonomous tasks with persistent state.

    Actions:
      run_playbook  — Execute a playbook (script_cron, install_packages, script_once).
                      Auto-detects type if 'playbook' is wrong/missing.
      get_task      — Fetch status of a task by id.
      list_tasks    — List recent task statuses.

    Params for run_playbook:
      playbook         — (optional) One of: script_cron | install_packages | script_once.
                         Auto-detected if missing/wrong.
      script_content   — Bash script content (for script_cron / script_once).
      schedule         — Cron schedule (for script_cron), e.g. "*/10 * * * *".
      packages         — List of packages (for install_packages).
      script_path      — (optional) Path for the script file.
      tag              — (optional) Identifier tag for the cron entry.
      notify_telegram  — (optional, default true) Notify on completion.
      idempotency_key  — (optional) Prevents duplicate execution.
      max_retries      — (optional, default 1) Max retry attempts on failure.
    """
    params = params or {}
    action = (action or "").strip().lower()
    state = _load_state()

    # ----- list_tasks -----
    if action == "list_tasks":
        tasks = list(state.get("tasks", {}).values())[-20:]
        return json.dumps({"ok": True, "action": action, "tasks": tasks}, ensure_ascii=False)

    # ----- get_task -----
    if action == "get_task":
        task_id = str(params.get("task_id", "")).strip()
        task = state.get("tasks", {}).get(task_id)
        if not task:
            return json.dumps({"ok": False, "action": action, "error": f"task no encontrada: {task_id}"}, ensure_ascii=False)
        return json.dumps({"ok": True, "action": action, "task": task}, ensure_ascii=False)

    # ----- run_playbook -----
    if action != "run_playbook":
        return json.dumps(
            {
                "ok": False,
                "action": action,
                "error": f"Acción '{action}' no soportada. Usa: run_playbook | get_task | list_tasks",
            },
            ensure_ascii=False,
        )

    # Auto-detect playbook type
    playbook = _auto_detect_playbook(params)
    chat_id = str(params.get("telegram_chat_id", "")).strip() or _OWNER_CHAT_ID

    # Idempotency check
    idem_key = str(params.get("idempotency_key", "")).strip()
    existing = _find_by_idempotency(state, idem_key)
    if existing and existing.get("status") in {"planned", "running", "verifying", "done"}:
        return json.dumps(
            {
                "ok": True,
                "action": action,
                "task_id": existing.get("id"),
                "status": existing.get("status"),
                "result": existing.get("result", {}),
                "message": "Task reutilizada por idempotency_key",
            },
            ensure_ascii=False,
        )

    # Create task
    task = _new_task(playbook, params, chat_id=chat_id)
    state["tasks"][task["id"]] = task
    _save_state(state)
    _notify(chat_id, f"🛠️ *Tokio Task* `{task['id']}` iniciada (`{playbook}`).")

    try:
        _update_task(state, task, "running", step=f"playbook={playbook} started")

        runner = PLAYBOOK_RUNNERS.get(playbook)
        if not runner:
            raise ValueError(
                f"playbook '{playbook}' no reconocido. "
                f"Valores válidos: {', '.join(sorted(VALID_PLAYBOOKS))}"
            )

        max_retries = max(0, int(params.get("max_retries", 1)))
        attempts = 0
        last_error = ""
        result: Dict[str, Any] = {}

        while attempts <= max_retries:
            try:
                result = runner(task)
                last_error = ""
                break
            except Exception as run_err:
                last_error = str(run_err)
                attempts += 1
                _update_task(
                    state, task, "running",
                    step=f"retry {attempts}/{max_retries}: {last_error[:120]}",
                )
                if attempts > max_retries:
                    raise RuntimeError(last_error)

        _update_task(state, task, "verifying", step="verification")
        _update_task(state, task, "done", step="completed", result=result)
        _notify(chat_id, f"✅ *Tokio Task* `{task['id']}` completada ({playbook}).")

        return json.dumps(
            {
                "ok": True,
                "action": action,
                "task_id": task["id"],
                "playbook": playbook,
                "status": "done",
                "result": result,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        _update_task(state, task, "failed", step="failed", error=str(e))
        _notify(chat_id, f"❌ *Tokio Task* `{task['id']}` falló: {e}")
        return json.dumps(
            {
                "ok": False,
                "action": action,
                "task_id": task["id"],
                "playbook": playbook,
                "status": "failed",
                "error": str(e),
            },
            ensure_ascii=False,
        )
