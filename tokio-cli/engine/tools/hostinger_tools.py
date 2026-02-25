"""
Hostinger DNS Management Tool - Automate DNS record management via Hostinger API
"""
import os
import json
import requests
import logging
from typing import Dict, Optional, Any, Tuple, List
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

_HOSTINGER_API_BASE = os.getenv("HOSTINGER_API_BASE", "https://developers.hostinger.com").strip().rstrip("/")
_HOSTINGER_API_KEY = os.getenv("HOSTINGER_API_KEY", "").strip()
_PROXY_STATE_PATH = Path(os.getenv("TOKIO_PROXY_STATE_PATH", "/workspace/cli/proxy_sites.json"))


def _load_proxy_state() -> Dict[str, Any]:
    try:
        if _PROXY_STATE_PATH.exists():
            data = json.loads(_PROXY_STATE_PATH.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"sites": {}}


def _save_proxy_state(state: Dict[str, Any]) -> None:
    try:
        _PROXY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROXY_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"No se pudo guardar estado de proxy: {e}")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _hostinger_headers() -> Dict[str, str]:
    """Get Hostinger API headers"""
    if not _HOSTINGER_API_KEY:
        raise ValueError(
            "HOSTINGER_API_KEY no configurado. "
            "Obtén tu API key desde: https://hpanel.hostinger.com/profile/api"
        )
    return {
        "Authorization": f"Bearer {_HOSTINGER_API_KEY}",
        "Content-Type": "application/json",
    }


def _hostinger_get(endpoint: str, timeout: int = 30) -> Tuple[bool, str, Dict]:
    """GET request to Hostinger API"""
    try:
        response = requests.get(
            f"{_HOSTINGER_API_BASE}{endpoint}",
            headers=_hostinger_headers(),
            timeout=timeout,
        )
        if response.status_code == 200:
            return True, "", response.json()
        body = (response.text or "")[:400]
        if response.status_code in (403, 530) and ("error code: 1016" in body.lower() or "cloudflare" in body.lower()):
            return False, (
                "Hostinger API inaccesible desde este endpoint/red (Cloudflare 1016/530). "
                "Verifica HOSTINGER_API_BASE correcto y/o usa actualización DNS manual temporal."
            ), {}
        return False, f"HTTP {response.status_code}: {body}", {}
    except Exception as e:
        return False, str(e), {}


def _hostinger_post(endpoint: str, data: Dict, timeout: int = 30) -> Tuple[bool, str, Dict]:
    """POST request to Hostinger API"""
    try:
        response = requests.post(
            f"{_HOSTINGER_API_BASE}{endpoint}",
            headers=_hostinger_headers(),
            json=data,
            timeout=timeout,
        )
        if response.status_code in (200, 201):
            return True, "", response.json()
        body = (response.text or "")[:400]
        if response.status_code in (403, 530) and ("error code: 1016" in body.lower() or "cloudflare" in body.lower()):
            return False, (
                "Hostinger API inaccesible desde este endpoint/red (Cloudflare 1016/530). "
                "Verifica HOSTINGER_API_BASE correcto y/o usa actualización DNS manual temporal."
            ), {}
        return False, f"HTTP {response.status_code}: {body}", {}
    except Exception as e:
        return False, str(e), {}


def _hostinger_put(endpoint: str, data: Dict, timeout: int = 30) -> Tuple[bool, str, Dict]:
    """PUT request to Hostinger API"""
    try:
        response = requests.put(
            f"{_HOSTINGER_API_BASE}{endpoint}",
            headers=_hostinger_headers(),
            json=data,
            timeout=timeout,
        )
        if response.status_code in (200, 201, 204):
            return True, "", response.json() if response.content else {}
        body = (response.text or "")[:400]
        if response.status_code in (403, 530) and ("error code: 1016" in body.lower() or "cloudflare" in body.lower()):
            return False, (
                "Hostinger API inaccesible desde este endpoint/red (Cloudflare 1016/530). "
                "Verifica HOSTINGER_API_BASE correcto y/o usa actualización DNS manual temporal."
            ), {}
        return False, f"HTTP {response.status_code}: {body}", {}
    except Exception as e:
        return False, str(e), {}


def _hostinger_delete(endpoint: str, timeout: int = 30) -> Tuple[bool, str]:
    """DELETE request to Hostinger API"""
    try:
        response = requests.delete(
            f"{_HOSTINGER_API_BASE}{endpoint}",
            headers=_hostinger_headers(),
            timeout=timeout,
        )
        if response.status_code in (200, 204):
            return True, ""
        return False, f"HTTP {response.status_code}: {response.text[:300]}"
    except Exception as e:
        return False, str(e)


def _hostinger_delete_json(endpoint: str, data: Dict, timeout: int = 30) -> Tuple[bool, str, Dict]:
    """DELETE with JSON body (required by DNS v1 filters endpoint)."""
    try:
        response = requests.delete(
            f"{_HOSTINGER_API_BASE}{endpoint}",
            headers=_hostinger_headers(),
            json=data,
            timeout=timeout,
        )
        if response.status_code in (200, 204):
            return True, "", response.json() if response.content else {}
        body = (response.text or "")[:400]
        if response.status_code in (403, 530) and ("error code: 1016" in body.lower() or "cloudflare" in body.lower()):
            return False, (
                "Hostinger API inaccesible desde este endpoint/red (Cloudflare 1016/530). "
                "Verifica HOSTINGER_API_BASE correcto y/o usa actualización DNS manual temporal."
            ), {}
        return False, f"HTTP {response.status_code}: {body}", {}
    except Exception as e:
        return False, str(e), {}


def hostinger_list_domains() -> str:
    """List all domains in Hostinger account"""
    ok, err, data = _hostinger_get("/api/domains/v1/portfolio")
    if not ok:
        return f"❌ Error listando dominios: {err}"
    
    domains = data if isinstance(data, list) else data.get("domains", [])
    if not domains:
        return "📋 No hay dominios configurados en Hostinger"
    
    result = "📋 Dominios en Hostinger:\n"
    for dom in domains:
        if isinstance(dom, str):
            name = dom
            status = "unknown"
        else:
            name = dom.get("domain", dom.get("name", "unknown"))
            status = dom.get("status", dom.get("state", "unknown"))
        result += f"  • {name} ({status})\n"
    
    return result


def hostinger_list_dns_records(domain: str) -> str:
    """List DNS records for a domain"""
    domain = domain.strip().lower()
    if not domain:
        return "❌ domain es requerido"
    
    ok, err, data = _hostinger_get(f"/api/dns/v1/zones/{domain}")
    if not ok:
        return f"❌ Error listando registros DNS: {err}"
    
    records = data if isinstance(data, list) else data.get("records", [])
    if not records:
        return f"📋 No hay registros DNS para {domain}"
    
    result = f"📋 Registros DNS para {domain}:\n"
    for rec in records:
        rec_type = rec.get("type", "unknown")
        name = rec.get("name", "@")
        rec_values = rec.get("records", [])
        if isinstance(rec_values, list):
            value = ", ".join(str(x.get("content", "")) for x in rec_values if isinstance(x, dict))
        else:
            value = rec.get("value", "")
        ttl = rec.get("ttl", 3600)
        result += f"  • {rec_type} {name} → {value} (TTL: {ttl})\n"
    
    return result


def hostinger_upsert_dns_record(
    domain: str,
    record_type: str,
    name: str,
    value: str,
    ttl: int = 3600,
) -> str:
    """
    Create or update DNS record (A, CNAME, TXT, etc.)
    
    Args:
        domain: Domain name (e.g., "example.com")
        record_type: DNS record type (A, CNAME, TXT, MX, etc.)
        name: Record name (e.g., "@" for root, "www" for www.example.com)
        value: Record value (IP for A, domain for CNAME, etc.)
        ttl: TTL in seconds (default 3600)
    """
    domain = domain.strip().lower()
    record_type = record_type.strip().upper()
    name = name.strip().lower()
    value = value.strip()
    
    if not domain:
        return "❌ domain es requerido"
    if record_type not in ("A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV"):
        return f"❌ Tipo de registro inválido: {record_type}"
    if not value:
        return "❌ value es requerido"
    
    # Normalize name: "@" means root domain
    if name == "@" or name == domain:
        name = "@"
    elif not name.endswith(f".{domain}"):
        # If name is just "www", make it "www.example.com"
        if "." not in name:
            name = f"{name}.{domain}"
    
    payload = {
        "overwrite": True,
        "zone": [
            {
                "name": name,
                "type": record_type,
                "ttl": int(ttl),
                "records": [{"content": value}],
            }
        ],
    }
    ok, err, _ = _hostinger_put(f"/api/dns/v1/zones/{domain}", payload)
    if ok:
        return f"✅ Registro DNS upsert: {record_type} {name} → {value}"
    return f"❌ Error creando/actualizando registro: {err}"


def hostinger_delete_dns_record(domain: str, record_id: str, name: str = "", record_type: str = "") -> str:
    """Delete DNS record by filter (new API) or legacy record_id"""
    domain = domain.strip().lower()
    record_id = record_id.strip()
    
    # New API path: delete by filters
    if domain and name and record_type:
        payload = {"filters": [{"name": name, "type": record_type.upper()}]}
        ok, err, _ = _hostinger_delete_json(f"/api/dns/v1/zones/{domain}", payload)
        if ok:
            return f"✅ Registro DNS eliminado: {record_type} {name}"
        return f"❌ Error eliminando registro: {err}"

    if not domain or not record_id:
        return "❌ domain y (name+type) o record_id son requeridos"
    # Legacy fallback
    ok, err = _hostinger_delete(f"/domains/{domain}/dns-records/{record_id}")
    if ok:
        return f"✅ Registro DNS eliminado: {record_id}"
    return f"❌ Error eliminando registro: {err}"


def _find_dns_records(domain: str, record_name: str) -> List[Dict[str, Any]]:
    ok, err, data = _hostinger_get(f"/api/dns/v1/zones/{domain}")
    if not ok:
        raise RuntimeError(f"No pude leer DNS para rollback: {err}")
    records = data if isinstance(data, list) else data.get("records", [])
    matches = []
    for rec in records:
        name = str(rec.get("name", "")).strip().lower()
        if record_name == "@":
            if name in {"@", domain}:
                matches.append(rec)
        else:
            if name == record_name or name == f"{record_name}.{domain}":
                matches.append(rec)
    return matches


def _rec_contents(rec: Dict[str, Any]) -> List[str]:
    vals = rec.get("records", [])
    out: List[str] = []
    if isinstance(vals, list):
        for it in vals:
            if isinstance(it, dict):
                c = str(it.get("content", "")).strip()
                if c:
                    out.append(c)
    return out


def _delete_records_by_types(domain: str, record_name: str, allowed_types: set[str]) -> List[str]:
    logs: List[str] = []
    try:
        current = _find_dns_records(domain, record_name)
        for rec in current:
            rec_type = str(rec.get("type", "")).upper()
            if rec_type not in allowed_types:
                continue
            ok, err, _ = _hostinger_delete_json(
                f"/api/dns/v1/zones/{domain}",
                {"filters": [{"name": rec.get("name"), "type": rec.get("type")}]},
            )
            if ok:
                values = ", ".join(_rec_contents(rec))
                logs.append(f"🧹 DNS removido para evitar conflicto: {rec_type} {rec.get('name')} -> {values}")
            else:
                logs.append(f"⚠️ No pude limpiar {rec_type} {rec.get('name')}: {err}")
    except Exception as e:
        logs.append(f"⚠️ Limpieza de DNS conflictivo falló: {e}")
    return logs


def _extract_tunnel_id_from_token(token: str) -> str:
    token = (token or "").strip()
    if not token or len(token) < 20 or "." not in token:
        return ""
    try:
        import base64
        parts = token.split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1]
        padding = 4 - (len(payload) % 4)
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        token_data = json.loads(decoded)
        return str(token_data.get("t", "")).strip()
    except Exception:
        return ""


def _resolve_tunnel_service() -> str:
    # Default estable para contenedor cloudflared: enrutar al host donde WAF escucha en 80.
    return os.getenv("TUNNEL_ORIGIN_SERVICE", "http://host.docker.internal:80").strip()


def _best_proxy_target(use_cname: bool, proxy_ip: Optional[str]) -> Tuple[str, str]:
    """
    Return (record_type, value) using tunnel-first default.
    """
    force_tunnel = os.getenv("TOKIO_PROXY_FORCE_TUNNEL", "true").strip().lower() not in {"0", "false", "no"}
    if force_tunnel:
        use_cname = True
    if use_cname:
        cname_target = os.getenv("PROXY_CNAME_TARGET", "").strip()
        if not cname_target:
            raise RuntimeError(
                "PROXY_CNAME_TARGET no configurado para modo tunnel-first. "
                "Ej: <tunnel-id>.cfargotunnel.com"
            )
        # Backward-compatible convenience: allow only tunnel UUID and auto-expand.
        if "." not in cname_target and len(cname_target) == 36 and cname_target.count("-") == 4:
            cname_target = f"{cname_target}.cfargotunnel.com"
        if "://" in cname_target or "." not in cname_target:
            raise RuntimeError(
                "PROXY_CNAME_TARGET inválido. Debe ser un hostname DNS, "
                "por ejemplo: <tunnel-id>.cfargotunnel.com"
            )
        return "CNAME", cname_target

    # Legacy A-record mode (desaconsejado; puede requerir abrir puertos).
    value = (proxy_ip or "").strip()
    if not value:
        value = os.getenv("PROXY_PUBLIC_IP", "").strip()
    if not value:
        raise RuntimeError("PROXY_PUBLIC_IP no configurado y no se pasó proxy_ip")
    return "A", value


def _ensure_tunnel_ready(results: List[str]) -> None:
    """
    Best-effort tunnel readiness check/deploy (for tunnel-first mode).
    """
    try:
        from .tunnel_tools import tunnel_manager
        status_raw = tunnel_manager("status", {})
        status_data = json.loads(status_raw)
        current = str(status_data.get("result", ""))
        if "Up " in current:
            results.append("✅ Tunnel cloudflared operativo.")
            return
        deploy_raw = tunnel_manager("deploy", {})
        deploy_data = json.loads(deploy_raw)
        if deploy_data.get("ok"):
            results.append("✅ Tunnel cloudflared desplegado automáticamente.")
        else:
            results.append(f"⚠️ No pude desplegar tunnel automáticamente: {deploy_data.get('error')}")
    except Exception as e:
        results.append(f"⚠️ Verificación/despliegue de tunnel falló: {e}")


def _health_check_site(hostname: str, timeout: int = 15, domain: str = "", host: str = "@") -> Tuple[bool, str]:
    url_candidates = [f"https://{hostname}", f"http://{hostname}"]
    checked: List[str] = []
    for url in url_candidates:
        try:
            r = requests.get(url, timeout=timeout, headers={"Host": hostname})
            checked.append(f"{url}=HTTP{r.status_code}")
            if r.status_code < 500:
                return True, f"{url} -> HTTP {r.status_code}"
        except Exception as e:
            checked.append(f"{url}=ERR:{str(e)[:80]}")
            continue
    # Fallback: validate through current A record with Host header (avoids transient AAAA/cache issues).
    if domain:
        try:
            for rec in _find_dns_records(domain, host or "@"):
                if str(rec.get("type", "")).upper() != "A":
                    continue
                for ip in _rec_contents(rec):
                    if not ip:
                        continue
                    try:
                        r = requests.get(
                            f"http://{ip}",
                            headers={"Host": hostname},
                            timeout=timeout,
                        )
                        checked.append(f"http://{ip}=HTTP{r.status_code}")
                        if r.status_code < 500:
                            return True, f"http://{ip} (Host: {hostname}) -> HTTP {r.status_code}"
                    except Exception as e:
                        checked.append(f"http://{ip}=ERR:{str(e)[:80]}")
                        continue
        except Exception:
            pass
    return False, "No se pudo validar health-check HTTP/HTTPS. Intentos: " + "; ".join(checked[-6:])


def hostinger_dns(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Hostinger DNS management tool entry point
    
    Actions:
    - list_domains: List all domains
    - list_records: List DNS records for a domain (params: domain)
    - upsert_record: Create/update DNS record (params: domain, type, name, value, ttl)
    - delete_record: Delete DNS record (params: domain, name, type)
    """
    params = params or {}
    action = (action or "").strip().lower()
    
    try:
        if action == "list_domains":
            return hostinger_list_domains()
        elif action == "list_records":
            return hostinger_list_dns_records(str(params.get("domain", "")))
        elif action == "upsert_record":
            return hostinger_upsert_dns_record(
                domain=str(params.get("domain", "")),
                record_type=str(params.get("type", "")),
                name=str(params.get("name", "@")),
                value=str(params.get("value", "")),
                ttl=int(params.get("ttl", 3600)),
            )
        elif action == "delete_record":
            return hostinger_delete_dns_record(
                domain=str(params.get("domain", "")),
                record_id=str(params.get("record_id", "")),
                name=str(params.get("name", "")),
                record_type=str(params.get("type", "")),
            )
        else:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"acción no soportada: {action}",
                    "supported": ["list_domains", "list_records", "upsert_record", "delete_record"],
                },
                ensure_ascii=False,
            )
    except Exception as e:
        return json.dumps(
            {"ok": False, "action": action, "error": str(e)},
            ensure_ascii=False,
        )


def publish_site(
    domain: str,
    backend_url: str,
    name: Optional[str] = None,
    proxy_ip: Optional[str] = None,
    use_cname: bool = True,
    host: str = "@",
) -> str:
    """
    Publish a website behind TokioAI WAF proxy automatically.
    
    This function (tunnel-first):
    1. Creates tenant in WAF API
    2. Points DNS to tunnel target (CNAME by default)
    3. Runs health-check
    4. Persists rollback metadata
    
    Args:
        domain: Domain name (e.g., "example.com")
        backend_url: Backend URL (e.g., "http://YOUR_IP_ADDRESS:8080")
        name: Tenant name (defaults to domain)
        proxy_ip: Only used for A-record mode
        use_cname: True => CNAME tunnel-first (recommended), False => A record
        host: DNS host label ('@', 'www', etc.)
    
    Returns:
        Success/error message
    """
    domain = domain.strip().lower()
    backend_url = backend_url.strip()
    name = (name or domain).strip()
    
    if not domain:
        return "❌ domain es requerido"
    if not backend_url:
        return "❌ backend_url es requerido"
    if not backend_url.startswith(("http://", "https://")):
        return "❌ backend_url debe comenzar con http:// o https://"
    
    record_name = (host or "@").strip().lower()
    results = []
    state = _load_proxy_state()
    state.setdefault("sites", {})

    # DNS snapshot for rollback
    dns_before = []
    try:
        dns_before = _find_dns_records(domain, record_name)
    except Exception as e:
        results.append(f"⚠️ No pude tomar snapshot DNS previo: {e}")
    
    # Step 1: Create tenant in WAF
    dashboard_api_url = os.getenv("DASHBOARD_API_URL", "http://tokio-ai-dashboard-api:8000")
    tenant_id = None
    try:
        response = requests.post(
            f"{dashboard_api_url}/api/tenants",
            json={
                "name": name,
                "domain": domain,
                "backend_url": backend_url,
            },
            timeout=30,
        )
        if response.status_code in (200, 201):
            body = {}
            try:
                body = response.json()
            except Exception:
                pass
            tenant = body.get("tenant", {}) if isinstance(body, dict) else {}
            tenant_id = tenant.get("id")
            results.append(f"✅ Tenant creado en WAF: {domain} → {backend_url}")
        elif response.status_code == 400 and "ya existe" in (response.text or "").lower():
            results.append(f"ℹ️ Tenant {domain} ya existía en WAF (modo idempotente).")
        else:
            results.append(
                f"⚠️ Dashboard API respondió HTTP {response.status_code}. "
                "Seguiré con DNS, pero conviene revisar creación de tenant."
            )
    except Exception as e:
        results.append(
            f"⚠️ Error creando tenant en WAF: {str(e)}. "
            "Continuando con DNS..."
        )
    
    # Step 2: Update DNS in Hostinger
    try:
        fqdn = domain if record_name == "@" else f"{record_name}.{domain}"
        record_type, record_value = _best_proxy_target(use_cname=bool(use_cname), proxy_ip=proxy_ip)
        if record_type == "CNAME":
            # In tunnel mode, never keep apex/subhost A/AAAA records, to avoid mixed routing.
            results.extend(_delete_records_by_types(domain, record_name, {"A", "AAAA", "CNAME"}))
            _ensure_tunnel_ready(results)
            # Configure tunnel route via Cloudflare API for SSL
            try:
                from .cloudflare_api_tools import cloudflare_configure_tunnel_route
                tunnel_id = os.getenv("CLOUDFLARED_TUNNEL_ID", "").strip()
                if not tunnel_id:
                    token = os.getenv("CLOUDFLARED_TUNNEL_TOKEN", "").strip()
                    tunnel_id = _extract_tunnel_id_from_token(token)
                
                if tunnel_id:
                    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
                    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
                    if api_token and account_id:
                        ok_cf, msg_cf = cloudflare_configure_tunnel_route(
                            tunnel_id=tunnel_id,
                            account_id=account_id,
                            hostname=fqdn,
                            service=_resolve_tunnel_service(),
                            api_token=api_token,
                        )
                        if ok_cf:
                            results.append(f"✅ Ruta túnel Cloudflare configurada: {msg_cf}")
                        else:
                            results.append(f"⚠️ No pude configurar ruta túnel: {msg_cf}")
                    else:
                        results.append("ℹ️ CLOUDFLARE_API_TOKEN/ACCOUNT_ID no configurados (SSL puede no funcionar)")
            except Exception as e:
                results.append(f"⚠️ Error configurando ruta túnel: {e}")
        
        dns_result = hostinger_upsert_dns_record(
            domain=domain,
            record_type=record_type,
            name=record_name,
            value=record_value,
        )
        results.append(dns_result)

        # Step 3: Health-check
        ok_health, detail_health = _health_check_site(fqdn, timeout=20, domain=domain, host=record_name)
        if ok_health:
            results.append(f"✅ Health-check OK: {detail_health}")
        else:
            results.append(f"⚠️ Health-check no confirmado todavía: {detail_health}")

        # Persist state for future unpublish/rollback
        state["sites"][f"{record_name}.{domain}"] = {
            "domain": domain,
            "host": record_name,
            "backend_url": backend_url,
            "tenant_id": tenant_id,
            "mode": "cname" if record_type == "CNAME" else "a_record",
            "target": record_value,
            "dns_before": dns_before,
            "updated_at": _now_iso(),
        }
        _save_proxy_state(state)

    except Exception as e:
        results.append(f"❌ Error actualizando DNS: {str(e)}")

        # Rollback best-effort: remove new DNS and restore previous snapshot
        try:
            current = _find_dns_records(domain, record_name)
            for rec in current:
                if str(rec.get("type", "")).upper() in {"A", "CNAME"}:
                    _hostinger_delete_json(
                        f"/api/dns/v1/zones/{domain}",
                        {"filters": [{"name": rec.get("name"), "type": rec.get("type")}]},
                    )
            for rec in dns_before:
                contents = _rec_contents(rec)
                if not contents:
                    continue
                _hostinger_put(
                    f"/api/dns/v1/zones/{domain}",
                    {
                        "overwrite": True,
                        "zone": [
                            {
                                "name": rec.get("name"),
                                "type": rec.get("type"),
                                "ttl": int(rec.get("ttl", 3600)),
                                "records": [{"content": c} for c in contents],
                            }
                        ],
                    },
                )
            results.append("↩️ Rollback DNS aplicado (best effort).")
        except Exception as rb:
            results.append(f"⚠️ Rollback DNS falló: {rb}")
    
    return "\n".join(results)


def unpublish_site(domain: str, host: str = "@", keep_tenant: bool = False) -> str:
    """
    Remove site from proxy path:
    - remove proxy DNS A/CNAME
    - restore previous DNS snapshot when available
    - optionally keep tenant active
    """
    domain = (domain or "").strip().lower()
    host = (host or "@").strip().lower()
    if not domain:
        return "❌ domain es requerido"

    key = f"{host}.{domain}"
    state = _load_proxy_state()
    site = state.get("sites", {}).get(key, {})
    results = []

    try:
        current = _find_dns_records(domain, host)
        for rec in current:
            if str(rec.get("type", "")).upper() in {"A", "AAAA", "CNAME"}:
                ok, err, _ = _hostinger_delete_json(
                    f"/api/dns/v1/zones/{domain}",
                    {"filters": [{"name": rec.get("name"), "type": rec.get("type")}]},
                )
                if ok:
                    values = ", ".join(_rec_contents(rec))
                    results.append(f"✅ DNS eliminado: {rec.get('type')} {rec.get('name')} -> {values}")
                else:
                    results.append(f"⚠️ No pude eliminar registro {rec.get('type')} {rec.get('name')}: {err}")
    except Exception as e:
        results.append(f"⚠️ Error eliminando DNS proxy: {e}")

    # Best-effort: remove tunnel route from Cloudflare config.
    fqdn = domain if host == "@" else f"{host}.{domain}"
    try:
        from .cloudflare_api_tools import cloudflare_remove_tunnel_route
        api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        tunnel_id = os.getenv("CLOUDFLARED_TUNNEL_ID", "").strip() or _extract_tunnel_id_from_token(
            os.getenv("CLOUDFLARED_TUNNEL_TOKEN", "")
        )
        if api_token and account_id and tunnel_id:
            ok_cf, msg_cf = cloudflare_remove_tunnel_route(
                tunnel_id=tunnel_id,
                account_id=account_id,
                hostname=fqdn,
                api_token=api_token,
            )
            if ok_cf:
                results.append(f"✅ Ruta túnel eliminada: {msg_cf}")
            else:
                results.append(f"⚠️ No pude eliminar ruta de túnel: {msg_cf}")
    except Exception as e:
        results.append(f"⚠️ Error eliminando ruta Cloudflare: {e}")

    # Restore old records if available
    dns_before = site.get("dns_before", []) if isinstance(site, dict) else []
    if dns_before:
        restored = 0
        for rec in dns_before:
            contents = _rec_contents(rec)
            if not contents:
                continue
            ok, err, _ = _hostinger_put(
                f"/api/dns/v1/zones/{domain}",
                {
                    "overwrite": True,
                    "zone": [
                        {
                            "name": rec.get("name"),
                            "type": rec.get("type"),
                            "ttl": int(rec.get("ttl", 3600)),
                            "records": [{"content": c} for c in contents],
                        }
                    ],
                },
            )
            if ok:
                restored += 1
        results.append(f"↩️ Restaurados {restored} registro(s) DNS previos.")
    else:
        results.append("ℹ️ No había snapshot DNS previo para restaurar.")

    # Optional tenant cleanup
    if not keep_tenant:
        tenant_id = site.get("tenant_id")
        if tenant_id:
            dashboard_api_url = os.getenv("DASHBOARD_API_URL", "http://tokio-ai-dashboard-api:8000")
            try:
                r = requests.delete(f"{dashboard_api_url}/api/tenants/{tenant_id}", timeout=20)
                if r.status_code in (200, 204):
                    results.append(f"✅ Tenant WAF eliminado (id={tenant_id}).")
                else:
                    results.append(f"⚠️ No pude eliminar tenant WAF id={tenant_id} (HTTP {r.status_code}).")
            except Exception as e:
                results.append(f"⚠️ Error eliminando tenant WAF: {e}")

    # Update state
    if key in state.get("sites", {}):
        del state["sites"][key]
        _save_proxy_state(state)

    return "\n".join(results)


def proxy_logs(domain: str, host: str = "@") -> str:
    """
    Unified status view for proxy publication state + DNS + health.
    """
    domain = (domain or "").strip().lower().strip(".")
    host = (host or "@").strip().lower()
    # Defensive normalization: LLM sometimes sends invalid placeholders as host labels.
    if host in {"", "root", "apex", "default", "localhost", "none", "null"}:
        host = "@"
    if not domain:
        return "❌ domain es requerido"
    # Accept "www.example.com" in domain param and split automatically.
    if "." in domain and host == "@":
        parts = domain.split(".")
        if len(parts) > 2:
            host = parts[0]
            domain = ".".join(parts[1:])
    fqdn = domain if host == "@" else f"{host}.{domain}"

    lines = [f"📡 Estado proxy para {fqdn}"]
    state = _load_proxy_state()
    key = f"{host}.{domain}"
    sites = state.get("sites", {}) if isinstance(state, dict) else {}
    site = None
    if key in sites:
        site = sites[key]
    elif host == "@":
        # Fallback: if root host not found, try any known host for this domain.
        suffix = f".{domain}"
        for k, v in sites.items():
            if isinstance(k, str) and k.endswith(suffix):
                site = v
                lines.append(f"- estado local: encontrado por fallback en key={k}")
                break

    if site:
        lines.append(f"- modo: {site.get('mode')}")
        lines.append(f"- target: {site.get('target')}")
        lines.append(f"- backend_url: {site.get('backend_url')}")
        lines.append(f"- updated_at: {site.get('updated_at')}")
    else:
        # Extra fallback: if requested host label is unknown, try common labels.
        if host not in {"@", "www"}:
            for alt_host in ("@", "www"):
                alt_key = f"{alt_host}.{domain}"
                if alt_key in sites:
                    site = sites[alt_key]
                    lines.append(f"- estado local: no hallado en '{host}', usando fallback host='{alt_host}'")
                    lines.append(f"- modo: {site.get('mode')}")
                    lines.append(f"- target: {site.get('target')}")
                    lines.append(f"- backend_url: {site.get('backend_url')}")
                    lines.append(f"- updated_at: {site.get('updated_at')}")
                    host = alt_host
                    fqdn = domain if host == "@" else f"{host}.{domain}"
                    lines[0] = f"📡 Estado proxy para {fqdn}"
                    break
        if not site:
            lines.append("- estado local: no registrado en TOKIO proxy state")

    try:
        dns = _find_dns_records(domain, host)
        if dns:
            lines.append("- DNS actual:")
            for rec in dns:
                values = ", ".join(_rec_contents(rec))
                lines.append(f"  • {rec.get('type')} {rec.get('name')} -> {values}")
        else:
            lines.append("- DNS actual: sin registros para ese host")
    except Exception as e:
        lines.append(f"- DNS actual: error {e}")

    ok_health, detail = _health_check_site(fqdn, timeout=12, domain=domain, host=host)
    lines.append(f"- health_check: {'ok' if ok_health else 'warning'} ({detail})")
    return "\n".join(lines)
