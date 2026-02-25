"""
Host Control Tool - Admin tasks on the Raspberry Pi host via SSH.

This is intentionally action-based (not a free-form shell) to reduce risk.
For dangerous actions we require an explicit confirm=true parameter.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class HostSSHConfig:
    host: str = os.getenv("HOST_SSH_HOST", "").strip()
    user: str = os.getenv("HOST_SSH_USER", "").strip() or "mrmoz"
    port: int = int(os.getenv("HOST_SSH_PORT", "22"))
    ssh_key_path: str = os.getenv("HOST_SSH_KEY_PATH", "").strip()
    connect_timeout: int = int(os.getenv("HOST_SSH_CONNECT_TIMEOUT", "8"))
    cmd_timeout: int = int(os.getenv("HOST_SSH_CMD_TIMEOUT", "60"))
    sudo: bool = os.getenv("HOST_SSH_SUDO", "true").lower() == "true"
    force_tty: bool = os.getenv("HOST_SSH_FORCE_TTY", "false").lower() == "true"
    allow_run: bool = os.getenv("HOST_CONTROL_ALLOW_RUN", "false").lower() == "true"


class HostToolError(Exception):
    pass


class HostManager:
    def __init__(self, cfg: Optional[HostSSHConfig] = None):
        self.cfg = cfg or HostSSHConfig()

    def _base_ssh_cmd(self) -> list[str]:
        if not self.cfg.host:
            raise HostToolError(
                "HOST_SSH_HOST no está configurado. Ej: HOST_SSH_HOST=YOUR_IP_ADDRESS"
            )

        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            f"ConnectTimeout={self.cfg.connect_timeout}",
            "-p",
            str(self.cfg.port),
        ]
        if self.cfg.force_tty:
            cmd.append("-tt")
        if self.cfg.ssh_key_path:
            cmd += ["-i", self.cfg.ssh_key_path]
        cmd += [f"{self.cfg.user}@{self.cfg.host}"]
        return cmd

    def _sudo_prefix(self) -> str:
        # -n = non-interactive; if sudo needs a password it will fail fast.
        return "sudo -n " if (self.cfg.sudo and self.cfg.user != "root") else ""

    def _run(self, remote_cmd: str, timeout: Optional[int] = None) -> str:
        full = self._base_ssh_cmd() + [remote_cmd]
        try:
            p = subprocess.run(
                full,
                capture_output=True,
                text=True,
                timeout=timeout or self.cfg.cmd_timeout,
            )
            out = (p.stdout or "").strip()
            err = (p.stderr or "").strip()
            if p.returncode != 0:
                raise HostToolError(err or out or f"SSH exited with {p.returncode}")
            return out
        except subprocess.TimeoutExpired:
            raise HostToolError("Timeout ejecutando comando en host")

    # --- Actions ---

    def health(self) -> Dict[str, Any]:
        cmd = (
            "set -e; "
            "echo '__TOKIO__ uname'; uname -a; "
            "echo '__TOKIO__ uptime'; uptime; "
            "echo '__TOKIO__ disk'; df -h / || true; "
            "echo '__TOKIO__ mem'; (free -h || true); "
            "echo '__TOKIO__ docker'; (docker ps --format '{{.Names}}:{{.Status}}' || true)"
        )
        out = self._run(cmd, timeout=30)
        return {"raw": out}

    def tail_file(self, path: str, lines: int = 200) -> Dict[str, Any]:
        path = (path or "").strip()
        if not path:
            raise HostToolError("path es requerido")
        cmd = f"{self._sudo_prefix()}tail -n {int(lines)} {shlex.quote(path)}"
        return {"path": path, "lines": int(lines), "content": self._run(cmd, timeout=30)}

    def journalctl(self, service: str, lines: int = 200) -> Dict[str, Any]:
        service = (service or "").strip()
        if not service:
            raise HostToolError("service es requerido")
        cmd = (
            f"{self._sudo_prefix()}journalctl -u {shlex.quote(service)} -n {int(lines)} --no-pager"
        )
        return {"service": service, "lines": int(lines), "content": self._run(cmd, timeout=45)}

    def systemctl(self, service: str, action: str) -> Dict[str, Any]:
        service = (service or "").strip()
        action = (action or "").strip().lower()
        if action not in {"start", "stop", "restart", "status", "enable", "disable"}:
            raise HostToolError("action inválida (start|stop|restart|status|enable|disable)")
        if not service:
            raise HostToolError("service es requerido")
        cmd = f"{self._sudo_prefix()}systemctl {shlex.quote(action)} {shlex.quote(service)}"
        return {"service": service, "action": action, "output": self._run(cmd, timeout=60)}

    def install_packages(self, packages: list[str]) -> Dict[str, Any]:
        pkgs = [p.strip() for p in (packages or []) if p and str(p).strip()]
        if not pkgs:
            raise HostToolError("packages es requerido")
        pkg_str = " ".join(shlex.quote(p) for p in pkgs)
        cmd = (
            f"{self._sudo_prefix()}apt-get update -y && "
            f"{self._sudo_prefix()}apt-get install -y {pkg_str}"
        )
        return {"packages": pkgs, "output": self._run(cmd, timeout=600)}

    def write_file(
        self,
        path: str,
        content: str,
        append: bool = False,
        chmod: str = "",
        mkdir_parents: bool = True,
    ) -> Dict[str, Any]:
        path = (path or "").strip()
        if not path:
            raise HostToolError("path es requerido")

        b64 = base64.b64encode((content or "").encode("utf-8")).decode("ascii")
        py = f"""
import base64, pathlib
path = {path!r}
data = base64.b64decode({b64!r}.encode("ascii"))
p = pathlib.Path(path)
{"p.parent.mkdir(parents=True, exist_ok=True)" if mkdir_parents else ""}
mode = "ab" if {bool(append)} else "wb"
with open(p, mode) as f:
    f.write(data)
"""
        # Use a heredoc to avoid shell quoting issues.
        remote = f"{self._sudo_prefix()}python3 - <<'PY'\n{py}\nPY"
        out = self._run(remote, timeout=60)

        if chmod:
            chmod = chmod.strip()
            if not chmod:
                pass
            else:
                self._run(
                    f"{self._sudo_prefix()}chmod {shlex.quote(chmod)} {shlex.quote(path)}",
                    timeout=30,
                )

        return {
            "path": path,
            "append": bool(append),
            "chmod": chmod or None,
            "output": out,
            "message": "Archivo escrito en host",
        }

    def cron_list(self, user: str = "") -> Dict[str, Any]:
        user = (user or "").strip()
        user_flag = f"-u {shlex.quote(user)} " if user else ""
        cmd = f"{self._sudo_prefix()}crontab {user_flag}-l || true"
        return {"user": user or None, "content": self._run(cmd, timeout=20)}

    def cron_add(
        self,
        schedule: str,
        command: str,
        tag: str = "tokioai",
        user: str = "",
        notify_telegram: bool = False,
        telegram_chat_id: str = "",
        notify_on_success: bool = False,
        notify_on_failure: bool = True,
    ) -> Dict[str, Any]:
        """
        Add cron job. If notify_telegram=True, creates a wrapper script that:
        1. Executes the command
        2. Sends notification to Telegram chat_id
        """
        schedule = (schedule or "").strip()
        command = (command or "").strip()
        tag = (tag or "tokioai").strip().replace("\n", " ")
        user = (user or "").strip()
        if not schedule:
            raise HostToolError("schedule es requerido. Ej: '0 9 * * *'")
        if not command:
            raise HostToolError("command es requerido")

        # If notify_telegram, create wrapper script
        if notify_telegram:
            telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            chat_id = (telegram_chat_id or os.getenv("TELEGRAM_OWNER_ID", "")).strip()
            
            if not telegram_token:
                raise HostToolError(
                    "TELEGRAM_BOT_TOKEN no configurado. Necesario para notificaciones."
                )
            if not chat_id:
                raise HostToolError(
                    "telegram_chat_id requerido o TELEGRAM_OWNER_ID en env. "
                    "Ej: params.telegram_chat_id='5719110063'"
                )

            # Create wrapper script in /opt/tokioai/
            script_path = f"/opt/tokioai/cron_{tag}.sh"
            script_content = f"""#!/usr/bin/env bash
set -uo pipefail

STATE_FILE="/tmp/tokio_cron_{tag}.state"
PREV_CODE=""
if [ -f "$STATE_FILE" ]; then
  PREV_CODE="$(cat "$STATE_FILE" 2>/dev/null || true)"
fi

set +e
{command}
EXIT_CODE=$?
set -e

TS="$(date -Is)"
echo "$EXIT_CODE" > "$STATE_FILE" 2>/dev/null || true

SHOULD_NOTIFY=0
MSG=""
if [ "$EXIT_CODE" -ne 0 ]; then
  if [ "{str(notify_on_failure).lower()}" = "true" ]; then
    SHOULD_NOTIFY=1
    MSG="❌ $TS - Tarea cron '{tag}' falló (exit code: $EXIT_CODE)"
  fi
else
  if [ "{str(notify_on_success).lower()}" = "true" ]; then
    SHOULD_NOTIFY=1
    MSG="✅ $TS - Tarea cron '{tag}' ejecutada correctamente"
  elif [ -n "$PREV_CODE" ] && [ "$PREV_CODE" != "0" ]; then
    SHOULD_NOTIFY=1
    MSG="✅ $TS - Tarea cron '{tag}' se recuperó (antes: $PREV_CODE, ahora: 0)"
  fi
fi

if [ "$SHOULD_NOTIFY" -eq 1 ]; then
  curl -sS -X POST "https://api.telegram.org/bot{telegram_token}/sendMessage" \\
      -H "Content-Type: application/json" \\
      -d "{{\\"chat_id\\":\\"{chat_id}\\",\\"text\\":\\"$MSG\\"}}" >/dev/null 2>&1 || true
fi

exit $EXIT_CODE
"""
            # Write script
            self.write_file(
                path=script_path,
                content=script_content,
                chmod="755",
                mkdir_parents=True,
            )
            # Use script in cron instead of raw command
            command = script_path

        user_flag = f"-u {shlex.quote(user)} " if user else ""
        # Idempotent: remove existing tag then add again.
        line = f"{schedule} {command} # tokio:{tag}"
        remote = (
            "set -e; "
            f"tmp=$(mktemp); "
            f"{self._sudo_prefix()}crontab {user_flag}-l 2>/dev/null | "
            f"grep -v {shlex.quote(f'# tokio:{tag}')} > \"$tmp\" || true; "
            f"echo {shlex.quote(line)} >> \"$tmp\"; "
            f"{self._sudo_prefix()}crontab {user_flag}\"$tmp\"; "
            "rm -f \"$tmp\"; "
            "echo 'cron_ok'"
        )
        out = self._run(remote, timeout=30)
        return {
            "user": user or None,
            "tag": tag,
            "entry": line,
            "notify_telegram": notify_telegram,
            "notify_on_success": notify_on_success,
            "notify_on_failure": notify_on_failure,
            "output": out,
        }

    def cron_remove(self, tag: str, user: str = "") -> Dict[str, Any]:
        tag = (tag or "").strip()
        user = (user or "").strip()
        if not tag:
            raise HostToolError("tag es requerido")
        user_flag = f"-u {shlex.quote(user)} " if user else ""
        remote = (
            "set -e; "
            f"tmp=$(mktemp); "
            f"{self._sudo_prefix()}crontab {user_flag}-l 2>/dev/null | "
            f"grep -v {shlex.quote(f'# tokio:{tag}')} > \"$tmp\" || true; "
            f"{self._sudo_prefix()}crontab {user_flag}\"$tmp\"; "
            "rm -f \"$tmp\"; "
            "echo 'cron_removed'"
        )
        out = self._run(remote, timeout=30)
        return {"user": user or None, "tag": tag, "output": out}

    def run(self, command: str) -> Dict[str, Any]:
        if not self.cfg.allow_run:
            raise HostToolError(
                "Acción 'run' está deshabilitada (HOST_CONTROL_ALLOW_RUN=false). "
                "Habilítala solo si aceptas el riesgo."
            )
        command = (command or "").strip()
        if not command:
            raise HostToolError("command es requerido")
        out = self._run(f"{self._sudo_prefix()}{command}", timeout=300)
        return {"command": command, "output": out}

    def list_web_backends(self) -> Dict[str, Any]:
        """
        Discover likely web backends without relying on ss/netstat/lsof.
        Uses /proc/net TCP tables + optional curl checks + docker published ports.
        """
        py = r"""
import json
import os
import subprocess
from pathlib import Path

def parse_proc_net(path):
    ports = set()
    p = Path(path)
    if not p.exists():
        return ports
    lines = p.read_text(errors="ignore").splitlines()[1:]
    for ln in lines:
        cols = ln.split()
        if len(cols) < 4:
            continue
        local = cols[1]
        state = cols[3]  # 0A = LISTEN
        if state != "0A":
            continue
        if ":" not in local:
            continue
        hex_port = local.split(":")[1]
        try:
            port = int(hex_port, 16)
            ports.add(port)
        except Exception:
            pass
    return ports

ports = sorted(parse_proc_net("/proc/net/tcp") | parse_proc_net("/proc/net/tcp6"))

# Prioritize common web/backend ports first
priority = [80, 443, 3000, 3001, 5000, 5173, 8000, 8080, 8100, 8123, 8443, 8888, 9000]
ordered = []
for p in priority:
    if p in ports:
        ordered.append(p)
for p in ports:
    if p not in ordered:
        ordered.append(p)

def check_http(port):
    try:
        r = subprocess.run(
            ["curl", "-sS", "-m", "3", "-I", f"http://YOUR_IP_ADDRESS:{port}/"],
            capture_output=True, text=True, timeout=5
        )
        out = (r.stdout or r.stderr or "").splitlines()
        line = out[0].strip() if out else ""
        return line
    except Exception:
        return ""

http_candidates = []
for p in ordered[:40]:
    if p < 1024 or p in priority:
        line = check_http(p)
        if line.startswith("HTTP/"):
            http_candidates.append({"port": p, "probe": line})

docker_ports = ""
try:
    d = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}} {{.Ports}}"],
        capture_output=True, text=True, timeout=8
    )
    docker_ports = (d.stdout or "").strip()
except Exception:
    docker_ports = ""

print(json.dumps({
    "listening_ports": ordered,
    "http_candidates": http_candidates,
    "docker_published_ports": docker_ports
}, ensure_ascii=False))
"""
        remote = f"{self._sudo_prefix()}python3 - <<'PY'\n{py}\nPY"
        out = self._run(remote, timeout=40)
        try:
            return json.loads(out)
        except Exception:
            return {"raw": out}

    def get_public_ip(self) -> Dict[str, Any]:
        """
        Get public IP address of the host.
        Tries multiple services: ifconfig.me, icanhazip.com, api.ipify.org
        """
        services = [
            "curl -sS --max-time 5 https://ifconfig.me/ip",
            "curl -sS --max-time 5 https://icanhazip.com",
            "curl -sS --max-time 5 https://api.ipify.org",
        ]
        
        for cmd in services:
            try:
                out = self._run(cmd, timeout=10)
                ip = out.strip()
                # Basic IP validation
                if ip and "." in ip and len(ip.split(".")) == 4:
                    return {"ip": ip, "method": cmd.split()[1]}
            except Exception:
                continue
        
        raise HostToolError("No se pudo obtener la IP pública desde ningún servicio")

    def setup_log_retention(
        self,
        days: int = 1,
        schedule: str = "30 3 * * *",
        user: str = "",
    ) -> Dict[str, Any]:
        """
        Configure automatic TokioAI log cleanup on host.
        Keeps logs for N days (default 1) to avoid disk growth.
        """
        keep_days = int(days)
        if keep_days < 1:
            keep_days = 1
        if keep_days > 30:
            keep_days = 30

        schedule = (schedule or "").strip() or "30 3 * * *"
        user = (user or "").strip()
        user_flag = f"-u {shlex.quote(user)} " if user else ""

        script_path = "/opt/tokioai/log_cleanup.sh"
        script = f"""#!/usr/bin/env bash
set -euo pipefail

KEEP_DAYS={keep_days}
TS="$(date -Is)"
echo "[tokio-log-cleanup] $TS start (keep=$KEEP_DAYS day/s)"

# Tokio logs in system log dir
find /var/log -maxdepth 1 -type f \\( -name "tokio*.log" -o -name "tokioai*.log" \\) -mtime +$KEEP_DAYS -print -exec truncate -s 0 {{}} \\; 2>/dev/null || true
find /var/log -maxdepth 1 -type f -name "tokio*.jsonl" -mtime +$KEEP_DAYS -print -delete 2>/dev/null || true

# Tokio scripts/logs
find /opt/tokioai -type f -name "*.log" -mtime +$KEEP_DAYS -print -exec truncate -s 0 {{}} \\; 2>/dev/null || true
find /opt/tokioai -type f -name "*.jsonl" -mtime +$KEEP_DAYS -print -delete 2>/dev/null || true

# Project logs (if present)
find /home/{self.cfg.user}/tokioai -type f -name "*.log" -mtime +$KEEP_DAYS -print -exec truncate -s 0 {{}} \\; 2>/dev/null || true
find /home/{self.cfg.user}/tokioai -type f -name "*.jsonl" -mtime +$KEEP_DAYS -print -delete 2>/dev/null || true

echo "[tokio-log-cleanup] $(date -Is) done"
"""
        self.write_file(
            path=script_path,
            content=script,
            chmod="755",
            mkdir_parents=True,
        )

        tag = "log_retention_cleanup"
        line = f"{schedule} {script_path} # tokio:{tag}"
        remote = (
            "set -e; "
            f"tmp=$(mktemp); "
            f"{self._sudo_prefix()}crontab {user_flag}-l 2>/dev/null | "
            f"grep -v {shlex.quote(f'# tokio:{tag}')} > \"$tmp\" || true; "
            f"echo {shlex.quote(line)} >> \"$tmp\"; "
            f"{self._sudo_prefix()}crontab {user_flag}\"$tmp\"; "
            "rm -f \"$tmp\"; "
            "echo 'log_retention_ok'"
        )
        out = self._run(remote, timeout=30)

        return {
            "keep_days": keep_days,
            "schedule": schedule,
            "script_path": script_path,
            "cron_entry": line,
            "output": out,
        }


def host_control(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Tool entry point.

    Args:
        action: One of supported actions
        params: Dict of parameters per action
    """
    params = params or {}
    mgr = HostManager()

    action = (action or "").strip().lower()
    confirm = bool(params.get("confirm", False))

    # Require explicit confirmation for dangerous actions.
    needs_confirm = action in {
        "systemctl",
        "install_packages",
        "cron_add",
        "cron_remove",
        "write_file",
        "run",
        "reboot",
    }
    if needs_confirm and not confirm:
        return json.dumps(
            {
                "ok": False,
                "action": action,
                "error": "confirm requerido para esta acción. Reintenta con params.confirm=true",
            },
            ensure_ascii=False,
        )

    try:
        if action == "health":
            result = mgr.health()
        elif action == "tail_file":
            result = mgr.tail_file(
                path=str(params.get("path", "")),
                lines=int(params.get("lines", 200)),
            )
        elif action == "journalctl":
            result = mgr.journalctl(
                service=str(params.get("service", "")),
                lines=int(params.get("lines", 200)),
            )
        elif action == "systemctl":
            result = mgr.systemctl(
                service=str(params.get("service", "")),
                action=str(params.get("service_action", params.get("action", ""))),
            )
        elif action == "install_packages":
            result = mgr.install_packages(list(params.get("packages", [])))
        elif action == "write_file":
            result = mgr.write_file(
                path=str(params.get("path", "")),
                content=str(params.get("content", "")),
                append=bool(params.get("append", False)),
                chmod=str(params.get("chmod", "")),
                mkdir_parents=bool(params.get("mkdir_parents", True)),
            )
        elif action == "cron_list":
            result = mgr.cron_list(user=str(params.get("user", "")))
        elif action == "cron_add":
            result = mgr.cron_add(
                schedule=str(params.get("schedule", "")),
                command=str(params.get("command", "")),
                tag=str(params.get("tag", "tokioai")),
                user=str(params.get("user", "")),
                notify_telegram=bool(params.get("notify_telegram", False)),
                telegram_chat_id=str(params.get("telegram_chat_id", "")),
                notify_on_success=bool(params.get("notify_on_success", False)),
                notify_on_failure=bool(params.get("notify_on_failure", True)),
            )
        elif action == "cron_remove":
            result = mgr.cron_remove(
                tag=str(params.get("tag", "")),
                user=str(params.get("user", "")),
            )
        elif action == "run":
            result = mgr.run(command=str(params.get("command", "")))
        elif action == "list_web_backends":
            result = mgr.list_web_backends()
        elif action == "get_public_ip":
            result = mgr.get_public_ip()
        elif action == "setup_log_retention":
            result = mgr.setup_log_retention(
                days=int(params.get("days", 1)),
                schedule=str(params.get("schedule", "30 3 * * *")),
                user=str(params.get("user", "")),
            )
        elif action == "reboot":
            out = mgr._run(f"{mgr._sudo_prefix()}reboot", timeout=5)
            result = {"output": out}
        else:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"acción no soportada: {action}",
                    "supported": [
                        "health",
                        "tail_file",
                        "journalctl",
                        "systemctl",
                        "install_packages",
                        "write_file",
                        "cron_list",
                        "cron_add",
                        "cron_remove",
                        "run",
                        "list_web_backends",
                        "list_web_backends",
                        "get_public_ip",
                        "setup_log_retention",
                        "reboot",
                    ],
                },
                ensure_ascii=False,
            )

        return json.dumps({"ok": True, "action": action, "result": result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "action": action, "error": str(e)}, ensure_ascii=False)


def list_web_backends() -> str:
    """
    Convenience wrapper tool to avoid LLM confusion with host_control action routing.
    """
    raw = host_control("list_web_backends", {"confirm": False})
    try:
        data = json.loads(raw)
        if data.get("ok"):
            return json.dumps(data.get("result", {}), ensure_ascii=False)
        return raw
    except Exception:
        return raw

