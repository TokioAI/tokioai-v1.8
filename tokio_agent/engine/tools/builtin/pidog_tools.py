"""
TokioAI PiDog Robot Tools — Control via Safety Proxy on Raspberry Pi.

All commands go through the PiDog proxy (port 5001) on the robot's Raspi.
The proxy handles safety limits, auto-stop, and hardware abstraction.

Actions:
  - status: Full robot status (ready, patrol, interactive, last_action)
  - sensors: Read ultrasonic distance + touch sensor
  - sounds: List available sound effects
  - actions: List available do_actions and presets
  - do_action: Execute official SunFounder action (stand, sit, forward, backward, etc.)
  - preset: Execute preset action (bark, howling, hand_shake, high_five, etc.)
  - speak: Play a sound effect (single_bark_1, howling, angry, etc.)
  - wake_up: Full wake-up sequence (stretch, twist, pant, wag tail)
  - patrol: Start autonomous patrol with obstacle avoidance
  - stop_patrol: Stop patrol mode
  - interactive: Start interactive mode (touch reactions, obstacle detection)
  - stop_interactive: Stop interactive mode
  - head: Move head (yaw, roll, pitch)
  - tail: Move tail (angle)
  - rgb: Control RGB LED strip (mode, color)
  - stop: Emergency stop all movement and modes
  - snapshot: Take a photo with PiDog camera
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

PIDOG_LAN = os.getenv("PIDOG_LAN_IP", "192.168.8.210")
PIDOG_PORT = int(os.getenv("PIDOG_PORT", "5001"))
TIMEOUT = 10.0

_TIMEOUT_MAP = {
    "wake_up": 30.0,
    "patrol": 5.0,       # Returns immediately, runs in background
    "interactive": 5.0,   # Returns immediately, runs in background
    "do_action": 20.0,
    "preset": 20.0,
    "speak": 10.0,
    "snapshot": 15.0,
}


def _get_base_url() -> str:
    url = os.getenv("PIDOG_API_URL", "")
    if url:
        return url
    return f"http://{PIDOG_LAN}:{PIDOG_PORT}"


def _enrich_error(e: Exception, path: str) -> str:
    err = str(e)
    if "Connection refused" in err or "connect" in err.lower():
        return (f"PiDog proxy no responde ({path}). "
                "Posibles causas: 1) Raspberry Pi del PiDog apagada. "
                "2) Servicio pidog_proxy no iniciado. "
                "3) IP incorrecta — verificar PIDOG_LAN_IP (actual: {PIDOG_LAN}).")
    if "timeout" in err.lower():
        return f"Timeout en PiDog proxy ({path}). El robot puede estar ejecutando un comando largo."
    return f"Error PiDog: {err}"


async def _get(path: str, timeout: float = None) -> dict:
    base = _get_base_url()
    try:
        async with httpx.AsyncClient(timeout=timeout or TIMEOUT) as client:
            r = await client.get(f"{base}{path}")
            if r.headers.get("content-type", "").startswith("image/"):
                return {"snapshot": True, "size": len(r.content),
                        "content_type": r.headers["content-type"]}
            return r.json()
    except Exception as e:
        return {"error": _enrich_error(e, path)}


async def _post(path: str, data: dict = None, timeout: float = None) -> dict:
    base = _get_base_url()
    try:
        async with httpx.AsyncClient(timeout=timeout or TIMEOUT) as client:
            r = await client.post(f"{base}{path}", json=data or {})
            return r.json()
    except Exception as e:
        return {"error": _enrich_error(e, path)}


async def pidog_control(action: str, params: dict = None) -> str:
    """Unified PiDog robot control handler."""
    params = params or {}
    timeout = _TIMEOUT_MAP.get(action, TIMEOUT)

    # ── Status ──
    if action == "status":
        r = await _get("/status", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        ready_icon = "✅" if r.get("ready") else "❌"
        lines = [
            "🐕 PiDog Status",
            f"  Hardware: {ready_icon} {'ready' if r.get('ready') else 'not ready'}",
            f"  Last action: {r.get('last_action', '?')}",
            f"  Patrol: {'🟢 running' if r.get('patrol') else '⚪ off'}",
            f"  Interactive: {'🟢 running' if r.get('interactive') else '⚪ off'}",
            f"  Version: {r.get('version', '?')}",
        ]
        # Also get sensors
        s = await _get("/sensors", timeout=5)
        if not s.get("error"):
            lines.append(f"  Distance: {s.get('distance_cm', -1)} cm")
            lines.append(f"  Touch: {s.get('touch', 'N')}")
        return "\n".join(lines)

    elif action == "sensors":
        r = await _get("/sensors", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return (f"📡 PiDog Sensors\n"
                f"  Distancia: {r.get('distance_cm', -1)} cm\n"
                f"  Touch: {r.get('touch', 'N')}")

    elif action == "sounds":
        r = await _get("/sounds", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        sounds = r.get("sounds", [])
        return f"🔊 Sonidos disponibles ({len(sounds)}):\n  " + ", ".join(sounds)

    elif action == "actions":
        r = await _get("/actions", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        do_acts = r.get("do_actions", [])
        presets = r.get("presets", [])
        return (f"🎬 Acciones disponibles:\n"
                f"  do_action: {', '.join(do_acts)}\n"
                f"  preset: {', '.join(presets)}")

    # ── Movement Actions ──
    elif action == "do_action":
        name = params.get("name", "stand")
        steps = params.get("steps", params.get("step_count", 10))
        speed = params.get("speed")
        data = {"name": name, "steps": steps}
        if speed:
            data["speed"] = speed
        r = await _post("/action", data, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"🐕 Accion: {name} (steps={r.get('steps', steps)}, speed={r.get('speed', '?')})"

    elif action == "preset":
        name = params.get("name", "bark")
        r = await _post("/preset", {"name": name}, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"🎭 Preset: {name} — {r.get('status', 'done')}"

    elif action in ("speak", "sound"):
        name = params.get("name", params.get("sound", "single_bark_1"))
        r = await _post("/speak", {"name": name}, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"🔊 Sonido: {name} — {r.get('status', 'played')}"

    # ── Complex Sequences ──
    elif action == "wake_up":
        r = await _post("/wake_up", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return "🌅 PiDog wake up sequence completada!"

    elif action in ("patrol", "patrullar"):
        r = await _post("/patrol", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return "🚨 PiDog patrullando con deteccion de obstaculos!"

    elif action == "stop_patrol":
        r = await _post("/stop_patrol", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return "🛑 Patrulla detenida"

    elif action in ("interactive", "interactivo"):
        duration = params.get("duration", 30)
        r = await _post("/interactive", {"duration": duration}, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"🤝 Modo interactivo: {duration}s (reacciona al tacto y obstaculos)"

    elif action == "stop_interactive":
        r = await _post("/stop_interactive", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return "🛑 Modo interactivo detenido"

    # ── Head/Tail/RGB ──
    elif action in ("head", "cabeza"):
        yaw = params.get("yaw", 0)
        roll = params.get("roll", 0)
        pitch = params.get("pitch", -30)
        r = await _post("/head", {"yaw": yaw, "roll": roll, "pitch": pitch}, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"🐕 Cabeza: yaw={yaw}, roll={roll}, pitch={pitch}"

    elif action in ("tail", "cola"):
        angle = params.get("angle", 0)
        r = await _post("/tail", {"angle": angle}, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"🐕 Cola: {angle}°"

    elif action == "rgb":
        mode = params.get("mode", "breath")
        color = params.get("color", "blue")
        r = await _post("/rgb", {"mode": mode, "color": color}, timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"💡 RGB: {mode} {color}"

    # ── Stop ──
    elif action in ("stop", "parar", "kill", "emergencia"):
        r = await _post("/stop", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        return "🛑 PiDog detenido — todo parado"

    # ── Snapshot ──
    elif action in ("snapshot", "foto"):
        r = await _get("/snapshot", timeout=timeout)
        if r.get("error"):
            return f"Error: {r['error']}"
        if r.get("snapshot"):
            return f"📸 Foto PiDog tomada ({r.get('size', 0)} bytes)"
        return f"📸 Snapshot: {r}"

    else:
        return (f"Accion desconocida: {action}. "
                "Acciones: status, sensors, sounds, actions, do_action, preset, speak, "
                "wake_up, patrol, stop_patrol, interactive, stop_interactive, "
                "head, tail, rgb, stop, snapshot")
