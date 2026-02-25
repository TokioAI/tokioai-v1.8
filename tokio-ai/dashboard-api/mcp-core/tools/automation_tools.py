"""
Automation tools: propone tools/commands con aprobación humana.
"""
import os
import logging
import json
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    try:
        import requests
        HAS_REQUESTS = True
    except ImportError:
        HAS_REQUESTS = False

def _get_base_url() -> str:
    return os.getenv("DASHBOARD_API_BASE_URL") or f"http://YOUR_IP_ADDRESS:{os.getenv('PORT','8080')}"

def _get_headers() -> Dict[str, str]:
    token = os.getenv("AUTOMATION_API_TOKEN", "").strip()
    return {"X-Automation-Token": token} if token else {}

async def _post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{_get_base_url()}{endpoint}"
    if HAS_AIOHTTP:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=_get_headers(),
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                error_text = await resp.text()
                logger.warning(f"Automation POST failed {resp.status} at {url}: {error_text[:200]}")
                return {"success": False, "error": error_text}
    if HAS_REQUESTS:
        resp = requests.post(url, json=payload, headers=_get_headers(), timeout=20)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Automation POST failed {resp.status_code} at {url}: {resp.text[:200]}")
        return {"success": False, "error": resp.text}
    try:
        data = json.dumps(payload).encode()
        req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json", **_get_headers()})
        with urlrequest.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()
            if resp.status == 200:
                return json.loads(body)
            logger.warning(f"Automation POST failed {resp.status} at {url}: {body[:200]}")
            return {"success": False, "error": body}
    except HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        logger.warning(f"Automation POST failed {e.code} at {url}: {body[:200]}")
        return {"success": False, "error": body}
    except URLError as e:
        logger.warning(f"Automation POST error at {url}: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.warning(f"Automation POST unexpected error at {url}: {e}")
        return {"success": False, "error": str(e)}

async def _get(endpoint: str) -> Dict[str, Any]:
    url = f"{_get_base_url()}{endpoint}"
    if HAS_AIOHTTP:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=_get_headers(),
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                error_text = await resp.text()
                logger.warning(f"Automation GET failed {resp.status} at {url}: {error_text[:200]}")
                return {"success": False, "error": error_text}
    if HAS_REQUESTS:
        resp = requests.get(url, headers=_get_headers(), timeout=20)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Automation GET failed {resp.status_code} at {url}: {resp.text[:200]}")
        return {"success": False, "error": resp.text}
    try:
        req = urlrequest.Request(url, headers=_get_headers())
        with urlrequest.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()
            if resp.status == 200:
                return json.loads(body)
            logger.warning(f"Automation GET failed {resp.status} at {url}: {body[:200]}")
            return {"success": False, "error": body}
    except HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        logger.warning(f"Automation GET failed {e.code} at {url}: {body[:200]}")
        return {"success": False, "error": body}
    except URLError as e:
        logger.warning(f"Automation GET error at {url}: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.warning(f"Automation GET unexpected error at {url}: {e}")
        return {"success": False, "error": str(e)}

async def tool_propose_tool(
    title: str,
    description: Optional[str] = "",
    code: str = "",
    input_schema: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    payload = {
        "type": "tool",
        "title": title,
        "description": description,
        "code": code,
        "input_schema": input_schema
    }
    return await _post("/api/automation/proposals", payload)

async def tool_propose_command(
    title: str,
    command: str,
    description: Optional[str] = ""
) -> Dict[str, Any]:
    payload = {
        "type": "command",
        "title": title,
        "description": description,
        "command": command
    }
    return await _post("/api/automation/proposals", payload)

async def tool_list_automation_pending() -> Dict[str, Any]:
    return await _get("/api/automation/proposals?status=pending")


async def tool_list_automation_approved() -> Dict[str, Any]:
    return await _get("/api/automation/tools?status=approved")


async def tool_run_approved_tool(
    tool_id: Optional[str] = None,
    tool_key: Optional[str] = None,
    title: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    payload = {
        "id": tool_id or "",
        "tool_key": tool_key or "",
        "title": title or "",
        "args": args or {}
    }
    return await _post("/api/automation/tools/execute", payload)
