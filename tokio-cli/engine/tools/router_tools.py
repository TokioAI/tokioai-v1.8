"""
Router Tools - Universal SSH-based control for OpenWrt/GL.iNet routers.

Designed to be portable: configure router host/user/key in .env and use the same tool
from the agent without hardcoding vendor-specific details.
"""
import json
import os
import re
import shlex
import subprocess
from typing import Any, Dict, Optional


def _router_env() -> Dict[str, Any]:
    return {
        "host": os.getenv("ROUTER_HOST", "").strip(),
        "user": os.getenv("ROUTER_USER", "root").strip(),
        "port": int(os.getenv("ROUTER_PORT", "22")),
        "ssh_key_path": os.getenv("ROUTER_SSH_KEY_PATH", "").strip(),
        "connect_timeout": int(os.getenv("ROUTER_CONNECT_TIMEOUT", "8")),
        "cmd_timeout": int(os.getenv("ROUTER_CMD_TIMEOUT", "45")),
    }


def _require_router_host(cfg: Dict[str, Any]) -> Optional[str]:
    if not cfg["host"]:
        return (
            "ROUTER_HOST no está configurado. Define en .env:\n"
            "ROUTER_HOST=YOUR_IP_ADDRESS\nROUTER_USER=root\nROUTER_PORT=22\n"
            "ROUTER_SSH_KEY_PATH=/workspace/keys/router_id_ed25519"
        )
    return None


def _build_ssh_cmd(cfg: Dict[str, Any], remote_cmd: str) -> list:
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={cfg['connect_timeout']}",
        "-p", str(cfg["port"]),
    ]
    if cfg["ssh_key_path"]:
        cmd += ["-i", cfg["ssh_key_path"]]
    cmd += [f"{cfg['user']}@{cfg['host']}", remote_cmd]
    return cmd


def _ssh_run(cfg: Dict[str, Any], remote_cmd: str, timeout: Optional[int] = None) -> str:
    process = subprocess.run(
        _build_ssh_cmd(cfg, remote_cmd),
        capture_output=True,
        text=True,
        timeout=timeout or cfg["cmd_timeout"]
    )
    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    if process.returncode != 0:
        raise RuntimeError(stderr or stdout or f"SSH command failed ({process.returncode})")
    return stdout


def _validate_ip(ip: str) -> bool:
    return bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip or ""))


def _count_matches(text: str, pattern: str) -> int:
    try:
        return len(re.findall(pattern, text or "", flags=re.IGNORECASE))
    except Exception:
        return 0


def router_control(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Universal router control tool.

    Supported actions:
    - health
    - firewall_status
    - wifi_status
    - detect_attack_signals
    - recover_wifi
    - add_block_ip (params.ip required)
    - remove_block_ip (params.ip required)
    - run (params.command required, advanced users)
    - wifi_defense_status
    - wifi_defense_harden (params.confirm=true required)
    """
    params = params or {}
    cfg = _router_env()
    err = _require_router_host(cfg)
    if err:
        return json.dumps({"success": False, "error": err}, ensure_ascii=False)

    try:
        if action == "health":
            result = {
                "uname": _ssh_run(cfg, "uname -a"),
                "uptime": _ssh_run(cfg, "uptime"),
            }

        elif action == "firewall_status":
            result = {
                "uci_firewall": _ssh_run(cfg, "uci show firewall || true"),
                "iptables_filter": _ssh_run(cfg, "iptables -L -n -v --line-numbers || true"),
                "iptables_nat": _ssh_run(cfg, "iptables -t nat -L -n -v --line-numbers || true"),
            }

        elif action == "wifi_status":
            result = {
                "wifi_info": _ssh_run(cfg, "iwinfo || true"),
                "interfaces": _ssh_run(cfg, "ip a || ifconfig || true"),
                "recent_wifi_logs": _ssh_run(
                    cfg,
                    "logread | tail -n 200 | grep -Ei 'wifi|wlan|hostapd|deauth|assoc|disassoc|auth' || true"
                ),
            }

        elif action == "detect_attack_signals":
            result = {
                "drop_or_scan_logs": _ssh_run(
                    cfg,
                    "logread | tail -n 300 | grep -Ei 'DROP|REJECT|scan|flood|DoS|DDoS|SYN' || true"
                ),
                "auth_events": _ssh_run(
                    cfg,
                    "logread | tail -n 300 | grep -Ei 'auth|deauth|wpa|bruteforce|invalid' || true"
                ),
                "conntrack": _ssh_run(
                    cfg,
                    "cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null; "
                    "cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || true"
                ),
            }

        elif action == "wifi_defense_status":
            raw = _ssh_run(
                cfg,
                "logread | tail -n 500 | grep -Ei 'deauth|disassoc|assoc|auth|flood|scan|brute|invalid|wpa|handshake|probe' || true",
            )
            deauth_count = _count_matches(raw, r"deauth|disassoc")
            scan_count = _count_matches(raw, r"scan|probe")
            brute_count = _count_matches(raw, r"brute|invalid|auth fail|wrong password")
            risk = "low"
            if deauth_count >= 8 or brute_count >= 8:
                risk = "high"
            elif deauth_count >= 3 or scan_count >= 5 or brute_count >= 3:
                risk = "medium"

            result = {
                "risk_level": risk,
                "metrics": {
                    "deauth_or_disassoc_events": deauth_count,
                    "scan_or_probe_events": scan_count,
                    "bruteforce_or_invalid_auth_events": brute_count,
                },
                "recent_wifi_security_logs": raw,
                "recommendation": (
                    "Ejecuta wifi_defense_harden con confirm=true para aplicar mitigaciones base "
                    "y revisa canal/potencia WPA2/WPA3."
                ),
            }

        elif action == "wifi_defense_harden":
            if not bool(params.get("confirm", False)):
                raise ValueError("wifi_defense_harden requiere params.confirm=true")
            # Conservative hardening for OpenWrt/GL.iNet (safe defaults).
            result = _ssh_run(
                cfg,
                "uci set wireless.@wifi-iface[0].wpa_disable_eapol_key_retries='0' 2>/dev/null || true; "
                "uci set firewall.@defaults[0].drop_invalid='1' 2>/dev/null || true; "
                "uci commit wireless; uci commit firewall; "
                "wifi reload 2>/dev/null || wifi; "
                "/etc/init.d/firewall reload",
                timeout=max(90, cfg["cmd_timeout"]),
            )

        elif action == "recover_wifi":
            result = _ssh_run(
                cfg,
                "wifi down; sleep 2; wifi up; /etc/init.d/network restart",
                timeout=max(90, cfg["cmd_timeout"]),
            )

        elif action == "add_block_ip":
            ip = str(params.get("ip", "")).strip()
            if not _validate_ip(ip):
                raise ValueError("IP inválida para add_block_ip")
            ip_escaped = shlex.quote(ip)
            result = _ssh_run(
                cfg,
                "uci add firewall rule; "
                "uci set firewall.@rule[-1].name='tokio_block_ip'; "
                "uci set firewall.@rule[-1].src='wan'; "
                f"uci set firewall.@rule[-1].src_ip={ip_escaped}; "
                "uci set firewall.@rule[-1].target='DROP'; "
                "uci commit firewall; "
                "/etc/init.d/firewall reload",
                timeout=max(60, cfg["cmd_timeout"]),
            )

        elif action == "remove_block_ip":
            ip = str(params.get("ip", "")).strip()
            if not _validate_ip(ip):
                raise ValueError("IP inválida para remove_block_ip")
            ip_escaped = shlex.quote(ip)
            result = _ssh_run(
                cfg,
                "for i in $(uci show firewall | grep \"src_ip\" | grep "
                + ip_escaped
                + " | cut -d'=' -f1 | sed 's/\\.src_ip//'); do "
                + "uci delete $i; "
                + "done; "
                + "uci commit firewall; /etc/init.d/firewall reload",
                timeout=max(60, cfg["cmd_timeout"]),
            )

        elif action == "run":
            # Advanced/raw command mode for power users
            cmd = str(params.get("command", "")).strip()
            if not cmd:
                raise ValueError("params.command es obligatorio para action=run")
            result = _ssh_run(cfg, cmd, timeout=cfg["cmd_timeout"])

        else:
            return json.dumps(
                {
                    "success": False,
                    "error": (
                        "Acción no soportada. Usa: health, firewall_status, wifi_status, "
                        "detect_attack_signals, wifi_defense_status, wifi_defense_harden, "
                        "recover_wifi, add_block_ip, remove_block_ip, run"
                    ),
                },
                ensure_ascii=False,
            )

        return json.dumps({"success": True, "action": action, "result": result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "action": action, "error": str(e)}, ensure_ascii=False)
