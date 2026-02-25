"""
Cloudflare API Tools - Configure tunnel routes and SSL via Cloudflare API
"""
import os
import json
import requests
from typing import Dict, Optional, Any, Tuple, List


def _cf_headers(api_token: str) -> Dict[str, str]:
    """Get Cloudflare API headers"""
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def _get_ingress(url: str, api_token: str) -> Tuple[List[Dict[str, Any]], str]:
    try:
        response = requests.get(url, headers=_cf_headers(api_token), timeout=30)
        if response.status_code != 200:
            return [], f"HTTP {response.status_code}: {(response.text or '')[:240]}"
        config = response.json()
        ingress = config.get("result", {}).get("config", {}).get("ingress", [])
        if not isinstance(ingress, list):
            ingress = []
        return ingress, ""
    except Exception as e:
        return [], str(e)


def _put_ingress(url: str, api_token: str, ingress: List[Dict[str, Any]]) -> Tuple[bool, str]:
    payload = {"config": {"ingress": ingress}}
    try:
        response = requests.put(
            url,
            headers=_cf_headers(api_token),
            json=payload,
            timeout=30,
        )
        if response.status_code == 200:
            return True, "ok"
        return False, f"HTTP {response.status_code}: {(response.text or '')[:400]}"
    except Exception as e:
        return False, str(e)


def cloudflare_configure_tunnel_route(
    tunnel_id: str,
    account_id: str,
    hostname: str,
    service: str,
    api_token: str,
) -> Tuple[bool, str]:
    """
    Configure a public hostname route for a Cloudflare tunnel.
    This allows SSL to work even if domain is not in Cloudflare DNS.
    
    Args:
        tunnel_id: Tunnel ID (e.g., "a59b3ce9-206d-446f-b3be-a7851c8790d0")
        account_id: Cloudflare Account ID
        hostname: Domain name (e.g., "tokioia.com")
        service: Local service URL (e.g., "http://localhost:8080")
        api_token: Cloudflare API token with Zero Trust permissions
    
    Returns:
        (success, message)
    """
    if not api_token:
        return False, "CLOUDFLARE_API_TOKEN no configurado"
    if not account_id:
        return False, "CLOUDFLARE_ACCOUNT_ID no configurado"
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
    
    ingress, err = _get_ingress(url, api_token)
    if err:
        return False, f"No pude leer configuración del túnel: {err}"

    # Remove existing route for hostname to keep operation idempotent.
    ingress = [r for r in ingress if str(r.get("hostname", "")).strip().lower() != hostname.lower()]
    ingress.insert(0, {"hostname": hostname, "service": service})
    
    # Add www variant
    if not hostname.startswith("www."):
        www_hostname = f"www.{hostname}"
        ingress = [r for r in ingress if str(r.get("hostname", "")).strip().lower() != www_hostname.lower()]
        ingress.insert(1, {"hostname": www_hostname, "service": service})

    # Add catch-all at the end when missing.
    if not any(r.get("service", "").startswith("http_status:") for r in ingress):
        ingress.append({"service": "http_status:404"})

    ok, put_err = _put_ingress(url, api_token, ingress)
    if ok:
        return True, f"Ruta configurada: {hostname} -> {service}"
    return False, put_err


def cloudflare_remove_tunnel_route(
    tunnel_id: str,
    account_id: str,
    hostname: str,
    api_token: str,
) -> Tuple[bool, str]:
    if not api_token:
        return False, "CLOUDFLARE_API_TOKEN no configurado"
    if not account_id:
        return False, "CLOUDFLARE_ACCOUNT_ID no configurado"
    if not tunnel_id:
        return False, "tunnel_id requerido"
    if not hostname:
        return False, "hostname requerido"

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations"
    ingress, err = _get_ingress(url, api_token)
    if err:
        return False, f"No pude leer configuración del túnel: {err}"

    wanted = {hostname.lower()}
    if not hostname.startswith("www."):
        wanted.add(f"www.{hostname}".lower())
    before = len(ingress)
    ingress = [r for r in ingress if str(r.get("hostname", "")).strip().lower() not in wanted]
    removed = before - len(ingress)

    if not any(r.get("service", "").startswith("http_status:") for r in ingress):
        ingress.append({"service": "http_status:404"})

    ok, put_err = _put_ingress(url, api_token, ingress)
    if ok:
        return True, f"Rutas removidas: {removed} para {hostname}"
    return False, put_err


def cloudflare_tool(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Cloudflare API tool entry point
    
    Actions:
    - configure_tunnel_route: Configure tunnel public hostname route
    - remove_tunnel_route: Remove hostname route from tunnel config
    """
    params = params or {}
    action = (action or "").strip().lower()
    
    try:
        if action == "configure_tunnel_route":
            api_token = str(params.get("api_token", os.getenv("CLOUDFLARE_API_TOKEN", ""))).strip()
            account_id = str(params.get("account_id", os.getenv("CLOUDFLARE_ACCOUNT_ID", ""))).strip()
            tunnel_id = str(params.get("tunnel_id", os.getenv("CLOUDFLARED_TUNNEL_ID", ""))).strip()
            hostname = str(params.get("hostname", "")).strip()
            service = str(params.get("service", "http://localhost:8080")).strip()
            
            if not tunnel_id:
                return json.dumps({
                    "ok": False,
                    "error": "tunnel_id requerido (o CLOUDFLARED_TUNNEL_ID en env)"
                }, ensure_ascii=False)
            if not hostname:
                return json.dumps({
                    "ok": False,
                    "error": "hostname requerido"
                }, ensure_ascii=False)
            
            ok, msg = cloudflare_configure_tunnel_route(
                tunnel_id=tunnel_id,
                account_id=account_id,
                hostname=hostname,
                service=service,
                api_token=api_token,
            )
            
            return json.dumps({
                "ok": ok,
                "action": action,
                "result": msg if ok else None,
                "error": msg if not ok else None
            }, ensure_ascii=False)
        elif action == "remove_tunnel_route":
            api_token = str(params.get("api_token", os.getenv("CLOUDFLARE_API_TOKEN", ""))).strip()
            account_id = str(params.get("account_id", os.getenv("CLOUDFLARE_ACCOUNT_ID", ""))).strip()
            tunnel_id = str(params.get("tunnel_id", os.getenv("CLOUDFLARED_TUNNEL_ID", ""))).strip()
            hostname = str(params.get("hostname", "")).strip()
            ok, msg = cloudflare_remove_tunnel_route(
                tunnel_id=tunnel_id,
                account_id=account_id,
                hostname=hostname,
                api_token=api_token,
            )
            return json.dumps({
                "ok": ok,
                "action": action,
                "result": msg if ok else None,
                "error": msg if not ok else None
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "ok": False,
                "error": f"acción no soportada: {action}",
                "supported": ["configure_tunnel_route", "remove_tunnel_route"]
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "ok": False,
            "action": action,
            "error": str(e)
        }, ensure_ascii=False)
