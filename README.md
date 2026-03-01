<div align="center">

```
████████╗ ██████╗ ██╗  ██╗██╗ ██████╗      █████╗ ██╗
╚══██╔══╝██╔═══██╗██║ ██╔╝██║██╔═══██╗    ██╔══██╗██║
   ██║   ██║   ██║█████╔╝ ██║██║   ██║    ███████║██║
   ██║   ██║   ██║██╔═██╗ ██║██║   ██║    ██╔══██║██║
   ██║   ╚██████╔╝██║  ██╗██║╚██████╔╝    ██║  ██║██║
   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝     ╚═╝  ╚═╝╚═╝
```

### Autonomous AI Agent Framework

**Connect an LLM to your entire infrastructure. Not a chatbot — an agent that gets things done.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue?style=for-the-badge)](LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](#telegram-bot)

<br>

*TokioAI connects Claude, GPT, or Gemini to your servers, databases, Docker containers, IoT devices, DNS, and cloud infrastructure through a secure tool-calling architecture.*

[Getting Started](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [WAF Dashboard](#-waf-dashboard) · [Custom Tools](#-adding-custom-tools)

</div>

---

## Demo

```
🌀 tokio> restart the nginx container and show me the last 20 lines of its logs

  🔧 docker restart nginx...
  🔧 docker logs --tail 20 nginx...

✅ Container nginx restarted successfully.

Last 20 lines:
2026/03/01 14:23:01 [notice] 1#1: signal process started
2026/03/01 14:23:01 [notice] 1#1: using the "epoll" event method
2026/03/01 14:23:01 [notice] 1#1: nginx/1.25.4
2026/03/01 14:23:01 [notice] 1#1: start worker processes
...

🌀 tokio> _
```

---

## 🧬 Philosophy

Most "AI tools" are chatbots with a nice UI. You type, it talks back. That's it.

**TokioAI was built with a different belief: AI should execute, not just respond.**

The world doesn't need another chatbot. It needs an agent that can restart your containers at 3 AM, query your database when something breaks, block an attacker's IP in real-time, and SSH into your server to fix what's wrong — all while you sleep.

TokioAI is built by a security architect who got tired of switching between 15 terminals, 8 dashboards, and 3 cloud consoles to do what one intelligent agent could do in seconds. Every tool in this framework exists because it solved a real problem in production, not because it looked good in a demo.

**Principles:**
- **Execute, don't chat** — Every tool does something real. No decorative features.
- **Security first** — Three layers of protection because an agent with bash access is a weapon. Treat it like one.
- **Own your infra** — Self-hosted, no SaaS dependencies, your data stays on your machines.
- **Simple > clever** — Python, Docker, PostgreSQL. No Kubernetes, no microservices, no buzzwords.

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🤖 Multi-Provider LLM
- **Anthropic Claude** (Direct API or Vertex AI)
- **OpenAI GPT** (GPT-4o, GPT-4, etc.)
- **Google Gemini** (Flash, Pro)
- Automatic fallback between providers

</td>
<td width="50%">

### 🛡️ Security Layers
- **Prompt Guard** — WAF for LLM prompts (injection detection + audit log to PostgreSQL)
- **Input Sanitizer** — Blocks reverse shells, crypto miners, fork bombs, SQL injection
- **API Auth** — Key-based authentication + rate limiting
- **Telegram ACL** — Owner-based access control

</td>
</tr>
<tr>
<td>

### 🔧 30+ Built-in Tools
| Category | Tools |
|:---------|:------|
| System | `bash`, `python`, `read_file`, `write_file` |
| Network | `curl`, `wget` |
| Docker | `ps`, `logs`, `start/stop/restart`, `exec`, `stats` |
| Database | `postgres_query` (SQL injection protected) |
| SSH | `host_control` (remote server management) |
| IoT | `home_assistant` (lights, sensors, automations) |
| Cloud | `gcp_waf`, `gcp_compute` (full GCP management) |
| DNS | `hostinger` (DNS record management) |
| Router | `router` (OpenWrt management) |
| Tunnels | `cloudflared` (Cloudflare tunnels) |
| Docs | `document` (generate PDF, PPTX, CSV) |
| Calendar | `calendar` (Google Calendar) |
| Tasks | `task_orchestrator` (multi-step automation) |
| Security | `prompt_guard` (injection detection) |

</td>
<td>

### 🧠 Agent Engine
- Multi-round tool-calling loop with automatic retry
- **Session memory** — Conversation history in PostgreSQL
- **Workspace memory** — Persistent notes across sessions
- **Error learning** — Remembers failures to avoid repeating them
- **Context builder** — Dynamic system prompts based on available tools
- **Container watchdog** — Auto-restarts crashed containers
- **Plugin system** — Drop-in custom tools

</td>
</tr>
</table>

---

## 📱 Three Interfaces

<table>
<tr>
<td width="33%" align="center"><h3>💻 CLI</h3></td>
<td width="33%" align="center"><h3>🌐 REST API</h3></td>
<td width="33%" align="center"><h3>📲 Telegram Bot</h3></td>
</tr>
<tr>
<td>

Interactive terminal with Rich formatting

```
╔══════════════════════════╗
║  ████████╗ ██████╗  ...  ║
║  Autonomous AI Agent v2  ║
╚══════════════════════════╝

LLM: Claude 3.5 Sonnet
Tools: 32 disponibles

🌀 tokio> _
```

</td>
<td>

FastAPI server with auth & CORS

```bash
curl -X POST localhost:8000/chat \
  -H "Authorization: Bearer KEY" \
  -d '{"message": "list containers"}'

# Response:
{
  "response": "Running containers:\n
    nginx (Up 3 days)\n
    postgres (Up 3 days)",
  "tools_used": ["docker"],
  "tokens": 847
}
```

</td>
<td>

Full multimedia support:
- 📷 **Images** — Analyzed via Vision API
- 🎤 **Voice** — Transcribed via Whisper/Gemini
- 🎵 **Audio** files
- 📄 **Documents** (PDF, DOCX, CSV, code)
- 🔗 **YouTube** link analysis
- 📎 **File generation** (PDF, CSV, PPTX sent back to you)

</td>
</tr>
</table>

---

## 🚀 Quick Start

### Option 1: Docker (easiest)

```bash
git clone https://github.com/TokioAI/tokioai-v1.8.git tokioai
cd tokioai
cp .env.example .env

# Edit .env — set at least ANTHROPIC_API_KEY (or OPENAI_API_KEY or GEMINI_API_KEY)
nano .env

docker compose up -d
```

This starts 3 containers: **PostgreSQL**, **TokioAI API** (port 8200), and **Telegram bot** (if configured).

### Option 2: Setup Wizard

```bash
git clone https://github.com/TokioAI/tokioai-v1.8.git tokioai
cd tokioai
python3 -m venv venv && source venv/bin/activate
pip install -e .
tokio setup
```

> The wizard walks you through LLM provider, database, Telegram, and optional features — then generates `.env` and `docker-compose.yml`.

### Option 3: Manual Setup

```bash
git clone https://github.com/TokioAI/tokioai-v1.8.git tokioai
cd tokioai

cp .env.example .env
# Edit .env — set your API key

python3 -m venv venv && source venv/bin/activate
pip install -e .

# Interactive CLI
tokio

# Or start API server
tokio server
```

### CLI Commands

```bash
tokio              # Interactive chat session
tokio server       # Start REST API server
tokio setup        # Run setup wizard
tokio "message"    # Single message mode (non-interactive)
```

---

## ⚙️ Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in your values.

### Required

| Variable | Description |
|:---------|:------------|
| `LLM_PROVIDER` | `anthropic`, `openai`, or `gemini` |
| `ANTHROPIC_API_KEY` | Claude API key (or use Vertex AI) |
| `POSTGRES_PASSWORD` | PostgreSQL password |

### LLM via Vertex AI (optional — for Claude on GCP)

> Only needed if you prefer using Claude through Google Cloud instead of the direct Anthropic API.

| Variable | Description |
|:---------|:------------|
| `USE_ANTHROPIC_VERTEX` | `true` to use Vertex AI |
| `GCP_PROJECT_ID` | Your GCP project |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON |
| `ANTHROPIC_VERTEX_REGION` | Region (e.g., `us-east5`) |

### Optional Features

| Variable | Description |
|:---------|:------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_OWNER_ID` | Your Telegram user ID |
| `HOST_SSH_HOST` | Remote server for SSH control |
| `HOME_ASSISTANT_URL` | Home Assistant instance URL |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token |
| `HOSTINGER_API_TOKEN` | Hostinger DNS API token |

See `.env.example` for the full list.

---

## 🏗️ Architecture

```
                         ┌─────────────────┐
                         │    Telegram Bot  │
                         │  (multimedia,    │
                         │   voice, images) │
                         └────────┬────────┘
                                  │
  ┌───────────┐           ┌───────┴───────┐           ┌─────────────────┐
  │           │           │               │           │   Agent Loop    │
  │    CLI    │──────────>│   FastAPI      │──────────>│  (multi-round   │
  │  (Rich)   │           │   Server      │           │   tool-calling) │
  │           │           │               │           │                 │
  └───────────┘           └───────────────┘           └────────┬────────┘
                                                               │
                                                    ┌──────────┴──────────┐
                                                    │   Tool Executor     │
                                                    │  ┌────────────────┐ │
                                                    │  │ Circuit Breaker│ │
                                                    │  │ Timeouts       │ │
                                                    │  │ Error Recovery │ │
                                                    │  └────────────────┘ │
                                                    └──────────┬──────────┘
                                                               │
                    ┌──────────────┬───────────────┬───────────┼──────────────┐
                    │              │               │           │              │
              ┌─────┴────┐  ┌─────┴─────┐  ┌─────┴────┐ ┌────┴─────┐ ┌─────┴─────┐
              │  System  │  │  Docker   │  │ Database │ │   SSH    │ │   Cloud   │
              │ bash     │  │ ps/logs   │  │ postgres │ │ host_ctl │ │ gcp_waf   │
              │ python   │  │ restart   │  │ query    │ │ curl     │ │ IoT/DNS   │
              │ files    │  │ exec      │  │          │ │ wget     │ │ tunnels   │
              └──────────┘  └───────────┘  └──────────┘ └──────────┘ └───────────┘

                    ┌──────────────────────────────────────────────────────┐
                    │                  Security Layers                    │
                    │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
                    │  │ Prompt Guard │  │   Input      │  │  Secure   │ │
                    │  │ (WAF for LLM │  │  Sanitizer   │  │  Channel  │ │
                    │  │  prompts)    │  │ (cmd filter) │  │ (API auth)│ │
                    │  └──────────────┘  └──────────────┘  └───────────┘ │
                    └──────────────────────────────────────────────────────┘

                    ┌──────────────────────────────────────────────────────┐
                    │                   Persistence                      │
                    │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
                    │  │   Session    │  │  Workspace   │  │   Error   │ │
                    │  │   Memory    │  │   Memory     │  │  Learner  │ │
                    │  │ (PostgreSQL) │  │ (cross-sess) │  │ (failures)│ │
                    │  └──────────────┘  └──────────────┘  └───────────┘ │
                    └──────────────────────────────────────────────────────┘
```

### Key Modules

| Module | Description | Lines |
|:-------|:------------|------:|
| `engine/agent.py` | Multi-round agent loop with tool calling | 462 |
| `engine/tools/executor.py` | Async execution with timeouts and circuit breaker | 210 |
| `engine/tools/builtin/loader.py` | Registers all 30+ built-in tools | 542 |
| `engine/security/prompt_guard.py` | Prompt injection WAF with PostgreSQL audit log | 223 |
| `engine/security/input_sanitizer.py` | Command/SQL/path sanitization | 161 |
| `engine/memory/session.py` | Conversation persistence | 152 |
| `engine/memory/workspace.py` | Cross-session persistent memory | 283 |
| `engine/llm/` | Multi-provider LLM abstraction | 6 files |
| `bots/telegram_bot.py` | Full multimedia Telegram bot | 1127 |
| `setup_wizard.py` | Interactive setup wizard | 707 |

---

## 🔒 Security

TokioAI has **three security layers** that protect against prompt injection, dangerous commands, and unauthorized access:

### Layer 1: Prompt Guard (LLM WAF)
Detects and blocks prompt injection attacks **before** they reach the LLM:
- Role override attempts (`"ignore previous instructions"`)
- System prompt extraction (`"print your system prompt"`)
- Delimiter injection (`"```system"`, `"<|endoftext|>"`)
- Encoding attacks (base64/hex-encoded injections)
- Tool abuse patterns (`"call bash with rm -rf"`)

All attempts are logged to PostgreSQL with timestamp, risk level, categories, and input preview.

### Layer 2: Input Sanitizer
Blocks dangerous commands **before** tool execution:
- Reverse shells (`nc -e`, `bash -i`)
- Crypto miners (`xmrig`, `stratum://`)
- Fork bombs (`:(){ :|:& };:`)
- Destructive commands (`rm -rf /`, `mkfs`, `dd if=/dev/zero`)
- SQL injection (`'; DROP TABLE`)
- Path traversal (`../../etc/passwd`)

### Layer 3: Secure Channel
- API key authentication for REST endpoints
- Rate limiting per client
- Telegram ACL with owner-only admin commands

---

## 🚢 Deployment Modes

The setup wizard (`tokio setup`) lets you choose how to deploy:

| Mode | What runs locally | What runs in cloud | Best for |
|:-----|:------------------|:-------------------|:---------|
| **1. Full Local** (default) | Everything — CLI, API, Telegram bot, PostgreSQL | Nothing | Development, testing, personal use |
| **2. Hybrid** | TokioAI CLI + tools | WAF, Kafka, PostgreSQL on GCP | Production with local agent control |
| **3. Full Cloud** | Nothing | Everything in GCP | Headless servers, max availability |

> **Note:** Mode 1 is the default and works perfectly without any cloud account. The WAF/GCP modules (`tokio_cloud/`) are entirely optional — the core agent, CLI, API, and Telegram bot work 100% standalone.

---

## 🌐 WAF Dashboard (Optional)

> **This section is optional.** The core TokioAI agent works perfectly without the WAF. Deploy the WAF only if you want to protect a web application with real-time attack detection.

TokioAI includes a complete **Web Application Firewall** with a cyberpunk-themed SOC dashboard.

### Dashboard Features

```
┌──────────────────────────────────────────────────────────────────────┐
│  ◉ TokioAI WAF          v3-supreme                  ● LIVE    🔄  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Requests │ │ Blocked  │ │ Unique   │ │ Critical │ │ Episodes │  │
│  │  12,847  │ │    342   │ │  1,205   │ │     47   │ │     12   │  │
│  │  ▲ 23%   │ │          │ │          │ │          │ │          │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                                      │
│  ┌────────────────────────────────────┐ ┌──────────────────────┐    │
│  │  📊 Traffic Timeline              │ │ 🛡️ OWASP Top 10     │    │
│  │  ████                      ██     │ │                      │    │
│  │  █████                    ████    │ │  A01  Broken Access  │    │
│  │  ██████      ███         ██████   │ │  A03  Injection      │    │
│  │  ████████  ██████  ████ ████████  │ │  A07  XSS            │    │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │ │  A10  SSRF           │    │
│  └────────────────────────────────────┘ └──────────────────────┘    │
│                                                                      │
│  ┌────────────────────────────────────┐ ┌──────────────────────┐    │
│  │  🌍 Attack Origins (World Map)    │ │ 🔴 LIVE ATTACKS      │    │
│  │                                    │ │                      │    │
│  │     ·  ··                          │ │ ● 45.33.x.x SQLI    │    │
│  │    ·    ···   ····  ····           │ │   /api/users?id=1'   │    │
│  │          ··    ··   · ·            │ │                      │    │
│  │      ·                     🎯      │ │ ● 91.xx.x.x XSS     │    │
│  │       ·                            │ │   /search?q=<script> │    │
│  │                 ·                  │ │                      │    │
│  │               ·                    │ │ ● 185.x.x.x SCAN    │    │
│  └────────────────────────────────────┘ │   /.env              │    │
│                                         └──────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ 📊 Trafico │ 📋 Episodios │ 🚫 Bloqueados │ 🏆 Top IPs │  │    │
│  │ 🔍 Signatures │ ⛓️ Kill Chain │ 📝 Auditoria              │    │
│  ├──────────────────────────────────────────────────────────────┤    │
│  │ Hora      IP            Method  URI           Sev    Threat │    │
│  │ 14:23:01  45.33.32.x    GET     /api/users    HIGH   SQLI   │    │
│  │ 14:22:58  91.108.x.x    POST    /login        CRIT   BRUTE  │    │
│  │ 14:22:45  185.220.x.x   GET     /.env         HIGH   SCAN   │    │
│  │ 14:22:30  23.94.x.x     GET     /wp-admin     MED    PROBE  │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### WAF Engine Features

| Feature | Description |
|:--------|:------------|
| **26 WAF Signatures** | SQL injection, XSS, command injection, path traversal, Log4Shell, SSRF, and more |
| **7 Behavioral Rules** | Rate limiting, brute force detection, scanner detection, honeypot traps |
| **Real-time Detection** | Nginx → Kafka → Realtime Processor pipeline |
| **IP Reputation** | Score-based reputation tracking per IP in PostgreSQL |
| **Multi-phase Correlation** | Recon → Probe → Exploit → Exfil attack chain detection |
| **Auto-blocking** | Instant block on critical signatures (confidence ≥ 0.90) |
| **Honeypot Endpoints** | Fake `/wp-admin`, `/phpmyadmin`, `/.env` that instantly flag attackers |
| **GeoIP Integration** | Attack origin mapping via DB-IP |
| **Threat Intelligence** | AbuseIPDB integration for IP reputation lookups |
| **SSE Live Feed** | Real-time Server-Sent Events attack stream |
| **Attack Heatmap** | Hour-of-day × Day-of-week threat visualization |
| **CSV Export** | Export filtered logs for analysis |

### WAF Deployment (Optional)

The WAF can be deployed on any machine (local, VPS, or GCP VM):

```bash
cd tokio_cloud/gcp-live
cp .env.example .env
# Edit .env — set your domain, backend IP, and passwords
nano .env

docker compose up -d
```

Deploys **7 containers**: PostgreSQL, Zookeeper, Kafka, Nginx WAF proxy, Log processor, Realtime attack detector, SOC Dashboard API.

> **Requirements:** A server with Docker, a domain pointing to it, and a backend to protect. No GCP account required — works on any VPS or local machine.

---

## 🔌 Adding Custom Tools

### Method 1: Built-in Tool

Create a file in `tokio_agent/engine/tools/builtin/`:

```python
# my_tools.py
import logging

logger = logging.getLogger(__name__)

async def my_custom_tool(action: str, params: dict = None) -> str:
    """Your custom tool logic."""
    params = params or {}
    if action == "hello":
        return f"Hello, {params.get('name', 'world')}!"
    return f"Unknown action: {action}"
```

Register in `loader.py`:

```python
from .my_tools import my_custom_tool

registry.register(
    name="my_tool",
    description="My custom tool",
    category="Custom",
    parameters={"action": "Action to perform", "params": "Additional parameters"},
    executor=my_custom_tool,
)
```

### Method 2: Plugin (Hot-reload)

Drop a Python file in `workspace/plugins/` — auto-discovered on startup:

```python
# workspace/plugins/weather.py
TOOL_NAME = "weather"
TOOL_DESCRIPTION = "Get current weather for a city"
TOOL_PARAMETERS = {"city": "City name"}
TOOL_CATEGORY = "Custom"

async def execute(city: str) -> str:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://wttr.in/{city}?format=3")
        return resp.text
```

---

## 📡 API Endpoints

| Method | Path | Description |
|:-------|:-----|:------------|
| `POST` | `/chat` | Send a message and get a response |
| `GET` | `/health` | Health check |
| `GET` | `/tools` | List available tools |
| `GET` | `/sessions` | List sessions |
| `DELETE` | `/sessions/{id}` | Delete a session |

### Example

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "list running docker containers", "session_id": "my-session"}'
```

**Response:**
```json
{
  "response": "Here are the running containers:\n\n| Name | Status | Ports |\n|------|--------|-------|\n| nginx | Up 3 days | 80, 443 |\n| postgres | Up 3 days | 5432 |",
  "tools_used": ["docker"],
  "rounds": 1,
  "tokens_used": 847,
  "session_id": "my-session"
}
```

---

## 📁 Project Structure

```
tokioai/
├── tokio_agent/
│   ├── cli.py                         # Interactive CLI with Rich
│   ├── setup_wizard.py                # Setup wizard (tokio setup)
│   ├── api/
│   │   └── server.py                  # FastAPI REST server
│   ├── bots/
│   │   ├── telegram_bot.py            # Telegram bot (multimedia)
│   │   └── Dockerfile.telegram
│   └── engine/
│       ├── agent.py                   # Agent loop (multi-round)
│       ├── context_builder.py         # Dynamic system prompt builder
│       ├── db.py                      # PostgreSQL helpers
│       ├── error_learner.py           # Error learning
│       ├── watchdog.py                # Container health watchdog
│       ├── llm/                       # LLM providers
│       │   ├── anthropic_llm.py       #   Claude (direct + Vertex AI)
│       │   ├── openai_llm.py          #   GPT-4o, GPT-4
│       │   └── gemini_llm.py          #   Gemini Flash, Pro
│       ├── memory/                    # Persistence layer
│       │   ├── session.py             #   Conversation history
│       │   └── workspace.py           #   Cross-session memory
│       ├── security/                  # Security layers
│       │   ├── prompt_guard.py        #   LLM prompt WAF
│       │   ├── input_sanitizer.py     #   Command sanitization
│       │   └── secure_channel.py      #   API authentication
│       └── tools/
│           ├── registry.py            # Tool registration
│           ├── executor.py            # Async executor + circuit breaker
│           ├── plugins/               # Plugin auto-loader
│           └── builtin/               # 30+ built-in tools
│               ├── loader.py          #   Tool registration
│               ├── system_tools.py    #   bash, python, files
│               ├── docker_tools.py    #   Docker management
│               ├── db_tools.py        #   PostgreSQL queries
│               ├── gcp_tools.py       #   GCP WAF + Compute
│               ├── host_tools.py      #   SSH remote control
│               ├── iot_tools.py       #   Home Assistant
│               └── ...                #   + 10 more tool files
├── tokio_cloud/                       # ⚡ WAF deployment (100% OPTIONAL)
│   ├── gcp-live/                      # Production WAF stack
│   │   ├── docker-compose.yml         #   7-container stack
│   │   ├── dashboard-app.py           #   SOC dashboard (1385 lines)
│   │   ├── realtime-processor.py      #   WAF engine (896 lines)
│   │   ├── nginx.conf                 #   Reverse proxy + rate limiting
│   │   └── deploy.sh                  #   Deployment script
│   └── waf-deployment/                # WAF setup docs + ModSecurity
├── tests/                             # Test suite (10 test files)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## 🧪 Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## 📋 Requirements

| Requirement | Version | Notes |
|:------------|:--------|:------|
| Python | 3.11+ | Required |
| PostgreSQL | 15+ | Session/memory persistence |
| Docker | 20+ | Optional, for containerized deployment |
| LLM API Key | — | At least one: Anthropic, OpenAI, or Gemini |

---

## 📜 License

GPL v3 — See [LICENSE](LICENSE) for details.

---

## 👤 Author

Built by **[MrMoz](https://github.com/TokioAI)** — Security architect, hacker, builder.

TokioAI started as a personal tool to automate SOC operations and infrastructure management. It grew into a full framework because every time something broke at 3 AM, the answer was always the same: "the agent should handle this."

If you find it useful, drop a star. If you break it, open an issue. If you improve it, send a PR.

---

<div align="center">

**TokioAI — Self-hosted AI that executes.**

*Not a chatbot. An agent.*

</div>
