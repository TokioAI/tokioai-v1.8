"""
Prompt Guard utility tools.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def prompt_guard_audit(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Actions:
    - status: show audit file path and line count
    - recent: show recent entries (default 20)
    """
    params = params or {}
    action = (action or "").strip().lower()
    path = Path(os.getenv("TOKIO_PROMPT_GUARD_AUDIT_PATH", "/workspace/cli/prompt_guard_audit.jsonl"))

    if action == "status":
        exists = path.exists()
        lines = 0
        if exists:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = sum(1 for _ in f)
            except Exception:
                lines = 0
        return json.dumps(
            {"ok": True, "action": action, "path": str(path), "exists": exists, "entries": lines},
            ensure_ascii=False,
        )

    if action == "recent":
        n = int(params.get("limit", 20))
        if not path.exists():
            return json.dumps({"ok": True, "action": action, "entries": []}, ensure_ascii=False)
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return json.dumps({"ok": True, "action": action, "entries": rows[-max(1, n):]}, ensure_ascii=False)

    return json.dumps(
        {"ok": False, "action": action, "error": "acción no soportada", "supported": ["status", "recent"]},
        ensure_ascii=False,
    )

