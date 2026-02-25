#!/usr/bin/env python3
"""TokioAI WAF Dashboard v2 — OWASP, Filters, Date Navigation, Fibonacci Logo."""
import os, json, secrets, time
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import jwt as pyjwt

DASH_USER = os.getenv("DASHBOARD_USER", "admin")
DASH_PASS = os.getenv("DASHBOARD_PASSWORD", "PrXtjL5EXrnP27wUwSz6dIoW")
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGO = "HS256"
JWT_EXP_HOURS = 24

PG = dict(
    host=os.getenv("POSTGRES_HOST", "postgres"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    dbname=os.getenv("POSTGRES_DB", "soc_ai"),
    user=os.getenv("POSTGRES_USER", "soc_user"),
    password=os.getenv("POSTGRES_PASSWORD", "changeme_gcp_2026"),
)

app = FastAPI(title="TokioAI WAF Dashboard", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)


def get_db():
    conn = psycopg2.connect(**PG)
    conn.autocommit = True
    return conn


def ensure_schema():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS waf_logs (
        id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(),
        ip TEXT, method TEXT, uri TEXT, status INT, body_bytes_sent INT DEFAULT 0,
        user_agent TEXT, host TEXT, referer TEXT, request_time FLOAT DEFAULT 0,
        severity TEXT DEFAULT 'info', blocked BOOLEAN DEFAULT FALSE,
        tenant_id TEXT, raw_log JSONB, classification_source TEXT,
        owasp_code TEXT, owasp_name TEXT, sig_id TEXT, threat_type TEXT,
        action TEXT DEFAULT 'log_only', confidence REAL,
        kafka_offset BIGINT, kafka_partition INT
    );
    CREATE INDEX IF NOT EXISTS idx_wl_ts ON waf_logs(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_wl_ip ON waf_logs(ip);
    CREATE INDEX IF NOT EXISTS idx_wl_sev ON waf_logs(severity);
    CREATE INDEX IF NOT EXISTS idx_wl_tt ON waf_logs(threat_type);
    CREATE INDEX IF NOT EXISTS idx_wl_ow ON waf_logs(owasp_code);

    CREATE TABLE IF NOT EXISTS episodes (
        id BIGSERIAL PRIMARY KEY, episode_id TEXT UNIQUE,
        attack_type TEXT, severity TEXT DEFAULT 'medium', src_ip TEXT,
        start_time TIMESTAMPTZ, end_time TIMESTAMPTZ,
        total_requests INT DEFAULT 0, blocked_requests INT DEFAULT 0,
        sample_uris TEXT, intelligence_analysis TEXT,
        status TEXT DEFAULT 'active', ml_label TEXT, ml_confidence FLOAT,
        description TEXT, owasp_code TEXT, owasp_name TEXT, risk_score REAL DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(),
        tenant_id TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ep_st ON episodes(start_time DESC);

    CREATE TABLE IF NOT EXISTS blocked_ips (
        id BIGSERIAL PRIMARY KEY, ip TEXT NOT NULL, reason TEXT,
        blocked_at TIMESTAMPTZ DEFAULT NOW(), expires_at TIMESTAMPTZ,
        active BOOLEAN DEFAULT TRUE, tenant_id TEXT, blocked_by TEXT,
        threat_type TEXT, severity TEXT DEFAULT 'high',
        episode_id TEXT, auto_blocked BOOLEAN DEFAULT FALSE,
        block_type TEXT DEFAULT 'manual', risk_score REAL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_bi_ip ON blocked_ips(ip);
    CREATE INDEX IF NOT EXISTS idx_bi_act ON blocked_ips(active);

    CREATE TABLE IF NOT EXISTS block_audit_log (
        id BIGSERIAL PRIMARY KEY, ip TEXT, action TEXT, reason TEXT,
        performed_by TEXT DEFAULT 'system', created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    cur.close()
    conn.close()


@app.on_event("startup")
async def startup():
    ensure_schema()
    sync_blocklist()


# ─── Auth ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


def create_token(username: str) -> str:
    return pyjwt.encode({
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXP_HOURS),
    }, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not creds:
        raise HTTPException(401, "Token requerido")
    try:
        return pyjwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])["sub"]
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expirado")
    except Exception:
        raise HTTPException(401, "Token inválido")


@app.post("/api/auth/login")
def login(req: LoginRequest):
    if req.username == DASH_USER and req.password == DASH_PASS:
        return {"token": create_token(req.username), "expires_in": JWT_EXP_HOURS * 3600}
    raise HTTPException(401, "Credenciales inválidas")


@app.get("/health")
def health():
    try:
        c = get_db(); c.close()
        return {"status": "healthy", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": str(e)}


# ─── API ──────────────────────────────────────────────────────────────────────
@app.get("/api/summary")
def summary(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    user: str = Depends(verify_token)
):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        df, dt, params = _date_filter(date_from, date_to)
        w = f"WHERE timestamp >= %s AND timestamp <= %s"
        cur.execute(f"""
            SELECT COUNT(*) total,
                   COUNT(CASE WHEN blocked THEN 1 END) blocked,
                   COUNT(DISTINCT ip) unique_ips,
                   COUNT(CASE WHEN severity='critical' THEN 1 END) critical,
                   COUNT(CASE WHEN severity='high' THEN 1 END) high,
                   COUNT(CASE WHEN severity='medium' THEN 1 END) medium,
                   COUNT(CASE WHEN severity='low' THEN 1 END) low
            FROM waf_logs {w}
        """, [df, dt])
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) c FROM episodes WHERE status='active'")
        ep = cur.fetchone()
        cur.execute("SELECT COUNT(*) c FROM blocked_ips WHERE active=true")
        bl = cur.fetchone()
        cur.close(); conn.close()
        return {**row, "active_episodes": ep["c"], "active_blocks": bl["c"]}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/attacks/recent")
def recent_attacks(
    limit: int = Query(1000, ge=1, le=50000, description="Número de logs a retornar (1-50000)"), 
    offset: int = 0,
    severity: Optional[str] = None, ip: Optional[str] = None,
    threat_type: Optional[str] = None, owasp_code: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    user: str = Depends(verify_token)
):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        df, dt, _ = _date_filter(date_from, date_to)
        clauses = ["timestamp >= %s", "timestamp <= %s"]
        params = [df, dt]
        if severity:
            clauses.append("severity = %s"); params.append(severity)
        if ip:
            clauses.append("ip = %s"); params.append(ip)
        if threat_type:
            clauses.append("threat_type = %s"); params.append(threat_type)
        if owasp_code:
            clauses.append("owasp_code = %s"); params.append(owasp_code)
        if search:
            clauses.append("(uri ILIKE %s OR ip ILIKE %s OR user_agent ILIKE %s OR host ILIKE %s)")
            s = f"%{search}%"
            params.extend([s, s, s, s])
        where = " WHERE " + " AND ".join(clauses)
        q = f"""SELECT timestamp,ip,method,uri,status,severity,blocked,host,user_agent,
                       request_time,threat_type,owasp_code,owasp_name,sig_id,action,confidence
                FROM waf_logs{where} ORDER BY timestamp DESC LIMIT %s OFFSET %s"""
        params.extend([limit, offset])
        cur.execute(q, params)
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/episodes")
def episodes(
    limit: int = 30, status: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    user: str = Depends(verify_token)
):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        df, dt, _ = _date_filter(date_from, date_to)
        clauses = ["start_time >= %s", "start_time <= %s"]
        params = [df, dt]
        if status:
            clauses.append("status = %s"); params.append(status)
        where = " WHERE " + " AND ".join(clauses)
        cur.execute(f"""SELECT episode_id, attack_type, severity, src_ip,
                        start_time, end_time, total_requests, sample_uris,
                        status, ml_label, ml_confidence, description,
                        owasp_code, owasp_name, risk_score
                        FROM episodes{where} ORDER BY start_time DESC LIMIT %s""", params + [limit])
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/blocked")
def blocked_list(user: str = Depends(verify_token)):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT ip, reason, threat_type, severity, blocked_at, expires_at,
                              auto_blocked, block_type, risk_score, episode_id
                       FROM blocked_ips WHERE active=true ORDER BY blocked_at DESC LIMIT 200""")
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


BLOCKLIST_PATH = os.getenv("BLOCKLIST_PATH", "/blocklist/blocked.conf")


def sync_blocklist():
    """Sync blocked IPs from DB to nginx blocklist file."""
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT ip FROM blocked_ips WHERE active=true")
        ips = [row[0] for row in cur.fetchall()]
        cur.close(); conn.close()
        lines = ["# TokioAI WAF Blocklist — auto-generated", f"# Updated: {datetime.now(timezone.utc).isoformat()}", f"# Total blocked: {len(ips)}"]
        for ip in ips:
            lines.append(f"deny {ip};")
        lines.append("# End blocklist")
        content = "\n".join(lines) + "\n"
        bdir = os.path.dirname(BLOCKLIST_PATH)
        if bdir and not os.path.exists(bdir):
            os.makedirs(bdir, exist_ok=True)
        with open(BLOCKLIST_PATH, "w") as f:
            f.write(content)
        print(f"[blocklist] Synced {len(ips)} IPs to {BLOCKLIST_PATH}", flush=True)
    except Exception as e:
        print(f"[blocklist] Sync error: {e}", flush=True)


class BlockIPRequest(BaseModel):
    ip: str
    reason: str = "Manual block"
    duration_hours: int = 24


@app.post("/api/blocked")
def block_ip(req: BlockIPRequest, user: str = Depends(verify_token)):
    try:
        conn = get_db(); cur = conn.cursor()
        expires = datetime.now(timezone.utc) + timedelta(hours=req.duration_hours)
        cur.execute("DELETE FROM blocked_ips WHERE ip=%s", (req.ip,))
        cur.execute("""INSERT INTO blocked_ips (ip, reason, expires_at, active, auto_blocked, block_type)
                       VALUES (%s, %s, %s, true, false, 'manual')""",
                    (req.ip, req.reason, expires))
        cur.execute("INSERT INTO block_audit_log (ip, action, reason, performed_by) VALUES (%s, 'block', %s, %s)",
                    (req.ip, req.reason, user))
        cur.close(); conn.close()
        sync_blocklist()
        return {"ok": True, "ip": req.ip, "expires_at": str(expires)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.delete("/api/blocked/{ip}")
def unblock_ip(ip: str, user: str = Depends(verify_token)):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE blocked_ips SET active=false WHERE ip=%s AND active=true", (ip,))
        cur.execute("INSERT INTO block_audit_log (ip,action,reason,performed_by) VALUES (%s,'unblock','manual',%s)", (ip, user))
        cur.close(); conn.close()
        sync_blocklist()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/top_ips")
def top_ips(
    hours: int = 24,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    user: str = Depends(verify_token)
):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        df, dt, _ = _date_filter(date_from, date_to)
        cur.execute("""
            SELECT ip, COUNT(*) hits,
                   COUNT(CASE WHEN severity IN ('high','critical') THEN 1 END) threats,
                   COUNT(DISTINCT uri) unique_uris,
                   COUNT(DISTINCT threat_type) attack_types,
                   MAX(severity) max_severity
            FROM waf_logs
            WHERE ip NOT IN ('unknown','-','','YOUR_IP_ADDRESS')
              AND timestamp >= %s AND timestamp <= %s
            GROUP BY ip ORDER BY threats DESC, hits DESC LIMIT 25
        """, (df, dt))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/timeline")
def timeline(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    user: str = Depends(verify_token)
):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        df, dt, _ = _date_filter(date_from, date_to)
        cur.execute("""
            SELECT date_trunc('hour', timestamp) as hour,
                   COUNT(*) total,
                   COUNT(CASE WHEN blocked THEN 1 END) blocked,
                   COUNT(CASE WHEN severity IN ('high','critical') THEN 1 END) threats
            FROM waf_logs WHERE timestamp >= %s AND timestamp <= %s
            GROUP BY 1 ORDER BY 1
        """, (df, dt))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/owasp_breakdown")
def owasp_breakdown(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    user: str = Depends(verify_token)
):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        df, dt, _ = _date_filter(date_from, date_to)
        cur.execute("""
            SELECT owasp_code, owasp_name, COUNT(*) cnt,
                   COUNT(DISTINCT ip) unique_ips
            FROM waf_logs
            WHERE owasp_code IS NOT NULL AND timestamp >= %s AND timestamp <= %s
            GROUP BY owasp_code, owasp_name ORDER BY cnt DESC
        """, (df, dt))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/audit")
def audit_log(limit: int = 50, user: str = Depends(verify_token)):
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM block_audit_log ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_serialize(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}


def _date_filter(date_from, date_to):
    now = datetime.now(timezone.utc)
    if date_from:
        try:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
        except Exception:
            df = now - timedelta(days=7)  # Default to 7 days instead of 24 hours
    else:
        df = now - timedelta(days=7)  # Default to 7 days instead of 24 hours
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        except Exception:
            dt = now
    else:
        dt = now
    return df, dt, []


def _serialize(row):
    return {k: str(v) if v is not None else None for k, v in row.items()}


# ─── Dashboard HTML ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TokioAI WAF — Security Operations Center</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#0a0e1a;--card:#111827;--card2:#1a2035;--border:#1e293b;--primary:#00d4ff;--danger:#ef4444;
--warning:#f59e0b;--success:#22c55e;--text:#e2e8f0;--text2:#94a3b8;--accent:#8b5cf6;--gradient:linear-gradient(135deg,#00d4ff,#8b5cf6)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.login-overlay{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;z-index:9999}
.login-box{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:40px;width:400px;text-align:center}
.login-box .logo-wrap{margin-bottom:20px}
.login-box h1{color:var(--primary);font-size:24px;margin-bottom:4px;font-weight:700}
.login-box .sub{color:var(--text2);margin-bottom:24px;font-size:13px;letter-spacing:1px;text-transform:uppercase}
.login-box input{width:100%;padding:12px 16px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:14px;margin-bottom:12px;outline:none;transition:border .2s}
.login-box input:focus{border-color:var(--primary)}
.login-box button{width:100%;padding:13px;background:var(--gradient);border:none;border-radius:8px;color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:opacity .2s}
.login-box button:hover{opacity:.9}
.login-error{color:var(--danger);font-size:13px;margin-top:8px;display:none}
.app{display:none}
.topbar{background:var(--card);border-bottom:1px solid var(--border);padding:10px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.topbar .left{display:flex;align-items:center;gap:12px}
.topbar .logo-sm{width:32px;height:32px}
.topbar h1{font-size:18px;color:var(--primary);white-space:nowrap}
.topbar .right{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.topbar .status{font-size:11px;color:var(--success)}
.btn-sm{padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--card2);color:var(--text);cursor:pointer;font-size:12px;transition:all .2s;white-space:nowrap}
.btn-sm:hover{border-color:var(--primary);color:var(--primary)}
.btn-danger{border-color:var(--danger);color:var(--danger)}
.btn-primary{background:var(--gradient);border:none;color:#fff;font-weight:600}
/* Filters bar */
.filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 24px;background:var(--card);border-bottom:1px solid var(--border)}
.filters input,.filters select{padding:7px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px;outline:none}
.filters input:focus,.filters select:focus{border-color:var(--primary)}
.filters input[type=date]{width:140px}
.filters input[type=text]{width:180px}
.filters label{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px}
.filter-group{display:flex;flex-direction:column;gap:3px}
.container{max-width:1500px;margin:0 auto;padding:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px}
.stat-card .label{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px}
.stat-card .value{font-size:24px;font-weight:700;margin-top:2px}
.stat-card .value.primary{color:var(--primary)}.stat-card .value.danger{color:var(--danger)}
.stat-card .value.warning{color:var(--warning)}.stat-card .value.success{color:var(--success)}
.stat-card .value.accent{color:var(--accent)}
.row-2{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:16px}
.tabs{display:flex;gap:4px;margin-bottom:12px;background:var(--card);border-radius:10px;padding:4px;border:1px solid var(--border)}
.tab{padding:7px 14px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:500;color:var(--text2);transition:all .2s}
.tab.active{background:var(--gradient);color:#fff;font-weight:600}
.tab:hover:not(.active){color:var(--text)}
.panel{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.panel-header{padding:12px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.panel-header h3{font-size:14px;font-weight:600}
table{width:100%;border-collapse:collapse}
th{background:var(--card2);padding:8px 12px;text-align:left;font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;font-weight:600;position:sticky;top:0;z-index:1}
td{padding:8px 12px;border-top:1px solid var(--border);font-size:12px}
tr:hover td{background:rgba(0,212,255,.03)}
.badge{padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;text-transform:uppercase;white-space:nowrap}
.badge.critical{background:rgba(239,68,68,.15);color:#ef4444}
.badge.high{background:rgba(245,158,11,.15);color:#f59e0b}
.badge.medium{background:rgba(139,92,246,.15);color:#8b5cf6}
.badge.low{background:rgba(34,197,94,.15);color:#22c55e}
.badge.info{background:rgba(100,116,139,.15);color:#94a3b8}
.badge.active{background:rgba(0,212,255,.15);color:#00d4ff}
.badge.resolved{background:rgba(100,116,139,.15);color:#64748b}
.badge.blocked{background:rgba(239,68,68,.15);color:#ef4444}
.badge.owasp{background:rgba(0,212,255,.1);color:#00d4ff;border:1px solid rgba(0,212,255,.3)}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;height:220px}
.owasp-box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px}
.owasp-item{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)}
.owasp-item:last-child{border:none}
.owasp-item .code{font-weight:700;color:var(--primary);font-size:13px;min-width:36px}
.owasp-item .name{flex:1;font-size:12px;color:var(--text2);margin-left:8px}
.owasp-item .cnt{font-weight:700;font-size:14px}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;align-items:center;justify-content:center}
.modal{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px;width:420px}
.modal h3{margin-bottom:16px;color:var(--primary)}
.modal input,.modal select{width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);margin-bottom:10px}
.modal .actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.table-wrap{max-height:480px;overflow-y:auto}
.table-wrap::-webkit-scrollbar{width:5px}
.table-wrap::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.risk-bar{width:60px;height:6px;background:var(--border);border-radius:3px;overflow:hidden;display:inline-block;vertical-align:middle}
.risk-bar .fill{height:100%;border-radius:3px}
.mono{font-family:'Courier New',monospace;font-size:11px}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.row-2{grid-template-columns:1fr}.container{padding:10px}.filters{flex-direction:column}}

/* ─── Animated Spiral Logo ─── */
.spiral-logo{position:relative;display:inline-flex;align-items:center;justify-content:center}
.spiral-logo .glow-bg{position:absolute;border-radius:50%;background:radial-gradient(circle,rgba(0,255,200,.08) 0%,transparent 70%);animation:sp-pulse 3s ease-in-out infinite}
.spiral-md{width:80px;height:80px}
.spiral-md .glow-bg{width:80px;height:80px}
.spiral-md svg{width:80px;height:80px}
.spiral-sm{width:32px;height:32px}
.spiral-sm .glow-bg{width:32px;height:32px}
.spiral-sm svg{width:32px;height:32px}
@keyframes sp-pulse{0%,100%{transform:scale(1);opacity:.6}50%{transform:scale(1.15);opacity:1}}
.ring-1{animation:sp-cw 8s linear infinite;transform-origin:100px 100px}
.ring-2{animation:sp-ccw 12s linear infinite;transform-origin:100px 100px}
.ring-3{animation:sp-cw 6s linear infinite;transform-origin:100px 100px}
.ring-4{animation:sp-ccw 16s linear infinite;transform-origin:100px 100px}
.ring-5{animation:sp-cw 10s linear infinite;transform-origin:100px 100px}
@keyframes sp-cw{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@keyframes sp-ccw{from{transform:rotate(0deg)}to{transform:rotate(-360deg)}}
.spiral-path{animation:sp-cw 5s linear infinite;transform-origin:100px 100px}
.core-anim{animation:sp-core 2s ease-in-out infinite;transform-origin:100px 100px}
@keyframes sp-core{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.3);opacity:.7}}
.orbit-dot{animation:sp-cw 4s linear infinite;transform-origin:100px 100px}
.orbit-dot-2{animation:sp-ccw 6s linear infinite;transform-origin:100px 100px}
.orbit-dot-3{animation:sp-cw 9s linear infinite;transform-origin:100px 100px}
.badge.normal{background:rgba(34,197,94,.12);color:#22c55e}
</style>
</head>
<body>

<!-- Login -->
<div class="login-overlay" id="loginOverlay">
<div class="login-box">
  <div class="logo-wrap"><div class="spiral-logo spiral-md" id="loginLogo"></div></div>
  <h1>TokioAI WAF</h1>
  <div class="sub">Security Operations Center</div>
  <input type="text" id="loginUser" placeholder="Usuario" autocomplete="username">
  <input type="password" id="loginPass" placeholder="Contraseña" autocomplete="current-password">
  <button onclick="doLogin()"><i class="fas fa-shield-halved"></i> Iniciar sesión</button>
  <div class="login-error" id="loginError">Credenciales inválidas</div>
</div>
</div>

<!-- App -->
<div class="app" id="app">
<div class="topbar">
  <div class="left">
    <div class="spiral-logo spiral-sm" id="topLogo"></div>
    <h1>TokioAI WAF</h1>
  </div>
  <div class="right">
    <span class="status" id="liveStatus"><i class="fas fa-circle"></i> Live</span>
    <button class="btn-sm" onclick="refreshAll()"><i class="fas fa-sync-alt"></i></button>
    <button class="btn-sm btn-danger" onclick="logout()"><i class="fas fa-sign-out-alt"></i> Salir</button>
  </div>
</div>

<!-- Filters -->
<div class="filters">
  <div class="filter-group"><label>Desde</label><input type="datetime-local" id="fDateFrom"></div>
  <div class="filter-group"><label>Hasta</label><input type="datetime-local" id="fDateTo"></div>
  <div class="filter-group"><label>IP</label><input type="text" id="fIp" placeholder="ej: YOUR_IP_ADDRESS"></div>
  <div class="filter-group"><label>Buscar URI/Pattern</label><input type="text" id="fSearch" placeholder="ej: wp-login, .env"></div>
  <div class="filter-group"><label>Severidad</label>
    <select id="fSeverity"><option value="">Todas</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="info">Info</option></select></div>
  <div class="filter-group"><label>OWASP</label>
    <select id="fOwasp"><option value="">Todos</option><option value="A01">A01 Access Control</option><option value="A03">A03 Injection</option><option value="A05">A05 Misconfig</option><option value="A07">A07 Auth Failures</option><option value="A10">A10 SSRF</option></select></div>
  <div class="filter-group"><label>Tipo Amenaza</label>
    <select id="fThreat"><option value="">Todos</option><option value="SQLI">SQLI</option><option value="XSS">XSS</option><option value="CMD_INJECTION">CMD Injection</option><option value="PATH_TRAVERSAL">Path Traversal</option><option value="SCAN_PROBE">Scanner/Probe</option><option value="BRUTE_FORCE">Brute Force</option><option value="SSRF">SSRF</option><option value="XXE">XXE</option><option value="EXPLOIT_ATTEMPT">Exploit Attempt</option><option value="RECON_IP">Recon IP</option><option value="BOT">Bot</option></select></div>
  <div class="filter-group"><label>Límite</label>
    <select id="fLimit" onchange="loadAttacks()"><option value="100">100</option><option value="200">200</option><option value="500">500</option><option value="1000" selected>1000</option><option value="2000">2000</option><option value="5000">5000</option><option value="10000">10000</option></select></div>
  <button class="btn-sm btn-primary" onclick="applyFilters()" style="margin-top:auto"><i class="fas fa-search"></i> Filtrar</button>
  <button class="btn-sm" onclick="resetFilters()" style="margin-top:auto"><i class="fas fa-times"></i> Limpiar</button>
  <div style="display:flex;gap:4px;margin-top:auto">
    <button class="btn-sm" onclick="setHourFilter(1)" title="Última hora">1h</button>
    <button class="btn-sm" onclick="setHourFilter(6)" title="Últimas 6 horas">6h</button>
    <button class="btn-sm" onclick="setHourFilter(24)" title="Últimas 24 horas">24h</button>
    <button class="btn-sm" onclick="setHourFilter(168)" title="Última semana">7d</button>
  </div>
  <button class="btn-sm" onclick="prevDay()" style="margin-top:auto" title="Día anterior"><i class="fas fa-chevron-left"></i></button>
  <button class="btn-sm" onclick="todayFilter()" style="margin-top:auto" title="Hoy"><i class="fas fa-calendar-day"></i></button>
  <button class="btn-sm" onclick="nextDay()" style="margin-top:auto" title="Día siguiente"><i class="fas fa-chevron-right"></i></button>
</div>

<div class="container">
  <div class="stats" id="statsRow"></div>
  <div class="row-2">
    <div class="chart-box"><canvas id="timelineChart"></canvas></div>
    <div class="owasp-box"><h4 style="color:var(--primary);margin-bottom:10px;font-size:13px"><i class="fas fa-shield-halved"></i> OWASP Top 10</h4><div id="owaspList"></div></div>
  </div>
  <div class="tabs">
    <div class="tab active" data-tab="attacks" onclick="switchTab('attacks')"><i class="fas fa-signal"></i> Tráfico</div>
    <div class="tab" data-tab="episodes" onclick="switchTab('episodes')"><i class="fas fa-layer-group"></i> Episodios</div>
    <div class="tab" data-tab="blocked" onclick="switchTab('blocked')"><i class="fas fa-ban"></i> Bloqueados</div>
    <div class="tab" data-tab="topips" onclick="switchTab('topips')"><i class="fas fa-ranking-star"></i> Top IPs</div>
    <div class="tab" data-tab="audit" onclick="switchTab('audit')"><i class="fas fa-clipboard-list"></i> Auditoría</div>
  </div>
  <div id="panel-attacks" class="panel">
    <div class="panel-header"><h3>Tráfico Reciente</h3>
      <button class="btn-sm btn-danger" onclick="showBlockModal()"><i class="fas fa-ban"></i> Bloquear IP</button></div>
    <div class="table-wrap"><table><thead><tr><th>Hora</th><th>IP</th><th>Método</th><th>URI</th><th>Status</th><th>Severidad</th><th>Amenaza</th><th>OWASP</th><th>Firma</th><th>Host</th></tr></thead><tbody id="attacksBody"></tbody></table></div>
  </div>
  <div id="panel-episodes" class="panel" style="display:none">
    <div class="panel-header"><h3>Episodios de Ataque</h3></div>
    <div class="table-wrap"><table><thead><tr><th>ID</th><th>Tipo</th><th>OWASP</th><th>IP</th><th>Requests</th><th>Risk</th><th>Inicio</th><th>Severidad</th><th>Estado</th><th>Descripción</th></tr></thead><tbody id="episodesBody"></tbody></table></div>
  </div>
  <div id="panel-blocked" class="panel" style="display:none">
    <div class="panel-header"><h3>IPs Bloqueadas</h3>
      <button class="btn-sm" onclick="showBlockModal()"><i class="fas fa-plus"></i> Agregar</button></div>
    <div class="table-wrap"><table><thead><tr><th>IP</th><th>Razón</th><th>Tipo Bloqueo</th><th>Amenaza</th><th>Risk</th><th>Desde</th><th>Expira</th><th>Auto</th><th>Acción</th></tr></thead><tbody id="blockedBody"></tbody></table></div>
  </div>
  <div id="panel-topips" class="panel" style="display:none">
    <div class="panel-header"><h3>Top IPs</h3></div>
    <div class="table-wrap"><table><thead><tr><th>IP</th><th>Hits</th><th>Amenazas</th><th>URIs</th><th>Tipos</th><th>Max Sev</th><th>Acción</th></tr></thead><tbody id="topipsBody"></tbody></table></div>
  </div>
  <div id="panel-audit" class="panel" style="display:none">
    <div class="panel-header"><h3>Log de Auditoría</h3></div>
    <div class="table-wrap"><table><thead><tr><th>Fecha</th><th>IP</th><th>Acción</th><th>Razón</th><th>Por</th></tr></thead><tbody id="auditBody"></tbody></table></div>
  </div>
</div>
</div>

<!-- Block Modal -->
<div class="modal-overlay" id="blockModal" onclick="if(event.target===this)this.style.display='none'">
<div class="modal">
  <h3><i class="fas fa-ban"></i> Bloquear IP</h3>
  <input type="text" id="blockIp" placeholder="IP (ej: YOUR_IP_ADDRESS)">
  <input type="text" id="blockReason" placeholder="Razón" value="Comportamiento sospechoso">
  <select id="blockDuration"><option value="1">1 hora</option><option value="6">6 horas</option><option value="24" selected>24 horas</option><option value="168">7 días</option><option value="720">30 días</option></select>
  <div class="actions">
    <button class="btn-sm" onclick="document.getElementById('blockModal').style.display='none'">Cancelar</button>
    <button class="btn-sm btn-danger" onclick="doBlock()"><i class="fas fa-ban"></i> Bloquear</button>
  </div>
</div>
</div>

<script>
// ─── Animated Spiral Logo (SVG injected) ─────────────────────────────────────
function drawSpiralLogo(el){
  const svgMarkup=`<div class="glow-bg"></div>
  <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">
    <defs>
      <filter id="glow"><feGaussianBlur stdDeviation="2.5" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <filter id="glow-strong"><feGaussianBlur stdDeviation="4" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <linearGradient id="spiralGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#00ffc8" stop-opacity="0"/><stop offset="50%" stop-color="#00d4ff" stop-opacity="1"/><stop offset="100%" stop-color="#7b5ea7" stop-opacity="0.6"/></linearGradient>
    </defs>
    <g class="ring-1"><polygon points="100,18 174,59 174,141 100,182 26,141 26,59" fill="none" stroke="#00ffc8" stroke-width="1" stroke-dasharray="8 4" opacity="0.4" filter="url(#glow)"/></g>
    <g class="ring-2"><circle cx="100" cy="100" r="68" fill="none" stroke="#7b5ea7" stroke-width="1" stroke-dasharray="3 9" opacity="0.6" filter="url(#glow)"/></g>
    <g class="ring-3"><rect x="44" y="44" width="112" height="112" rx="4" fill="none" stroke="#00d4ff" stroke-width="0.8" stroke-dasharray="5 6" opacity="0.35" filter="url(#glow)"/></g>
    <g class="ring-4"><circle cx="100" cy="100" r="52" fill="none" stroke="#ff6b9d" stroke-width="0.8" stroke-dasharray="2 6" opacity="0.4" filter="url(#glow)"/></g>
    <g class="ring-5"><polygon points="100,62 131,78 138,112 117,138 83,138 62,112 69,78" fill="none" stroke="#00ffc8" stroke-width="0.8" stroke-dasharray="4 5" opacity="0.3" filter="url(#glow)"/></g>
    <g class="spiral-path"><path d="M 100 100 Q 100 88, 110 84 Q 126 80, 130 93 Q 136 112, 120 124 Q 100 138, 82 126 Q 62 112, 68 88 Q 76 64, 100 60 Q 130 56, 146 78 Q 158 100, 148 124 Q 136 150, 110 158 Q 80 164, 60 146" fill="none" stroke="url(#spiralGrad)" stroke-width="2" stroke-linecap="round" opacity="0.9" filter="url(#glow)"/></g>
    <g class="orbit-dot"><circle cx="100" cy="18" r="3.5" fill="#00ffc8" filter="url(#glow-strong)"/></g>
    <g class="orbit-dot-2"><circle cx="168" cy="100" r="2.5" fill="#7b5ea7" filter="url(#glow-strong)"/></g>
    <g class="orbit-dot-3"><circle cx="100" cy="48" r="2" fill="#ff6b9d" filter="url(#glow-strong)"/></g>
    <g class="core-anim"><polygon points="100,86 112,107 88,107" fill="none" stroke="#00ffc8" stroke-width="1.5" opacity="0.8" filter="url(#glow)"/><circle cx="100" cy="100" r="5" fill="#00ffc8" opacity="0.9" filter="url(#glow-strong)"/><circle cx="100" cy="100" r="2" fill="#ffffff"/></g>
  </svg>`;
  el.innerHTML=svgMarkup;
}
document.querySelectorAll('.spiral-logo').forEach(drawSpiralLogo);

// ─── State ───────────────────────────────────────────────────────────────────
let TOKEN=localStorage.getItem('tokio_waf_token');
let chart=null;
const API='';
let currentDate=new Date();

// ─── Auth ────────────────────────────────────────────────────────────────────
function doLogin(){
  const u=document.getElementById('loginUser').value,p=document.getElementById('loginPass').value;
  fetch(API+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})})
  .then(r=>{if(!r.ok)throw r;return r.json()}).then(d=>{
    TOKEN=d.token;localStorage.setItem('tokio_waf_token',TOKEN);
    document.getElementById('loginOverlay').style.display='none';
    document.getElementById('app').style.display='block';
    initDateFilters();refreshAll();
  }).catch(()=>{document.getElementById('loginError').style.display='block'});
}
function logout(){TOKEN=null;localStorage.removeItem('tokio_waf_token');location.reload()}
function authFetch(url){return fetch(url,{headers:{'Authorization':'Bearer '+TOKEN}}).then(r=>{if(r.status===401){logout();throw'auth'}return r.json()})}

if(TOKEN){
  document.getElementById('loginOverlay').style.display='none';
  document.getElementById('app').style.display='block';
  initDateFilters();refreshAll();
}
document.getElementById('loginPass').addEventListener('keypress',e=>{if(e.key==='Enter')doLogin()});

// ─── Date Filters ────────────────────────────────────────────────────────────
function initDateFilters(){
  const now=new Date();
  const from=new Date(now);from.setHours(0,0,0,0);
  document.getElementById('fDateFrom').value=toLocalISO(from);
  document.getElementById('fDateTo').value=toLocalISO(now);
}
function toLocalISO(d){return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}
function getDateParams(){
  const f=document.getElementById('fDateFrom').value;
  const t=document.getElementById('fDateTo').value;
  let p='';
  if(f)p+=`&date_from=${new Date(f).toISOString()}`;
  if(t)p+=`&date_to=${new Date(t).toISOString()}`;
  return p;
}
function getFilterParams(){
  let p=getDateParams();
  const ip=document.getElementById('fIp').value;if(ip)p+=`&ip=${encodeURIComponent(ip)}`;
  const s=document.getElementById('fSearch').value;if(s)p+=`&search=${encodeURIComponent(s)}`;
  const sev=document.getElementById('fSeverity').value;if(sev)p+=`&severity=${sev}`;
  const ow=document.getElementById('fOwasp').value;if(ow)p+=`&owasp_code=${ow}`;
  const tt=document.getElementById('fThreat').value;if(tt)p+=`&threat_type=${tt}`;
  return p;
}
function applyFilters(){refreshAll()}
function resetFilters(){
  document.getElementById('fIp').value='';document.getElementById('fSearch').value='';
  document.getElementById('fSeverity').value='';document.getElementById('fOwasp').value='';
  document.getElementById('fThreat').value='';initDateFilters();refreshAll();
}
function prevDay(){
  const el=document.getElementById('fDateFrom');const d=new Date(el.value);d.setDate(d.getDate()-1);
  const d2=new Date(d);d2.setHours(23,59,59);
  document.getElementById('fDateFrom').value=toLocalISO(d);
  document.getElementById('fDateTo').value=toLocalISO(d2);refreshAll();
}
function nextDay(){
  const el=document.getElementById('fDateFrom');const d=new Date(el.value);d.setDate(d.getDate()+1);
  const d2=new Date(d);d2.setHours(23,59,59);
  document.getElementById('fDateFrom').value=toLocalISO(d);
  document.getElementById('fDateTo').value=toLocalISO(d2);refreshAll();
}
function todayFilter(){initDateFilters();refreshAll()}
function setHourFilter(hours){
  const now=new Date();
  const from=new Date(now.getTime()-hours*3600000);
  document.getElementById('fDateFrom').value=toLocalISO(from);
  document.getElementById('fDateTo').value=toLocalISO(now);
  refreshAll();
}

// ─── Refresh ─────────────────────────────────────────────────────────────────
function refreshAll(){loadStats();loadTimeline();loadOwasp();loadAttacks();loadEpisodes();loadBlocked();loadTopIps();loadAudit()}

function loadStats(){
  authFetch(API+'/api/summary?'+getDateParams().slice(1)).then(d=>{
    document.getElementById('statsRow').innerHTML=`
      <div class="stat-card"><div class="label">Requests</div><div class="value primary">${d.total||0}</div></div>
      <div class="stat-card"><div class="label">Bloqueados</div><div class="value danger">${d.blocked||0}</div></div>
      <div class="stat-card"><div class="label">IPs Únicas</div><div class="value success">${d.unique_ips||0}</div></div>
      <div class="stat-card"><div class="label">Critical</div><div class="value danger">${d.critical||0}</div></div>
      <div class="stat-card"><div class="label">High</div><div class="value warning">${d.high||0}</div></div>
      <div class="stat-card"><div class="label">Medium</div><div class="value accent">${d.medium||0}</div></div>
      <div class="stat-card"><div class="label">Episodios</div><div class="value warning">${d.active_episodes||0}</div></div>
      <div class="stat-card"><div class="label">IPs Block</div><div class="value danger">${d.active_blocks||0}</div></div>`;
  }).catch(()=>{});
}

function loadTimeline(){
  authFetch(API+'/api/timeline?'+getDateParams().slice(1)).then(data=>{
    if(!Array.isArray(data))return;
    const labels=data.map(d=>new Date(d.hour).toLocaleTimeString('es',{hour:'2-digit',minute:'2-digit'}));
    const totals=data.map(d=>parseInt(d.total));
    const threats=data.map(d=>parseInt(d.threats));
    const blocked=data.map(d=>parseInt(d.blocked));
    if(chart)chart.destroy();
    chart=new Chart(document.getElementById('timelineChart'),{
      type:'line',data:{labels,datasets:[
        {label:'Total',data:totals,borderColor:'#00d4ff',backgroundColor:'rgba(0,212,255,.08)',fill:true,tension:.4,borderWidth:2,pointRadius:1},
        {label:'Amenazas',data:threats,borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,.08)',fill:true,tension:.4,borderWidth:2,pointRadius:1},
        {label:'Bloqueados',data:blocked,borderColor:'#ef4444',backgroundColor:'rgba(239,68,68,.08)',fill:true,tension:.4,borderWidth:2,pointRadius:1}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#94a3b8',font:{size:11}}}},
        scales:{x:{ticks:{color:'#475569',font:{size:10}},grid:{color:'#1e293b'}},y:{ticks:{color:'#475569',font:{size:10}},grid:{color:'#1e293b'}}}}
    });
  }).catch(()=>{});
}

function loadOwasp(){
  authFetch(API+'/api/owasp_breakdown?'+getDateParams().slice(1)).then(data=>{
    if(!Array.isArray(data)){document.getElementById('owaspList').innerHTML='<div style="color:var(--text2);font-size:12px">Sin datos</div>';return}
    document.getElementById('owaspList').innerHTML=data.map(r=>{
      const colors={'A01':'#ef4444','A03':'#f59e0b','A05':'#8b5cf6','A07':'#3b82f6','A10':'#22c55e'};
      return `<div class="owasp-item"><span class="code" style="color:${colors[r.owasp_code]||'var(--primary)'}">${r.owasp_code||'?'}</span><span class="name">${r.owasp_name||'Unknown'}</span><span class="cnt" style="color:${colors[r.owasp_code]||'var(--text)'}">${r.cnt}</span></div>`;
    }).join('')||'<div style="color:var(--text2);font-size:12px">Sin datos OWASP</div>';
  }).catch(()=>{});
}

function loadAttacks(){
  const limit=document.getElementById('fLimit')?parseInt(document.getElementById('fLimit').value)||1000:1000;
  const loadingMsg='<tr><td colspan="10" style="text-align:center;color:var(--text2);padding:20px"><i class="fas fa-spinner fa-spin"></i> Cargando logs...</td></tr>';
  document.getElementById('attacksBody').innerHTML=loadingMsg;
  authFetch(API+`/api/attacks/recent?limit=${limit}`+getFilterParams()).then(data=>{
    if(!Array.isArray(data)){document.getElementById('attacksBody').innerHTML='<tr><td colspan="10" style="text-align:center;color:var(--text2);padding:12px">Sin datos</td></tr>';return;}
    const count=data.length;
    const rows=data.map(r=>`
      <tr><td class="mono">${fmtTime(r.timestamp)}</td><td><strong>${r.ip||'-'}</strong></td><td>${r.method||'-'}</td>
      <td title="${esc(r.uri||'')}" class="mono">${(r.uri||'-').substring(0,45)}</td><td>${r.status||'-'}</td>
      <td><span class="badge ${r.severity==='info'||!r.severity?'normal':r.severity}">${r.severity==='info'||!r.severity?'normal':r.severity}</span></td>
      <td>${r.threat_type&&r.threat_type!='None'?'<span class="badge medium">'+r.threat_type+'</span>':'-'}</td>
      <td>${r.owasp_code&&r.owasp_code!='None'?'<span class="badge owasp">'+r.owasp_code+'</span>':'-'}</td>
      <td class="mono">${r.sig_id&&r.sig_id!='None'?r.sig_id:'-'}</td>
      <td>${r.host||'-'}</td></tr>`).join('');
    const limitMsg=count>=limit?`<tr><td colspan="10" style="text-align:center;color:var(--warning);padding:12px;font-weight:600"><i class="fas fa-info-circle"></i> Mostrando ${count} logs (límite alcanzado). Aumentá el límite o ajustá los filtros de fecha para ver más.</td></tr>`:'';
    const summaryMsg=`<tr><td colspan="10" style="text-align:center;color:var(--text2);padding:8px;font-size:11px">Total: ${count} logs mostrados</td></tr>`;
    document.getElementById('attacksBody').innerHTML=rows+limitMsg+summaryMsg;
  }).catch(err=>{
    document.getElementById('attacksBody').innerHTML='<tr><td colspan="10" style="text-align:center;color:var(--danger);padding:12px">Error al cargar logs</td></tr>';
    console.error('Error loading attacks:',err);
  });
}

function loadEpisodes(){
  authFetch(API+'/api/episodes?limit=50'+getDateParams()).then(data=>{
    if(!Array.isArray(data))return;
    document.getElementById('episodesBody').innerHTML=data.map(r=>{
      const risk=parseFloat(r.risk_score)||0;
      const riskColor=risk>=0.75?'#ef4444':risk>=0.5?'#f59e0b':risk>=0.25?'#8b5cf6':'#22c55e';
      return `<tr><td class="mono">${(r.episode_id||'').substring(0,12)}</td><td>${r.attack_type||'-'}</td>
      <td>${r.owasp_code&&r.owasp_code!='None'?'<span class="badge owasp">'+r.owasp_code+'</span>':'-'}</td>
      <td><strong>${r.src_ip||'-'}</strong></td><td>${r.total_requests||0}</td>
      <td><div class="risk-bar"><div class="fill" style="width:${risk*100}%;background:${riskColor}"></div></div> ${(risk*100).toFixed(0)}%</td>
      <td class="mono">${fmtTime(r.start_time)}</td>
      <td><span class="badge ${r.severity||'medium'}">${r.severity||'medium'}</span></td>
      <td><span class="badge ${r.status||'active'}">${r.status||'active'}</span></td>
      <td title="${esc(r.description||'')}">${(r.description||'-').substring(0,60)}</td></tr>`;
    }).join('');
  }).catch(()=>{});
}

function loadBlocked(){
  authFetch(API+'/api/blocked').then(data=>{
    if(!Array.isArray(data))return;
    document.getElementById('blockedBody').innerHTML=data.map(r=>{
      const risk=parseFloat(r.risk_score)||0;
      const riskColor=risk>=0.75?'#ef4444':risk>=0.5?'#f59e0b':'#22c55e';
      return `<tr><td><strong>${r.ip}</strong></td><td title="${esc(r.reason||'')}">${(r.reason||'-').substring(0,40)}</td>
      <td><span class="badge ${r.block_type==='signature'?'critical':r.block_type==='episode'?'warning':'info'}">${r.block_type||'manual'}</span></td>
      <td>${r.threat_type||'-'}</td>
      <td><div class="risk-bar"><div class="fill" style="width:${risk*100}%;background:${riskColor}"></div></div></td>
      <td class="mono">${fmtTime(r.blocked_at)}</td><td class="mono">${fmtTime(r.expires_at)}</td>
      <td>${r.auto_blocked==='True'?'<i class="fas fa-robot" style="color:var(--primary)"></i>':'<i class="fas fa-user" style="color:var(--text2)"></i>'}</td>
      <td><button class="btn-sm btn-danger" onclick="doUnblock('${r.ip}')"><i class="fas fa-unlock"></i></button></td></tr>`;
    }).join('');
  }).catch(()=>{});
}

function loadTopIps(){
  authFetch(API+'/api/top_ips?'+getDateParams().slice(1)).then(data=>{
    if(!Array.isArray(data))return;
    document.getElementById('topipsBody').innerHTML=data.map(r=>`
      <tr><td><strong>${r.ip}</strong></td><td>${r.hits}</td><td style="color:${parseInt(r.threats)>0?'var(--danger)':'var(--text2)'}">${r.threats}</td>
      <td>${r.unique_uris}</td><td>${r.attack_types||'-'}</td>
      <td><span class="badge ${r.max_severity||'info'}">${r.max_severity||'-'}</span></td>
      <td><button class="btn-sm btn-danger" onclick="blockIpQuick('${r.ip}')"><i class="fas fa-ban"></i></button></td></tr>`).join('');
  }).catch(()=>{});
}

function loadAudit(){
  authFetch(API+'/api/audit?limit=50').then(data=>{
    if(!Array.isArray(data))return;
    document.getElementById('auditBody').innerHTML=data.map(r=>`
      <tr><td class="mono">${fmtTime(r.created_at)}</td><td><strong>${r.ip||'-'}</strong></td>
      <td><span class="badge ${r.action==='block'?'blocked':'active'}">${r.action}</span></td>
      <td>${r.reason||'-'}</td><td>${r.performed_by||'-'}</td></tr>`).join('');
  }).catch(()=>{});
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function fmtTime(t){if(!t||t==='None')return'-';try{return new Date(t).toLocaleString('es-AR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return t}}
function esc(s){return s?s.replace(/"/g,'&quot;').replace(/</g,'&lt;'):''}
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  ['attacks','episodes','blocked','topips','audit'].forEach(p=>document.getElementById('panel-'+p).style.display=p===name?'':'none');
}
function showBlockModal(){document.getElementById('blockModal').style.display='flex'}
function doBlock(){
  const ip=document.getElementById('blockIp').value.trim();
  const reason=document.getElementById('blockReason').value.trim()||'Manual block';
  const dur=parseInt(document.getElementById('blockDuration').value)||24;
  if(!ip||!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)){alert('Ingresá una IP válida (ej: YOUR_IP_ADDRESS)');return}
  fetch(API+'/api/blocked',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+TOKEN},body:JSON.stringify({ip:ip,reason:reason,duration_hours:dur})})
  .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()})
  .then(d=>{
    if(d.ok){document.getElementById('blockModal').style.display='none';document.getElementById('blockIp').value='';alert('✅ IP '+ip+' bloqueada');refreshAll()}
    else{alert('❌ Error: '+(d.error||'desconocido'))}
  }).catch(e=>{alert('❌ Error de red: '+e.message)});
}
function doUnblock(ip){if(confirm('¿Desbloquear '+ip+'?'))fetch(API+'/api/blocked/'+ip,{method:'DELETE',headers:{'Authorization':'Bearer '+TOKEN}}).then(r=>{if(!r.ok)throw r;return r.json()}).then(()=>{alert('✅ IP '+ip+' desbloqueada');refreshAll()}).catch(e=>{alert('❌ Error al desbloquear')})}
function blockIpQuick(ip){document.getElementById('blockIp').value=ip;showBlockModal()}

setInterval(refreshAll,30000);
</script>
</body>
</html>"""
