# 🛡️ TokioAI - Autonomous Security Operations Center

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)

**Complete SOC-level platform that deploys, protects, and operates your entire security infrastructure through an autonomous AI agent.**

TokioAI combines intelligent Web Application Firewall (WAF) capabilities with machine learning threat detection, real-time security dashboards, and natural language AI agent control to provide autonomous security operations.

## 🚀 Features

### 🛡️ Intelligent WAF (Web Application Firewall)
- **Nginx-based reverse proxy** with 15+ WAF signatures
- **Real-time detection** of: SQL Injection, XSS (reflected/stored), path traversal, command injection, SSRF, Log4Shell, scanners (Nikto, sqlmap, Nmap), WordPress exploits, exposed configs (.env, .git)
- **Inspects every HTTP request** in real-time

### 🧠 ML Threat Classification (OWASP Top 10)
- **Real-time processor** with machine learning
- **Severity classification**: critical, high, medium, low, normal
- **OWASP Top 10 2021 mapping**: A01 (Broken Access Control), A03 (Injection), A05 (Security Misconfiguration), A06 (Vulnerable Components), A07 (Auth Failures), A10 (SSRF)
- **Minimizes false positives** with intelligent path exclusions

### 🔒 3-Tier Auto-Blocking Engine
- **Immediate blocking** on critical WAF signature matches (SQLi, RCE)
- **Episode-based blocking** when sustained attack patterns are detected
- **Rate-limit blocking** when volume thresholds are exceeded
- **Zero-downtime** Nginx blocklist reloads

### 📊 Episode Detection & Attack Correlation
- Groups related attack events from the same IP in configurable time windows
- Correlates multi-vector attacks (scanning → injection → config probing → exfiltration)
- Automatic severity escalation based on event count and types

### 🤖 Autonomous AI Agent (Natural Language)
- **Natural language commands** in any language
- **Context understanding**, multi-step operations, intelligent error handling
- **Explicit confirmation** for dangerous actions
- **Supports**: OpenAI GPT-4, Anthropic Claude, Google Gemini with automatic fallback

### 📈 Real-Time Security Dashboard
- Dark theme, JWT login, live traffic graphs (Chart.js)
- Severity distribution, recent traffic table with advanced filters
- IP block management (block/unblock from UI)
- Episode viewer with risk scores
- Filters by IP, URL pattern, and date/time range

### 🔌 Complete Integrations
- **Telegram Bot**: Full control from Telegram, real-time alerts, security ACL
- **Home Assistant + Alexa**: Voice control of SOC operations via Alexa Media Player
- **SSH Host Control**: Complete remote administration via SSH
- **Router Control**: OpenWrt/GL.iNet router management (firewall, DNS, DHCP, VPN)
- **DNS Management**: Automated DNS management via Hostinger API

### ☁️ One-Command GCP Deployment
- Full WAF + ML + Dashboard deployment on **Google Cloud Platform**
- Automatically creates: VPC network + subnet, firewall rules, static IP, Compute Engine VM, Docker containers, SSL certificates, DNS configuration

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Deployment](#-deployment)
- [Architecture](#-architecture)
- [API Documentation](#-api-documentation)
- [Security](#-security)
- [Contributing](#-contributing)
- [License](#-license)

## ⚡ Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for MCP Host)
- **PostgreSQL 14+**
- **Apache Kafka** (or use Docker Compose)
- **Docker & Docker Compose** (recommended)
- **Google Cloud SDK** (for GCP deployment)

### Local Development Setup

1. **Clone the repository:**
```bash
git clone https://github.com/yourusername/TokioAI.git
cd TokioAI
```

2. **Copy environment variables:**
```bash
cp .env.example .env
# Edit .env with your actual values
nano .env
```

3. **Install Python dependencies:**
```bash
cd tokio-ai/dashboard-api
pip install -r requirements.txt
```

4. **Install Node.js dependencies:**
```bash
cd mcp-host
npm install
npm run build
```

5. **Start services with Docker Compose:**
```bash
cd ../../..
docker-compose up -d
```

6. **Run database migrations:**
```bash
cd tokio-ai/dashboard-api
python3 -m alembic upgrade head
```

7. **Start the dashboard API:**
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

8. **Access the dashboard:**
```
http://localhost:8000
```

## 🔧 Configuration

### Environment Variables

All configuration is done through environment variables. See [.env.example](.env.example) for a complete list.

#### Required Variables

```bash
# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=soc_ai
POSTGRES_USER=soc_user
POSTGRES_PASSWORD=YOUR_SECURE_PASSWORD

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC_WAF_LOGS=waf-logs

# LLM (at least one required)
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
# OR
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
# OR
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY

# Dashboard Authentication
DASHBOARD_USERNAME=your-email@example.com
DASHBOARD_PASSWORD_HASH=YOUR_BCRYPT_HASH
```

#### Generate Password Hash

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw('YOUR_PASSWORD'.encode(), bcrypt.gensalt()).decode())"
```

### Feature Flags

Enable/disable features via environment variables:

```bash
TOKIO_ENABLE_SPOTIFY=true
TOKIO_ENABLE_ATLASSIAN=false
TOKIO_ENABLE_SOAR=false
TOKIO_TOOLS_MODE=http
```

## 🚀 Deployment

### Local Deployment

See [Quick Start](#-quick-start) section above.

### GCP Cloud Deployment

#### Prerequisites

1. **Google Cloud Project** with billing enabled
2. **gcloud CLI** installed and authenticated
3. **Service Account** with required permissions

#### One-Command Deployment

```bash
./scripts/deploy-gcp.sh
```

This script will:
- Create VPC network and subnet
- Set up firewall rules
- Create Compute Engine VM
- Deploy Docker containers (Nginx, Kafka, PostgreSQL, ML Processor, Dashboard)
- Configure SSL certificates
- Set up DNS

#### Manual GCP Deployment

See [docs/DEPLOYMENT_GCP.md](docs/DEPLOYMENT_GCP.md) for detailed instructions.

### Docker Compose Deployment

```bash
docker-compose up -d
```

See [docker-compose.yml](docker-compose.yml) for service configuration.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     TokioAI Architecture                     │
└─────────────────────────────────────────────────────────────┘

┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Nginx WAF  │─────▶│  Kafka Queue │─────▶│ ML Processor │
│  (Reverse    │      │              │      │              │
│   Proxy)     │      │              │      │              │
└──────────────┘      └──────────────┘      └──────────────┘
       │                      │                      │
       │                      │                      │
       ▼                      ▼                      ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Dashboard  │      │  PostgreSQL  │      │  AI Agent    │
│     API      │◀─────│   Database   │      │   (MCP)      │
│  (FastAPI)   │      │              │      │              │
└──────────────┘      └──────────────┘      └──────────────┘
       │
       │
       ▼
┌──────────────┐
│   Frontend   │
│  Dashboard   │
└──────────────┘
```

### Components

- **Nginx WAF**: Reverse proxy with ModSecurity rules
- **Kafka**: Event streaming for WAF logs
- **ML Processor**: Real-time threat classification
- **PostgreSQL**: Persistent storage for logs, episodes, blocks
- **Dashboard API**: FastAPI backend for web interface
- **AI Agent (MCP)**: Natural language command processing
- **Frontend**: Real-time security dashboard

## 📚 API Documentation

### Dashboard API

Once running, access API documentation at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Key Endpoints

- `GET /api/traffic` - Get recent traffic logs
- `POST /api/blocks` - Block an IP address
- `DELETE /api/blocks/{ip}` - Unblock an IP address
- `GET /api/episodes` - Get attack episodes
- `POST /api/cli` - Execute AI agent command

### Authentication

The dashboard uses JWT-based authentication. Include the session cookie in requests or use the `AUTOMATION_API_TOKEN` header for API access.

## 🔒 Security

### Best Practices

1. **Never commit `.env` files** to version control
2. **Use strong passwords** for PostgreSQL and dashboard
3. **Enable HTTPS** in production (Let's Encrypt included)
4. **Restrict firewall rules** to necessary IPs only
5. **Use Cloud SQL Private IP** instead of public IP when possible
6. **Rotate API keys** regularly
7. **Enable 2FA** for GCP accounts

### Security Features

- **JWT authentication** for dashboard access
- **ACL-based access control** for automation
- **Input validation** and sanitization
- **SQL injection protection** via parameterized queries
- **XSS protection** via content security policies
- **Rate limiting** on API endpoints

## 🧪 Testing

```bash
# Run unit tests
pytest tests/

# Run integration tests
pytest tests/integration/

# Run smoke tests
./scripts/smoke_test.py
```

## 📖 Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [GCP Deployment](docs/DEPLOYMENT_GCP.md)
- [Configuration Guide](docs/CONFIGURATION.md)
- [API Reference](docs/API.md)
- [Security Guide](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- WAF powered by [ModSecurity](https://modsecurity.org/)
- ML models using [scikit-learn](https://scikit-learn.org/)
- AI agents via [Model Context Protocol](https://modelcontextprotocol.io/)

## 📧 Contact

- **Website**: [tokioia.com](https://tokioia.com)
- **GitHub**: [@yourusername](https://github.com/yourusername)
- **Issues**: [GitHub Issues](https://github.com/yourusername/TokioAI/issues)

---

**Built with ❤️ for autonomous security operations**
