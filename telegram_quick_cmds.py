"""
TokioAI Telegram Quick Commands — instant responses, no LLM needed.

/sitrep   — Full system status
/health   — Health vitals (HR, SpO2, BP)
/waf      — WAF attack stats
/drone    — Drone status
/threats  — DEFCON threat level
/entity   — Entity vision status
/see      — Camera snapshot
"""
import os
import io
import httpx
from telegram import Update
from telegram.ext import ContextTypes

RASPI_API = os.getenv("RASPI_API_URL", "http://100.100.80.12:5000")
DRONE_API = os.getenv("DRONE_API_URL", "http://100.100.80.12:5001")
WAF_API = os.getenv("WAF_DASHBOARD_URL", "http://127.0.0.1:8000")
WAF_USER = os.getenv("WAF_DASHBOARD_USER", "admin")
WAF_PASS = os.getenv("WAF_DASHBOARD_PASS", "")
_waf_token_cache = {"token": "", "expires": 0}
CLI_API = os.getenv("CLI_SERVICE_URL", "http://tokio-agent:8000")


async def _quick_api(url: str, timeout: float = 8.0):
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.json()
            return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}


async def _waf_api(path: str, timeout: float = 8.0):
    """Authenticated WAF API call."""
    import time as _time
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Get/refresh token
            now = _time.time()
            if now > _waf_token_cache["expires"]:
                r = await client.post(
                    f"{WAF_API}/api/auth/login",
                    json={"username": WAF_USER, "password": WAF_PASS}
                )
                if r.status_code == 200:
                    _waf_token_cache["token"] = r.json().get("token", "")
                    _waf_token_cache["expires"] = now + 3600  # 1 hour
                else:
                    return {"error": f"WAF auth failed: {r.status_code}"}

            headers = {"Authorization": f"Bearer {_waf_token_cache['token']}"}
            r = await client.get(f"{WAF_API}{path}", headers=headers)
            if r.status_code == 200:
                return r.json()
            return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}


async def _safe_reply(update, text):
    try:
        await update.message.reply_text(text)
    except Exception:
        pass


async def _typing(update, context):
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass


async def sitrep_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    await _typing(update, context)

    lines = ["🛡️ SITREP — TokioAI\n"]

    entity = await _quick_api(f"{RASPI_API}/status")
    if "error" not in entity:
        fps = entity.get("vision", {}).get("fps", "?")
        persons = entity.get("persons_detected", 0)
        emotion = entity.get("emotion", "?")
        lines.append(f"👁️ Entity: ✅ {fps} FPS | {persons} persons | {emotion}")
    else:
        lines.append(f"👁️ Entity: ❌ offline")

    threat = await _quick_api(f"{RASPI_API}/threat/status")
    if "error" not in threat:
        lines.append(f"⚠️ Threat: DEFCON {threat.get('level', threat.get('defcon','?'))} ({threat.get('level_name','?')}) score={threat.get('overall_score', threat.get('score','?'))}")
    else:
        lines.append("⚠️ Threat: no data")

    waf = await _waf_api("/api/summary")
    if "error" not in waf:
        lines.append(f"🔥 WAF: {waf.get('total','?')} attacks | {waf.get('blocked','?')} blocked | {waf.get('active_blocks','?')} IPs banned")
    else:
        lines.append("🔥 WAF: ❌ unreachable")

    wifi = await _quick_api(f"{RASPI_API}/wifi/status")
    if "error" not in wifi and wifi.get("available"):
        mon = "✅" if wifi.get("monitoring") else "❌"
        cd = "ON" if wifi.get("counter_deauth") else "OFF"
        lines.append(f"📡 WiFi: {mon} monitor | counter-deauth {cd} | {wifi.get('deauth_detected',0)} deauths")
    else:
        lines.append("📡 WiFi: no data")

    health = await _quick_api(f"{RASPI_API}/health/status")
    if "error" not in health:
        lines.append(f"❤️ Health: HR {health.get('heart_rate','?')} bpm | SpO2 {health.get('spo2','?')}%")
    else:
        lines.append("❤️ Health: no data")

    drone = await _quick_api(f"{DRONE_API}/drone/status")
    if "error" not in drone:
        conn = "✅" if drone.get("connected") else "❌"
        lines.append(f"🚁 Drone: {conn} connected | safety={drone.get('safety_level','?')}")
    else:
        lines.append("🚁 Drone: proxy off")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{CLI_API}/health")
            lines.append("☁️ GCP Agent: ✅ healthy" if r.status_code == 200 else "☁️ GCP Agent: ❌")
    except Exception:
        lines.append("☁️ GCP Agent: ❌")

    await _safe_reply(update, "\n".join(lines))


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    await _typing(update, context)

    data = await _quick_api(f"{RASPI_API}/health/report")
    if "error" in data:
        await _safe_reply(update, f"❌ Health unavailable: {data['error'][:60]}")
        return

    lines = ["❤️ Health Report\n"]
    c = data.get("current", {})
    if c:
        lines.append(f"Heart Rate: {c.get('heart_rate','?')} bpm")
        lines.append(f"SpO2: {c.get('spo2','?')}%")
        bp = c.get("blood_pressure", {})
        if bp:
            lines.append(f"Blood Pressure: {bp.get('systolic','?')}/{bp.get('diastolic','?')} mmHg")
    a = data.get("assessment", "")
    if a:
        lines.append(f"\n📋 {a}")
    await _safe_reply(update, "\n".join(lines))


async def waf_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    await _typing(update, context)

    stats = await _waf_api("/api/summary")
    if "error" in stats:
        await _safe_reply(update, "❌ WAF unreachable")
        return

    lines = ["🔥 WAF Defense\n"]
    lines.append(f"Total attacks: {stats.get('total','?')}")
    lines.append(f"Blocked: {stats.get('blocked','?')}")
    lines.append(f"Active IP bans: {stats.get('active_blocks','?')}")
    lines.append(f"Unique IPs: {stats.get('unique_ips','?')}")
    # Severity (fields are at top level in summary)
    lines.append("\nSeverity:")
    for l in ["critical","high","medium","low"]:
        v = stats.get(l, 0)
        if v:
            lines.append(f"  {l.upper()}: {v}")
    await _safe_reply(update, "\n".join(lines))


async def drone_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    await _typing(update, context)

    data = await _quick_api(f"{DRONE_API}/drone/status")
    if "error" in data:
        await _safe_reply(update, "🚁 Drone proxy not responding")
        return

    lines = ["🚁 Drone Status\n"]
    connected = data.get('connected', False)
    armed = data.get('armed', False)
    lines.append(f"Connected: {'✅' if connected else '❌'}")
    lines.append(f"Armed: {'🟢 YES' if armed else '⚪ No'}")
    lines.append(f"Safety: {data.get('safety_level','?')}")
    lines.append(f"Kill switch: {'🔴 ACTIVE' if data.get('kill_switch') else '🟢 normal'}")
    geo = data.get("geofence", {})
    if geo:
        lines.append(f"Geofence: {geo.get('max_distance_cm','?')}cm | height {geo.get('max_height_cm','?')}cm")
    audit = data.get("audit", {})
    if audit:
        lines.append(f"Commands: {audit.get('total_commands',0)} | Blocked: {audit.get('blocked_commands',0)}")
    await _safe_reply(update, "\n".join(lines))


async def threats_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    await _typing(update, context)

    data = await _quick_api(f"{RASPI_API}/threat/status")
    if "error" in data:
        await _safe_reply(update, "⚠️ Threat engine not responding")
        return

    defcon = data.get("level", data.get("defcon", "?"))
    emojis = {"1":"🔴","2":"🟠","3":"🟡","4":"🔵","5":"🟢"}
    e = emojis.get(str(defcon), "⚪")
    lines = [f"{e} DEFCON {defcon} — {data.get('level_name','?')}\n"]
    lines.append(f"Score: {data.get('overall_score', data.get('score','?'))}")
    vecs = data.get("vectors", data.get("threat_vectors", {}))
    if vecs:
        lines.append("\nThreat vectors:")
        for v, info in vecs.items():
            score = info.get('score', 0)
            emoji = "🔴" if score >= 50 else "🟠" if score >= 25 else "🟡" if score >= 10 else "🟢"
            name = info.get('name', v)
            detail = info.get('last_detail', '')
            lines.append(f"  {emoji} {name}: score {score}")
            if detail:
                lines.append(f"    └ {detail[:80]}")
    await _safe_reply(update, "\n".join(lines))


async def entity_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    await _typing(update, context)

    data = await _quick_api(f"{RASPI_API}/status")
    if "error" in data:
        await _safe_reply(update, f"❌ Entity unreachable")
        return

    lines = ["👁️ Entity Status\n"]
    v = data.get("vision", {})
    lines.append(f"FPS: {v.get('fps','?')}")
    lines.append(f"Camera: {'✅' if v.get('camera_open', v.get('camera_ok')) else '❌'}")
    lines.append(f"Hailo: {'✅' if v.get('hailo_available', v.get('hailo_active')) else '❌'}")
    lines.append(f"Persons: {data.get('persons_detected','?')}")
    lines.append(f"Emotion: {data.get('emotion','?')}")
    lines.append(f"Security: {'✅' if data.get('security_connected') else '❌'}")
    await _safe_reply(update, "\n".join(lines))

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{RASPI_API}/snapshot")
            if r.status_code == 200:
                await update.message.reply_photo(photo=io.BytesIO(r.content), caption="📸 Vista actual")
    except Exception:
        pass


async def see_command(update: Update, context: ContextTypes.DEFAULT_TYPE, guard_fn=None):
    if guard_fn and not await guard_fn(update):
        return
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{RASPI_API}/snapshot")
            if r.status_code == 200:
                await update.message.reply_photo(photo=io.BytesIO(r.content), caption="📸 Lo que veo ahora")
            else:
                await _safe_reply(update, "❌ No pude tomar snapshot")
    except Exception as e:
        await _safe_reply(update, f"❌ Camera: {str(e)[:60]}")
