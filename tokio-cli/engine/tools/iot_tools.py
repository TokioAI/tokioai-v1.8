"""
IoT Integration Tools - Alexa, Smart Plugs, Vacuum, Lights
Requires: API keys and device configuration
"""
import os
import json
import requests
import logging
import time
import colorsys
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

_DEVICE_MEMORY_PATH = Path(
    os.getenv("TOKIO_DEVICE_MEMORY_PATH", "/workspace/cli/ha_entities_cache.json")
)
_DEVICE_MEMORY_CACHE: Dict = {"updated_at": "", "entities": {}, "aliases": {}}
_PG_CONN = None
_PG_READY = False


def _pg_enabled() -> bool:
    return os.getenv("TOKIO_IOT_PG_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def _pg_connect():
    global _PG_CONN
    if not _pg_enabled():
        return None
    if _PG_CONN is not None:
        return _PG_CONN
    try:
        import psycopg2
        _PG_CONN = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "soc_ai"),
            user=os.getenv("POSTGRES_USER", "soc_user"),
            password=os.getenv("POSTGRES_PASSWORD", "changeme_please"),
            connect_timeout=5,
        )
        _PG_CONN.autocommit = True
        return _PG_CONN
    except Exception as e:
        logger.debug(f"PostgreSQL no disponible para memoria IoT: {e}")
        _PG_CONN = None
        return None


def _pg_ensure_schema() -> None:
    global _PG_READY
    if _PG_READY:
        return
    conn = _pg_connect()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tokio_device_memory (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.close()
        _PG_READY = True
    except Exception as e:
        logger.debug(f"No pude crear schema tokio_device_memory: {e}")


def _pg_load_device_memory() -> Optional[Dict[str, Any]]:
    _pg_ensure_schema()
    conn = _pg_connect()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM tokio_device_memory WHERE key=%s", ("ha_entities_cache",))
        row = cur.fetchone()
        cur.close()
        if not row or not row[0]:
            return None
        data = row[0]
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.debug(f"No pude leer memoria IoT desde PostgreSQL: {e}")
    return None


def _pg_save_device_memory(data: Dict[str, Any]) -> bool:
    _pg_ensure_schema()
    conn = _pg_connect()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tokio_device_memory(key, value, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """,
            ("ha_entities_cache", json.dumps(data, ensure_ascii=False)),
        )
        cur.close()
        return True
    except Exception as e:
        logger.debug(f"No pude guardar memoria IoT en PostgreSQL: {e}")
        return False


def _load_device_memory() -> Dict:
    global _DEVICE_MEMORY_CACHE
    try:
        pg_data = _pg_load_device_memory()
        if isinstance(pg_data, dict) and pg_data:
            _DEVICE_MEMORY_CACHE = pg_data
            return _DEVICE_MEMORY_CACHE
    except Exception:
        pass
    try:
        if _DEVICE_MEMORY_PATH.exists():
            data = json.loads(_DEVICE_MEMORY_PATH.read_text())
            if isinstance(data, dict):
                _DEVICE_MEMORY_CACHE = data
    except Exception:
        # Keep in-memory fallback if file is corrupted/unavailable.
        pass
    return _DEVICE_MEMORY_CACHE


def _save_device_memory() -> None:
    persisted_pg = False
    try:
        persisted_pg = _pg_save_device_memory(_DEVICE_MEMORY_CACHE)
    except Exception:
        persisted_pg = False
    try:
        _DEVICE_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEVICE_MEMORY_PATH.write_text(json.dumps(_DEVICE_MEMORY_CACHE, ensure_ascii=False, indent=2))
    except Exception as e:
        if not persisted_pg:
            logger.debug(f"Could not persist HA entity cache: {e}")


def _remember_entity(entity_id: str, friendly_name: str = "", domain: str = "", state: str = "") -> None:
    mem = _load_device_memory()
    entity_id = (entity_id or "").strip().lower()
    if not entity_id or "." not in entity_id:
        return
    if not domain:
        domain = entity_id.split(".", 1)[0]
    aliases = mem.setdefault("aliases", {})
    entities = mem.setdefault("entities", {})
    entities[entity_id] = {
        "entity_id": entity_id,
        "friendly_name": friendly_name or "",
        "domain": domain,
        "state": state or "",
        "last_seen": datetime.now().isoformat(),
    }

    # Useful aliases for long-term recall across restarts.
    slug = entity_id.split(".", 1)[1]
    aliases[f"{domain}:{slug}"] = entity_id
    aliases[slug] = entity_id
    if friendly_name:
        lowered = friendly_name.strip().lower()
        aliases[f"{domain}:{lowered}"] = entity_id
        aliases[lowered] = entity_id
    mem["updated_at"] = datetime.now().isoformat()
    _save_device_memory()


def _resolve_from_memory(domain: str, name_or_entity_id: str) -> Optional[str]:
    mem = _load_device_memory()
    aliases = mem.get("aliases", {}) if isinstance(mem, dict) else {}
    entities = mem.get("entities", {}) if isinstance(mem, dict) else {}

    raw = (name_or_entity_id or "").strip().lower()
    if not raw:
        return None
    if raw in entities:
        return raw
    if raw.startswith(f"{domain}."):
        return raw

    domain_key = f"{domain}:{raw}"
    if domain_key in aliases:
        return str(aliases[domain_key]).lower()
    if raw in aliases:
        resolved = str(aliases[raw]).lower()
        if resolved.startswith(f"{domain}."):
            return resolved
    return None

_ALEXA_DEFAULT_DEVICE = "Jarvis"
_ALEXA_GENERIC_NAMES = {
    "default", "alexa", "echo", "eco", "", "none",
    "nombre_del_dispositivo_alexa", "dispositivo", "device"
}


def _normalize_device_name(device_name: Optional[str]) -> str:
    if not device_name:
        return _ALEXA_DEFAULT_DEVICE
    clean = device_name.strip()
    if clean.lower() in _ALEXA_GENERIC_NAMES:
        return _ALEXA_DEFAULT_DEVICE
    return clean


def _ha_config() -> Tuple[str, str]:
    base_url = os.getenv("HOME_ASSISTANT_URL", "http://host.docker.internal:8123").rstrip("/")
    token = os.getenv("HOME_ASSISTANT_TOKEN", "").strip()
    return base_url, token


def _ha_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _ha_request(method: str, path: str, json_payload: Optional[Dict] = None, timeout: int = 15, retries: int = 2):
    base_url, token = _ha_config()
    if not token:
        return None, "HOME_ASSISTANT_TOKEN no configurado"
    url = f"{base_url}{path}"
    attempt = 0
    while attempt <= retries:
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=_ha_headers(token),
                json=json_payload,
                timeout=timeout,
            )
            return response, ""
        except Exception as e:
            if attempt >= retries:
                return None, str(e)
            time.sleep(0.5 * (attempt + 1))
        finally:
            attempt += 1
    return None, "error de conexión no especificado"


def _ha_post(service: str, payload: Dict, timeout: int = 15) -> Tuple[bool, str]:
    response, err = _ha_request("POST", f"/api/services/{service}", json_payload=payload, timeout=timeout, retries=2)
    if response is None:
        if "HOME_ASSISTANT_TOKEN no configurado" in err:
            return False, (
                "❌ HOME_ASSISTANT_TOKEN no configurado. "
                "Crea un Long-Lived Access Token en Home Assistant y configúralo en .env."
            )
        return False, err
    if response.status_code == 200:
        return True, response.text
    return False, f"HTTP {response.status_code}: {response.text[:400]}"


def _ha_get_state(entity_id: str, timeout: int = 10) -> Tuple[bool, str, Dict]:
    response, err = _ha_request("GET", f"/api/states/{entity_id}", timeout=timeout, retries=2)
    if response is None:
        return False, err, {}
    if response.status_code == 200:
        data = response.json()
        return True, "", data
    return False, f"HTTP {response.status_code}: {response.text[:300]}", {}


def _ha_list_states(timeout: int = 15) -> Tuple[bool, str, List[Dict]]:
    """List all Home Assistant entity states."""
    response, err = _ha_request("GET", "/api/states", timeout=timeout, retries=2)
    if response is None:
        return False, err, []
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, list):
            # Refresh persistent memory cache from Home Assistant inventory.
            for st in data:
                entity_id = str(st.get("entity_id", "")).strip().lower()
                if not entity_id or "." not in entity_id:
                    continue
                domain = entity_id.split(".", 1)[0]
                friendly = str(st.get("attributes", {}).get("friendly_name", "")).strip()
                state = str(st.get("state", "")).strip()  # Get current state
                _remember_entity(entity_id, friendly_name=friendly, domain=domain, state=state)
            return True, "", data
        return False, "Formato inesperado desde /api/states", []
    return False, f"HTTP {response.status_code}: {response.text[:300]}", []


def _resolve_ha_entity(domain: str, name_or_entity_id: str) -> str:
    """
    Resolve a Home Assistant entity_id from either:
    - a real entity_id (e.g. light.smart_bulb)
    - a friendly name (e.g. "Smart Bulb")
    - a slug (e.g. "smart_bulb")
    """
    domain = (domain or "").strip().lower()
    raw = (name_or_entity_id or "").strip()
    if not domain:
        return raw
    if not raw:
        return f"{domain}.unknown"

    lowered = raw.lower()
    if lowered.startswith(f"{domain}."):
        _remember_entity(lowered, domain=domain)
        return lowered

    slug = lowered.replace(" ", "_")
    direct = f"{domain}.{slug}"

    # 0) Resolve from persistent memory first
    memory_match = _resolve_from_memory(domain, lowered)
    if memory_match:
        return memory_match

    ok, _, states = _ha_list_states()
    if not ok:
        return direct

    # 1) Exact entity_id match
    for st in states:
        eid = str(st.get("entity_id", "")).lower()
        if eid == direct:
            friendly = str(st.get("attributes", {}).get("friendly_name", "")).strip()
            state = str(st.get("state", "")).strip()
            _remember_entity(eid, friendly_name=friendly, domain=domain, state=state)
            return eid

    # 2) Exact friendly_name match
    for st in states:
        eid = str(st.get("entity_id", "")).lower()
        if not eid.startswith(f"{domain}."):
            continue
        friendly = str(st.get("attributes", {}).get("friendly_name", "")).strip().lower()
        if friendly and friendly == lowered:
            state = str(st.get("state", "")).strip()
            _remember_entity(eid, friendly_name=friendly, domain=domain, state=state)
            return eid

    # 3) Contains match (friendly name)
    for st in states:
        eid = str(st.get("entity_id", "")).lower()
        if not eid.startswith(f"{domain}."):
            continue
        friendly = str(st.get("attributes", {}).get("friendly_name", "")).strip().lower()
        if friendly and lowered in friendly:
            state = str(st.get("state", "")).strip()
            _remember_entity(eid, friendly_name=friendly, domain=domain, state=state)
            return eid

    # 4) Suffix match (entity_id contains slug)
    for st in states:
        eid = str(st.get("entity_id", "")).lower()
        if not eid.startswith(f"{domain}."):
            continue
        if eid.endswith(f".{slug}") or f"_{slug}" in eid or f".{slug}_" in eid:
            friendly = str(st.get("attributes", {}).get("friendly_name", "")).strip()
            state = str(st.get("state", "")).strip()
            _remember_entity(eid, friendly_name=friendly, domain=domain, state=state)
            return eid

    # Persist direct guess as alias candidate for future interactions.
    _remember_entity(direct, domain=domain)
    return direct


def _resolve_alexa_entity(device_name: str) -> str:
    """
    Resolve Home Assistant entity_id for Alexa device.
    Tries exact slug first, then searches media_player states.
    """
    name = _normalize_device_name(device_name)
    slug = name.lower().replace(" ", "_")
    direct_entity = f"media_player.{slug}"

    _base_url, token = _ha_config()
    if not token:
        return direct_entity

    ok, _err, states = _ha_list_states(timeout=10)
    if not ok:
        return direct_entity

    candidates: List[Dict] = []
    for state in states:
        entity_id = state.get("entity_id", "")
        if entity_id.startswith("media_player.") and "alexa" in entity_id:
            candidates.append(state)
        elif entity_id.startswith("media_player.") and state.get("attributes", {}).get("friendly_name"):
            # Keep all media players as fallback, then prioritize name matching below.
            candidates.append(state)

    # 1) Exact entity match
    for c in candidates:
        if c.get("entity_id") == direct_entity:
            return direct_entity

    # 2) Friendly name match
    lowered = name.lower()
    for c in candidates:
        friendly = str(c.get("attributes", {}).get("friendly_name", "")).lower()
        if friendly == lowered:
            return c.get("entity_id", direct_entity)

    # 3) Contains match
    for c in candidates:
        friendly = str(c.get("attributes", {}).get("friendly_name", "")).lower()
        if lowered in friendly:
            return c.get("entity_id", direct_entity)

    return direct_entity


def _wake_alexa_entity(entity_id: str) -> None:
    # Best-effort "despertar" cuando Alexa/HA queda en pausa o unavailable.
    _ha_post("media_player/turn_on", {"entity_id": entity_id}, timeout=10)
    _ha_post("media_player/volume_set", {"entity_id": entity_id, "volume_level": 0.35}, timeout=10)
    time.sleep(1.0)


def alexa_speak(text: str, device_name: str = "default") -> str:
    """Make Alexa speak text using Home Assistant + Alexa Media Player."""
    entity_id = _resolve_alexa_entity(device_name)

    # First choice: notify service from alexa_media
    ok, detail = _ha_post(
        "notify/alexa_media",
        {
            "message": text,
            "target": [entity_id],
            "data": {"type": "tts"},
        },
    )
    if ok:
        return f"✅ Mensaje enviado por Home Assistant a {entity_id}: '{text}'"

    # Fallback: media_player.play_media
    ok2, detail2 = _ha_post(
        "media_player/play_media",
        {
            "entity_id": entity_id,
            "media_content_id": text,
            "media_content_type": "tts",
        },
    )
    if ok2:
        return f"✅ TTS enviado por Home Assistant a {entity_id}: '{text}'"

    return (
        "❌ No pude enviar TTS a Alexa vía Home Assistant.\n"
        f"- notify/alexa_media: {detail}\n"
        f"- media_player/play_media: {detail2}"
    )

def alexa_weather(device_name: str = "default", location: str = "") -> str:
    """Ask Alexa weather by sending a voice-like command via Home Assistant."""
    target = location.strip() if location else "tu ubicación"
    phrase = f"¿Cuál es el clima en {target}?"
    return alexa_speak(text=phrase, device_name=device_name)

def alexa_play_music(query: str, device_name: str = "default") -> str:
    """Play music on Alexa via Home Assistant media_player service."""
    entity_id = _resolve_alexa_entity(device_name)

    _wake_alexa_entity(entity_id)
    _, _, before_data = _ha_get_state(entity_id)
    before_state = before_data.get("state", "unknown")
    before_title = str(before_data.get("attributes", {}).get("media_title", "")).strip().lower()
    before_called = str(before_data.get("attributes", {}).get("last_called_summary", "")).strip().lower()

    attempts = [
        ("custom", f"play {query}", "comando remoto en inglés"),
        ("custom", f"reproduce {query} en Amazon Music", "comando remoto en español"),
        ("music", query, "búsqueda nativa de música"),
    ]
    errors: List[str] = []

    for media_type, media_id, label in attempts:
        ok, detail = _ha_post(
            "media_player/play_media",
            {
                "entity_id": entity_id,
                "media_content_type": media_type,
                "media_content_id": media_id,
            },
        )
        if not ok:
            errors.append(f"{label}: {detail}")
            continue

        # Verificación: esperamos que el estado pase a 'playing'
        time.sleep(3)
        st_ok, st_err, after_data = _ha_get_state(entity_id)
        if st_ok:
            after_state = after_data.get("state", "unknown")
            attrs = after_data.get("attributes", {})
            after_title = str(attrs.get("media_title", "")).strip().lower()
            after_called = str(attrs.get("last_called_summary", "")).strip().lower()

            # Confirmación fuerte: estado reproduciendo
            if after_state == "playing":
                return f"✅ Reproducción iniciada en {entity_id}: '{query}' ({label})."

            # Confirmación suave: cambió pista o resumen de último comando
            if after_title and after_title != before_title:
                return (
                    f"✅ Comando de música aceptado en {entity_id} ({label}). "
                    f"Se detectó cambio de pista: '{attrs.get('media_title', '')}'."
                )
            if after_called and after_called != before_called:
                return (
                    f"✅ Comando de música aceptado en {entity_id} ({label}). "
                    f"Resumen detectado: '{attrs.get('last_called_summary', '')}'."
                )

        if st_ok:
            errors.append(
                f"{label}: comando aceptado pero estado {before_state} -> {after_state}"
            )
            # Evitamos falso negativo: el comando se envió aunque HA no marque 'playing' enseguida.
            return (
                f"⚠️ Envié el comando de reproducción a {entity_id} ({label}), "
                f"pero no pude confirmar inicio inmediato (estado {before_state} -> {after_state})."
            )
        else:
            errors.append(f"{label}: no pude verificar estado ({st_err})")
            return (
                f"⚠️ Envié el comando de reproducción a {entity_id} ({label}), "
                "pero no pude verificar el estado del dispositivo en Home Assistant."
            )

    return (
        "❌ No pude confirmar reproducción en Alexa.\n"
        + "\n".join(f"- {e}" for e in errors[-3:])
    )


def alexa_status(device_name: str = "default") -> str:
    """Get Alexa device status (state, volume, media info) - SILENT, no TTS."""
    entity_id = _resolve_alexa_entity(device_name)
    ok, err, data = _ha_get_state(entity_id)
    
    if not ok:
        return f"❌ No pude obtener estado de {entity_id}: {err}"
    
    state = data.get("state", "unknown")
    attrs = data.get("attributes", {})
    
    volume = attrs.get("volume_level", 0)
    volume_pct = int(volume * 100) if volume else 0
    is_muted = attrs.get("is_volume_muted", False)
    media_title = attrs.get("media_title", "")
    media_artist = attrs.get("media_artist", "")
    media_content_type = attrs.get("media_content_type", "")
    
    result = f"""📊 Estado de {entity_id}:
Estado: {state}
Volumen: {volume_pct}% {"(silenciado)" if is_muted else ""}"""
    
    if media_title:
        result += f"\nReproduciendo: {media_title}"
        if media_artist:
            result += f" - {media_artist}"
    
    return result


def alexa_set_volume(device_name: str = "default", level: int = 50) -> str:
    """Set Alexa volume (0-100) - SILENT, no TTS."""
    entity_id = _resolve_alexa_entity(device_name)
    
    # Clamp to 0-100
    level = max(0, min(100, int(level)))
    volume_level = level / 100.0
    
    ok, detail = _ha_post(
        "media_player/volume_set",
        {
            "entity_id": entity_id,
            "volume_level": volume_level,
        },
    )
    
    if ok:
        return f"✅ Volumen de {entity_id} ajustado a {level}%"
    return f"❌ Error ajustando volumen: {detail}"


def alexa_volume_up(device_name: str = "default", step: int = 10) -> str:
    """Increase Alexa volume by step (default 10%) - SILENT, no TTS."""
    entity_id = _resolve_alexa_entity(device_name)
    
    # Get current volume
    ok, err, data = _ha_get_state(entity_id)
    if not ok:
        return f"❌ No pude obtener volumen actual: {err}"
    
    current_volume = data.get("attributes", {}).get("volume_level", 0.5)
    current_pct = int(current_volume * 100)
    new_pct = min(100, current_pct + int(step))
    new_volume = new_pct / 100.0
    
    ok, detail = _ha_post(
        "media_player/volume_set",
        {
            "entity_id": entity_id,
            "volume_level": new_volume,
        },
    )
    
    if ok:
        return f"✅ Volumen de {entity_id}: {current_pct}% → {new_pct}%"
    return f"❌ Error subiendo volumen: {detail}"


def alexa_volume_down(device_name: str = "default", step: int = 10) -> str:
    """Decrease Alexa volume by step (default 10%) - SILENT, no TTS."""
    entity_id = _resolve_alexa_entity(device_name)
    
    # Get current volume
    ok, err, data = _ha_get_state(entity_id)
    if not ok:
        return f"❌ No pude obtener volumen actual: {err}"
    
    current_volume = data.get("attributes", {}).get("volume_level", 0.5)
    current_pct = int(current_volume * 100)
    new_pct = max(0, current_pct - int(step))
    new_volume = new_pct / 100.0
    
    ok, detail = _ha_post(
        "media_player/volume_set",
        {
            "entity_id": entity_id,
            "volume_level": new_volume,
        },
    )
    
    if ok:
        return f"✅ Volumen de {entity_id}: {current_pct}% → {new_pct}%"
    return f"❌ Error bajando volumen: {detail}"


def alexa_mute(device_name: str = "default", mute: bool = True) -> str:
    """Mute/unmute Alexa - SILENT, no TTS."""
    entity_id = _resolve_alexa_entity(device_name)
    
    ok, detail = _ha_post(
        "media_player/volume_mute",
        {
            "entity_id": entity_id,
            "is_volume_muted": mute,
        },
    )
    
    if ok:
        action = "silenciado" if mute else "activado sonido"
        return f"✅ {entity_id} {action}"
    return f"❌ Error cambiando mute: {detail}"


# ============================================================================
# GENERIC HOME ASSISTANT CONTROL (Switches, Lights, Vacuums, etc.)
# ============================================================================

_COLOR_NAME_TO_RGB = {
    # Spanish
    "rojo": [255, 0, 0],
    "verde": [0, 255, 0],
    "azul": [0, 0, 255],
    "amarillo": [255, 255, 0],
    "naranja": [255, 165, 0],
    "violeta": [128, 0, 128],
    "morado": [128, 0, 128],
    "rosa": [255, 105, 180],
    "magenta": [255, 0, 255],
    "cian": [0, 255, 255],
    "celeste": [0, 255, 255],
    "blanco": [255, 255, 255],
    # English
    "red": [255, 0, 0],
    "green": [0, 255, 0],
    "blue": [0, 0, 255],
    "yellow": [255, 255, 0],
    "orange": [255, 165, 0],
    "purple": [128, 0, 128],
    "pink": [255, 105, 180],
    "magenta": [255, 0, 255],
    "cyan": [0, 255, 255],
    "white": [255, 255, 255],
}


def _rgb_to_hs(rgb: List[int]) -> List[float]:
    r = max(0, min(255, int(rgb[0]))) / 255.0
    g = max(0, min(255, int(rgb[1]))) / 255.0
    b = max(0, min(255, int(rgb[2]))) / 255.0
    h, s, _v = colorsys.rgb_to_hsv(r, g, b)
    # Home Assistant expects [hue (0-360), sat (0-100)]
    return [round(h * 360.0, 2), round(s * 100.0, 2)]


def ha_control_switch(entity_id: str, state: str) -> str:
    """Control Home Assistant switch (on/off). Entity ID: switch.xxx"""
    entity_id = _resolve_ha_entity("switch", entity_id)
    state = state.strip().lower()
    if state not in ("on", "off", "toggle"):
        return "❌ state debe ser 'on', 'off' o 'toggle'"
    
    service = "switch/turn_on" if state == "on" else "switch/turn_off" if state == "off" else "switch/toggle"
    ok, detail = _ha_post(service, {"entity_id": entity_id})
    
    if ok:
        time.sleep(0.8)
        st_ok, st_err, st_data = _ha_get_state(entity_id)
        if not st_ok:
            return f"⚠️ Envié comando a {entity_id}, pero no pude verificar estado final: {st_err}"
        final_state = str(st_data.get("state", "unknown")).lower()
        if state in ("on", "off") and final_state != state:
            return (
                f"⚠️ Envié '{state}' a {entity_id}, pero HA reporta '{final_state}'. "
                "No confirmo cambio real."
            )
        return f"✅ Switch {entity_id} → {state} confirmado (estado final: {final_state})"
    return f"❌ Error controlando switch: {detail}"


def ha_control_light(
    entity_id: str,
    state: str = "on",
    brightness: int = 255,
    rgb_color: Optional[List[int]] = None,
    color: str = "",
) -> str:
    """
    Control Home Assistant light (on/off, brightness, RGB color).
    Entity ID: light.xxx
    
    Args:
        entity_id: Entity ID (e.g., "light.smart_bulb")
        state: "on" or "off"
        brightness: 0-255
        rgb_color: [R, G, B] values 0-255 (optional)
        color: Nombre de color (ej: 'rojo', 'blue') (optional)
    """
    entity_id = _resolve_ha_entity("light", entity_id)
    state = state.strip().lower()
    if state not in ("on", "off", "toggle"):
        return "❌ state debe ser 'on', 'off' o 'toggle'"
    
    payload = {"entity_id": entity_id}

    # Resolve color name -> rgb if needed
    if color and not rgb_color:
        rgb_color = _COLOR_NAME_TO_RGB.get(color.strip().lower())
    
    if state == "off":
        ok, detail = _ha_post("light/turn_off", payload)
    elif state == "toggle":
        ok, detail = _ha_post("light/toggle", payload)
    else:  # on
        payload["brightness"] = max(0, min(255, int(brightness)))
        supported_modes: List[str] = []
        st_ok, _st_err, st_data = _ha_get_state(entity_id)
        if st_ok:
            supported_modes = list(st_data.get("attributes", {}).get("supported_color_modes", []) or [])

        if rgb_color and len(rgb_color) == 3:
            rgb = [
                max(0, min(255, int(rgb_color[0]))),
                max(0, min(255, int(rgb_color[1]))),
                max(0, min(255, int(rgb_color[2]))),
            ]

            # Many Tuya bulbs prefer hs_color even if they expose rgb_color sometimes.
            if supported_modes and ("hs" in supported_modes) and not any(m.startswith("rgb") for m in supported_modes):
                payload["hs_color"] = _rgb_to_hs(rgb)
            else:
                payload["rgb_color"] = rgb

        ok, detail = _ha_post("light/turn_on", payload)

        # Fallback: if color didn't apply, retry using hs_color
        if ok and rgb_color and len(rgb_color) == 3:
            time.sleep(1)
            after_ok, _after_err, after = _ha_get_state(entity_id)
            if after_ok:
                attrs = after.get("attributes", {}) or {}
                desired_rgb = payload.get("rgb_color")
                desired_hs = payload.get("hs_color")
                current_rgb = attrs.get("rgb_color")
                current_hs = attrs.get("hs_color")

                rgb_applied = bool(desired_rgb and current_rgb and list(current_rgb) == list(desired_rgb))
                hs_applied = False
                if desired_hs and current_hs and isinstance(current_hs, (list, tuple)) and len(current_hs) >= 2:
                    hs_applied = [round(float(current_hs[0]), 2), round(float(current_hs[1]), 2)] == list(desired_hs)

                if not rgb_applied and not hs_applied:
                    retry_payload = {
                        "entity_id": entity_id,
                        "brightness": payload.get("brightness", 255),
                        "hs_color": _rgb_to_hs(rgb_color),
                    }
                    _ha_post("light/turn_on", retry_payload)
    
    if ok:
        # Strong verification: confirm final state from Home Assistant.
        time.sleep(1.2)
        st_ok, st_err, st_data = _ha_get_state(entity_id)
        if not st_ok:
            return (
                f"⚠️ Envié comando a {entity_id}, pero no pude verificar estado final: {st_err}"
            )

        final_state = str(st_data.get("state", "unknown")).lower()
        attrs = st_data.get("attributes", {}) or {}

        if state == "off" and final_state != "off":
            return (
                f"⚠️ Envié apagado a {entity_id}, pero HA reporta estado final '{final_state}'. "
                "No confirmo apagado real."
            )
        if state == "on" and final_state != "on":
            return (
                f"⚠️ Envié encendido a {entity_id}, pero HA reporta estado final '{final_state}'. "
                "No confirmo encendido real."
            )

        color_info = ""
        if rgb_color and len(rgb_color) == 3:
            color_info = f" color=RGB({int(rgb_color[0])},{int(rgb_color[1])},{int(rgb_color[2])})"
        elif color:
            color_info = f" color={color.strip()}"
        # Include final state snapshot to avoid false positives in chat.
        final_brightness = attrs.get("brightness")
        bright_note = ""
        if isinstance(final_brightness, int):
            bright_pct = int((final_brightness / 255) * 100)
            bright_note = f", brillo final~{bright_pct}%"
        return f"✅ Light {entity_id} → {state} confirmado (estado final: {final_state}{bright_note}{color_info})"
    return f"❌ Error controlando light: {detail}"


def ha_control_vacuum(entity_id: str, action: str) -> str:
    """
    Control Home Assistant vacuum cleaner.
    Entity ID: vacuum.xxx or device ID for Tuya
    
    Actions: start, stop, pause, return_to_base, locate, clean_spot
    """
    entity_id = _resolve_ha_entity("vacuum", entity_id)
    action = action.strip().lower()
    valid_actions = {"start", "stop", "pause", "return_to_base", "locate", "clean_spot"}
    if action not in valid_actions:
        return f"❌ action debe ser uno de: {', '.join(valid_actions)}"
    
    service_map = {
        "start": "vacuum/start",
        "stop": "vacuum/stop",
        "pause": "vacuum/pause",
        "return_to_base": "vacuum/return_to_base",
        "locate": "vacuum/locate",
        "clean_spot": "vacuum/clean_spot",
    }
    
    ok, detail = _ha_post(service_map[action], {"entity_id": entity_id})
    
    if ok:
        time.sleep(1.2)
        st_ok, st_err, st_data = _ha_get_state(entity_id)
        if st_ok:
            return f"✅ Vacuum {entity_id} → {action} (estado: {st_data.get('state', 'unknown')})"
        return f"⚠️ Vacuum {entity_id} → {action} enviado, sin confirmación final: {st_err}"
    return f"❌ Error controlando vacuum: {detail}"


def ha_get_state(entity_id: str) -> str:
    """Get state of any Home Assistant entity (switch, light, vacuum, etc.)"""
    # If the caller passes a friendly name, try best-effort resolve across common domains.
    raw = (entity_id or "").strip()
    if raw and "." not in raw:
        # Prefer exact match by trying a few domains.
        for d in ("light", "switch", "vacuum", "sensor", "binary_sensor", "media_player"):
            candidate = _resolve_ha_entity(d, raw)
            ok, _, _data = _ha_get_state(candidate)
            if ok:
                entity_id = candidate
                break
    ok, err, data = _ha_get_state(entity_id)
    
    if not ok:
        return f"❌ No pude obtener estado de {entity_id}: {err}"
    
    state = data.get("state", "unknown")
    attrs = data.get("attributes", {})
    
    result = f"📊 Estado de {entity_id}:\nEstado: {state}"
    
    # Add device-specific attributes
    if "brightness" in attrs:
        brightness_pct = int((attrs["brightness"] / 255) * 100)
        result += f"\nBrillo: {brightness_pct}%"
    
    if "rgb_color" in attrs:
        rgb = attrs["rgb_color"]
        result += f"\nColor RGB: ({rgb[0]}, {rgb[1]}, {rgb[2]})"
    
    if "battery_level" in attrs:
        result += f"\nBatería: {attrs['battery_level']}%"
    
    if "battery_icon" in attrs:
        result += f"\nBatería: {attrs['battery_icon']}"
    
    if "status" in attrs:
        result += f"\nStatus: {attrs['status']}"
    
    return result


def ha_sync_entities() -> str:
    """
    Force sync Home Assistant entities into persistent cache.
    Useful when new devices are added.
    Saves entity state for filtering unavailable devices.
    """
    ok, err, states = _ha_list_states()
    if not ok:
        return f"❌ No pude sincronizar entidades HA: {err}"
    domains = {}
    mem = _load_device_memory()
    entities = mem.setdefault("entities", {})
    
    for st in states:
        eid = str(st.get("entity_id", "")).lower()
        if "." not in eid:
            continue
        d = eid.split(".", 1)[0]
        domains[d] = domains.get(d, 0) + 1
        
        # Save entity with state
        friendly = str(st.get("attributes", {}).get("friendly_name", "")).strip()
        state = str(st.get("state", "")).strip()
        _remember_entity(eid, friendly_name=friendly, domain=d, state=state)
    
    _save_device_memory()
    summary = ", ".join(f"{k}={v}" for k, v in sorted(domains.items()))
    return f"✅ Entidades sincronizadas en memoria persistente ({len(states)} total). {summary}"


def ha_list_entities(domain: str = "light", filter_unavailable: bool = True) -> str:
    """
    List Home Assistant entities for a domain (light/switch/vacuum/media_player/etc).
    Uses cache first and auto-sync on cache miss.
    
    Args:
        domain: Domain to list (light/switch/vacuum/media_player/etc)
        filter_unavailable: If True, filter out unavailable entities and Alexa devices that don't work
    """
    domain = (domain or "light").strip().lower()
    mem = _load_device_memory()
    entities = mem.get("entities", {}) if isinstance(mem, dict) else {}
    rows = []
    
    # Patterns to exclude (Alexa devices that typically don't work)
    alexa_exclude_patterns = [
        "this_device",  # Local device (usually not useful)
        "jarvis",       # Jarvis Echo (if not working)
    ]
    
    for eid, info in entities.items():
        if not str(eid).startswith(f"{domain}."):
            continue
        
        friendly = str(info.get("friendly_name", "")).strip()
        state = str(info.get("state", "")).strip()
        entity_domain = str(eid).split(".", 1)[0] if "." in str(eid) else domain
        
        # Filter out unavailable entities if requested
        if filter_unavailable:
            # Check current state from Home Assistant if cached state is unavailable
            if state.lower() in ("unavailable", "unknown", "none"):
                # Verify current state from HA
                ok, _, current_data = _ha_get_state(eid)
                if ok and current_data:
                    current_state = str(current_data.get("state", "")).strip().lower()
                    if current_state not in ("unavailable", "unknown", "none"):
                        # Entity is now available, update cache
                        state = current_state
                        info["state"] = current_state
                        _remember_entity(eid, friendly_name=friendly, domain=entity_domain, state=current_state)
                    else:
                        # Still unavailable, skip it
                        continue
                else:
                    # Can't verify, skip if it's an Alexa device
                    eid_lower = str(eid).lower()
                    if any(pattern in eid_lower for pattern in alexa_exclude_patterns):
                        continue
            
            # Filter out Alexa devices that are unavailable
            eid_lower = str(eid).lower()
            if any(pattern in eid_lower for pattern in alexa_exclude_patterns):
                if state.lower() in ("unavailable", "unknown", "none"):
                    continue
        
        rows.append((str(eid), friendly, state))

    if not rows:
        ok, err, _states = _ha_list_states()
        if not ok:
            return f"❌ No pude listar entidades {domain} desde HA: {err}"
        mem = _load_device_memory()
        entities = mem.get("entities", {}) if isinstance(mem, dict) else {}
        for eid, info in entities.items():
            if str(eid).startswith(f"{domain}."):
                friendly = str(info.get("friendly_name", "")).strip()
                state = str(info.get("state", "")).strip()
                entity_domain = str(eid).split(".", 1)[0] if "." in str(eid) else domain
                
                # Apply same filters
                if filter_unavailable:
                    # Check current state from Home Assistant if cached state is unavailable
                    if state.lower() in ("unavailable", "unknown", "none"):
                        ok, _, current_data = _ha_get_state(eid)
                        if ok and current_data:
                            current_state = str(current_data.get("state", "")).strip().lower()
                            if current_state not in ("unavailable", "unknown", "none"):
                                state = current_state
                                info["state"] = current_state
                                _remember_entity(eid, friendly_name=friendly, domain=entity_domain, state=current_state)
                            else:
                                continue
                        else:
                            eid_lower = str(eid).lower()
                            if any(pattern in eid_lower for pattern in alexa_exclude_patterns):
                                continue
                    
                    # Filter out Alexa devices that are unavailable
                    eid_lower = str(eid).lower()
                    if any(pattern in eid_lower for pattern in alexa_exclude_patterns):
                        if state.lower() in ("unavailable", "unknown", "none"):
                            continue
                
                rows.append((str(eid), friendly, state))

    if not rows:
        return f"⚠️ No encontré entidades del dominio '{domain}' disponibles."

    lines = [f"📋 Entidades {domain} disponibles:"]
    for eid, friendly, state in sorted(rows):
        if friendly:
            lines.append(f"- {eid} ({friendly}) - Estado: {state}")
        else:
            lines.append(f"- {eid} - Estado: {state}")
    return "\n".join(lines)


def ha_clean_unavailable_entities(domain: str = "") -> str:
    """
    Remove unavailable entities from cache.
    Useful for cleaning up obsolete Alexa devices or broken entities.
    
    Args:
        domain: Optional domain to clean (e.g., "media_player"). If empty, cleans all domains.
    """
    mem = _load_device_memory()
    entities = mem.get("entities", {}) if isinstance(mem, dict) else {}
    
    removed = []
    alexa_patterns = ["this_device", "jarvis"]
    
    for eid, info in list(entities.items()):
        entity_domain = str(eid).split(".", 1)[0] if "." in str(eid) else ""
        
        # Filter by domain if specified
        if domain and entity_domain != domain.lower():
            continue
        
        state = str(info.get("state", "")).lower()
        eid_lower = str(eid).lower()
        
        # Remove if unavailable or if it's an Alexa device that's unavailable
        if state in ("unavailable", "unknown", "none"):
            # Check if it's an Alexa device
            is_alexa = any(pattern in eid_lower for pattern in alexa_patterns)
            if is_alexa or state == "unavailable":
                removed.append(eid)
                del entities[eid]
    
    if removed:
        mem["entities"] = entities
        _save_device_memory()
        return f"✅ Eliminadas {len(removed)} entidades no disponibles:\n" + "\n".join(f"- {eid}" for eid in removed[:20])
    else:
        return "✅ No se encontraron entidades no disponibles para eliminar."


def ha_set_alias(alias: str, entity_id: str) -> str:
    """
    Persist a manual alias for long-term memory.
    Example: alias='living', entity_id='light.smart_bulb_2'
    """
    alias = (alias or "").strip().lower()
    entity_id = (entity_id or "").strip().lower()
    if not alias or not entity_id or "." not in entity_id:
        return "❌ alias y entity_id válido son requeridos"
    domain = entity_id.split(".", 1)[0]
    mem = _load_device_memory()
    mem.setdefault("aliases", {})
    mem.setdefault("entities", {})
    mem["aliases"][alias] = entity_id
    mem["aliases"][f"{domain}:{alias}"] = entity_id
    _remember_entity(entity_id, domain=domain)
    _save_device_memory()
    return f"✅ Alias guardado: '{alias}' → {entity_id}"


# ============================================================================
# SMART PLUG CONTROL (TP-Link, Tuya) - Legacy, use ha_control_switch instead
# ============================================================================

def control_smart_plug(device_id: str, action: str) -> str:
    """
    Control smart plug (on/off/toggle)

    Supports:
    - Home Assistant switches (entity_id: switch.xxx)
    - TP-Link Kasa (legacy API)
    - Tuya Smart Life (legacy API)

    If device_id starts with "switch.", uses Home Assistant automatically.
    """
    # Auto-detect Home Assistant entity_id
    if device_id.startswith("switch.") or os.getenv("HOME_ASSISTANT_TOKEN", "").strip():
        # If token exists, we can also accept slugs/friendly names.
        if not device_id.startswith("switch."):
            device_id = _resolve_ha_entity("switch", device_id)
        if device_id.startswith("switch."):
            return ha_control_switch(device_id, action)
    
    # Legacy API fallback
    try:
        api_key = os.getenv("SMART_HOME_API_KEY")
        api_url = os.getenv("SMART_HOME_API_URL", "http://localhost:8080")

        if not api_key:
            return "❌ SMART_HOME_API_KEY not configured. Use entity_id format: switch.xxx"

        response = requests.post(
            f"{api_url}/devices/{device_id}/control",
            json={"action": action},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            return f"✅ Plug {device_id}: {action}"
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def get_plug_status(device_id: str) -> str:
    """Get smart plug status (on/off, power consumption)"""
    # Auto-detect Home Assistant entity_id
    if device_id.startswith("switch.") or os.getenv("HOME_ASSISTANT_TOKEN", "").strip():
        if not device_id.startswith("switch."):
            device_id = _resolve_ha_entity("switch", device_id)
        if device_id.startswith("switch."):
            return ha_get_state(device_id)
    
    # Legacy API fallback
    try:
        api_key = os.getenv("SMART_HOME_API_KEY")
        api_url = os.getenv("SMART_HOME_API_URL", "http://localhost:8080")

        if not api_key:
            return "❌ SMART_HOME_API_KEY not configured. Use entity_id format: switch.xxx"

        response = requests.get(
            f"{api_url}/devices/{device_id}/status",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            return f"""🔌 Plug Status - {device_id}
State: {data.get('state', 'unknown')}
Power: {data.get('power', 0)}W
Today: {data.get('energy_today', 0)}kWh
"""
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ============================================================================
# VACUUM CONTROL (Roborock, Xiaomi, others)
# ============================================================================

def vacuum_control(action: str, device_id: str = "default") -> str:
    """
    Control vacuum cleaner

    Actions: start, stop, pause, return_to_base, locate, clean_spot

    Supports:
    - Home Assistant vacuums (entity_id: vacuum.xxx)
    - Roborock (legacy API)
    - Xiaomi Mi (legacy API)

    If device_id starts with "vacuum.", uses Home Assistant automatically.
    """
    # Auto-detect Home Assistant entity_id
    if device_id.startswith("vacuum.") or os.getenv("HOME_ASSISTANT_TOKEN", "").strip():
        if not device_id.startswith("vacuum."):
            device_id = _resolve_ha_entity("vacuum", device_id)
        if device_id.startswith("vacuum."):
            return ha_control_vacuum(device_id, action)
    
    # Legacy API fallback
    try:
        api_key = os.getenv("VACUUM_API_KEY")
        api_url = os.getenv("VACUUM_API_URL", "http://localhost:8081")

        if not api_key:
            return "❌ VACUUM_API_KEY not configured. Use entity_id format: vacuum.xxx"

        response = requests.post(
            f"{api_url}/vacuum/{device_id}/control",
            json={"action": action},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            return f"✅ Vacuum: {action}"
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def vacuum_status(device_id: str = "default") -> str:
    """Get vacuum status"""
    # Auto-detect Home Assistant entity_id
    if device_id.startswith("vacuum.") or os.getenv("HOME_ASSISTANT_TOKEN", "").strip():
        if not device_id.startswith("vacuum."):
            device_id = _resolve_ha_entity("vacuum", device_id)
        if device_id.startswith("vacuum."):
            return ha_get_state(device_id)
    
    # Legacy API fallback
    try:
        api_key = os.getenv("VACUUM_API_KEY")
        api_url = os.getenv("VACUUM_API_URL", "http://localhost:8081")

        if not api_key:
            return "❌ VACUUM_API_KEY not configured. Use entity_id format: vacuum.xxx"

        response = requests.get(
            f"{api_url}/vacuum/{device_id}/status",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            return f"""🤖 Vacuum Status - {device_id}
State: {data.get('state', 'unknown')}
Battery: {data.get('battery', 0)}%
Cleaning Time: {data.get('cleaning_time', 0)} min
Area Cleaned: {data.get('area', 0)} m²
"""
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ============================================================================
# SMART LIGHTS (Philips Hue, etc.)
# ============================================================================

def control_lights(room: str, state: str, brightness: int = 100) -> str:
    """
    Control smart lights

    Args:
        room: Room name or light entity_id (e.g., "light.smart_bulb")
        state: on/off
        brightness: 0-100 (converted to 0-255 for Home Assistant)
    
    If room starts with "light.", uses Home Assistant automatically.
    """
    # Home Assistant path (preferred). Accept entity_id, slug, or friendly name if token exists.
    if room.startswith("light.") or os.getenv("HOME_ASSISTANT_TOKEN", "").strip():
        resolved = room if room.startswith("light.") else _resolve_ha_entity("light", room)
        if resolved.startswith("light."):
            brightness_255 = int((max(0, min(100, int(brightness))) / 100) * 255)
            return ha_control_light(resolved, state, brightness_255)
    
    # Legacy API fallback
    try:
        api_key = os.getenv("LIGHTS_API_KEY")
        api_url = os.getenv("LIGHTS_API_URL", "http://localhost:8082")

        if not api_key:
            return "❌ LIGHTS_API_KEY not configured. Use entity_id format: light.xxx"

        response = requests.post(
            f"{api_url}/lights/{room}/control",
            json={
                "state": state,
                "brightness": brightness
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            return f"✅ Lights {room}: {state} ({brightness}%)"
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def set_scene(scene_name: str) -> str:
    """Activate a lighting scene"""
    try:
        api_key = os.getenv("LIGHTS_API_KEY")
        api_url = os.getenv("LIGHTS_API_URL", "http://localhost:8082")

        if not api_key:
            return "❌ LIGHTS_API_KEY not configured"

        response = requests.post(
            f"{api_url}/scenes/{scene_name}/activate",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            return f"✅ Scene activated: {scene_name}"
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ============================================================================
# TEMPERATURE & SENSORS
# ============================================================================

def get_sensor_data(sensor_id: str) -> str:
    """Get data from temperature/humidity sensors"""
    # Auto-detect Home Assistant entity_id (sensor.*, binary_sensor.*, etc.)
    if sensor_id.startswith(("sensor.", "binary_sensor.", "climate.", "weather.")) or os.getenv("HOME_ASSISTANT_TOKEN", "").strip():
        if "." not in sensor_id:
            sensor_id = _resolve_ha_entity("sensor", sensor_id)
        return ha_get_state(sensor_id)
    
    # Legacy API fallback
    try:
        api_url = os.getenv("SENSORS_API_URL", "http://localhost:8083")

        response = requests.get(
            f"{api_url}/sensors/{sensor_id}",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            return f"""🌡️ Sensor - {sensor_id}
Temperature: {data.get('temperature', 'N/A')}°C
Humidity: {data.get('humidity', 'N/A')}%
Battery: {data.get('battery', 'N/A')}%
Last Update: {data.get('last_update', 'N/A')}
"""
        else:
            return f"❌ Failed: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"
