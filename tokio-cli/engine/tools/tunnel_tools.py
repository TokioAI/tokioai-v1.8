"""
Tunnel Manager Tool
Automates cloudflared tunnel lifecycle on host without opening router ports.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .host_tools import HostManager, HostSSHConfig


def _cfg() -> Dict[str, str]:
    return {
        "tunnel_name": os.getenv("TOKIO_TUNNEL_NAME", "tokioai-tunnel").strip(),
        "tunnel_token": os.getenv("CLOUDFLARED_TUNNEL_TOKEN", "").strip(),
        "image": os.getenv("CLOUDFLARED_IMAGE", "cloudflare/cloudflared:latest").strip(),
        "container_name": os.getenv("CLOUDFLARED_CONTAINER_NAME", "tokio-cloudflared").strip(),
    }


def _mgr() -> HostManager:
    return HostManager(HostSSHConfig())


def _docker_cmd(mgr: HostManager, cmd: str, timeout: int = 60) -> str:
    return mgr._run(f"{mgr._sudo_prefix()}{cmd}", timeout=timeout)


def tunnel_manager(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Manage cloudflared tunnel on host.

    Actions:
    - status
    - deploy (requires token from env or params.token)
    - stop
    - restart
    - logs
    """
    params = params or {}
    action = (action or "").strip().lower()
    cfg = _cfg()
    mgr = _mgr()

    container = str(params.get("container_name", cfg["container_name"])).strip() or cfg["container_name"]
    image = str(params.get("image", cfg["image"])).strip() or cfg["image"]
    token = str(params.get("token", cfg["tunnel_token"])).strip()

    try:
        if action == "status":
            out = _docker_cmd(
                mgr,
                f"docker ps -a --filter name={container} --format '{{{{.Names}}}} {{{{.Status}}}} {{{{.Image}}}}' || true",
            )
            return json.dumps({"ok": True, "action": action, "result": out or "not_found"}, ensure_ascii=False)

        if action == "logs":
            lines = int(params.get("lines", 120))
            out = _docker_cmd(mgr, f"docker logs --tail {max(10, lines)} {container} || true")
            return json.dumps({"ok": True, "action": action, "result": out}, ensure_ascii=False)

        if action == "stop":
            out = _docker_cmd(mgr, f"docker rm -f {container} || true")
            return json.dumps({"ok": True, "action": action, "result": out}, ensure_ascii=False)

        if action == "restart":
            out = _docker_cmd(mgr, f"docker restart {container}")
            return json.dumps({"ok": True, "action": action, "result": out}, ensure_ascii=False)

        if action == "deploy":
            if not token:
                return json.dumps(
                    {
                        "ok": False,
                        "action": action,
                        "error": "Falta token de cloudflared. Configura CLOUDFLARED_TUNNEL_TOKEN o params.token",
                    },
                    ensure_ascii=False,
                )

            # idempotent deploy
            cmd = (
                f"docker rm -f {container} >/dev/null 2>&1 || true; "
                f"docker run -d --name {container} --restart unless-stopped "
                f"{image} tunnel --no-autoupdate run --token '{token}'"
            )
            out = _docker_cmd(mgr, cmd, timeout=120)
            return json.dumps(
                {"ok": True, "action": action, "result": {"container": container, "deploy_output": out}},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": False,
                "action": action,
                "error": "acción no soportada",
                "supported": ["status", "deploy", "stop", "restart", "logs"],
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps({"ok": False, "action": action, "error": str(e)}, ensure_ascii=False)

