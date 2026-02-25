# 🔒 Security Guide

This document outlines security best practices for deploying and operating TokioAI.

## Table of Contents

- [Authentication](#authentication)
- [Network Security](#network-security)
- [Secrets Management](#secrets-management)
- [Data Protection](#data-protection)
- [Security Updates](#security-updates)

## Authentication

### Dashboard Authentication

The dashboard uses JWT-based authentication with bcrypt password hashing.

**Best Practices:**

1. **Use Strong Passwords**
   ```bash
   # Generate password hash
   python3 -c "import bcrypt; print(bcrypt.hashpw('YOUR_STRONG_PASSWORD'.encode(), bcrypt.gensalt()).decode())"
   ```

2. **Enable Session Security**
   ```bash
   DASHBOARD_SESSION_SECRET=YOUR_RANDOM_SECRET_HERE
   DASHBOARD_SESSION_TTL_SECONDS=3600
   ```

3. **Use HTTPS in Production**
   - Never transmit credentials over HTTP
   - Configure SSL certificates (Let's Encrypt recommended)

### API Authentication

For automated access, use `AUTOMATION_API_TOKEN`:

```bash
curl -H "X-Automation-Token: YOUR_TOKEN" \
     http://localhost:8000/api/traffic
```

**Security Recommendations:**

- Use long, random tokens (32+ characters)
- Rotate tokens regularly
- Store tokens securely (use Secret Manager in production)
- Never commit tokens to version control

## Network Security

### Firewall Rules

**GCP Firewall Best Practices:**

1. **Deny All by Default**
   ```bash
   gcloud compute firewall-rules create default-deny-all \
       --action=DENY \
       --rules=all \
       --source-ranges=0.0.0.0/0
   ```

2. **Allow Only Necessary Traffic**
   ```bash
   # HTTP/HTTPS from internet
   gcloud compute firewall-rules create allow-http-https \
       --allow tcp:80,tcp:443 \
       --source-ranges 0.0.0.0/0
   
   # SSH only from your IP
   gcloud compute firewall-rules create allow-ssh \
       --allow tcp:22 \
       --source-ranges YOUR_IP/32
   ```

3. **Use Private IPs**
   - Cloud SQL: Use Private IP, not Public IP
   - Internal services: Use VPC internal IPs
   - Only expose necessary services publicly

### VPN / IAP Access

For secure access to internal services:

1. **Identity-Aware Proxy (IAP)**
   ```bash
   gcloud compute instances add-iam-binding INSTANCE_NAME \
       --zone=ZONE \
       --member=user:YOUR_EMAIL \
       --role=roles/iap.httpsResourceAccessor
   ```

2. **VPN Access**
   - Set up Cloud VPN for secure access
   - Use client certificates for authentication

## Secrets Management

### Environment Variables

**Never commit secrets to version control:**

```bash
# ✅ Good: Use .env.example
POSTGRES_PASSWORD=YOUR_PASSWORD_HERE

# ❌ Bad: Hardcoded in code
POSTGRES_PASSWORD=soc_password_2026
```

### GCP Secret Manager

For production deployments, use GCP Secret Manager:

```python
from google.cloud import secretmanager

def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
```

**Create Secrets:**

```bash
# Create secret
echo -n "YOUR_PASSWORD" | gcloud secrets create postgres-password --data-file=-

# Grant access
gcloud secrets add-iam-policy-binding postgres-password \
    --member=serviceAccount:SERVICE_ACCOUNT \
    --role=roles/secretmanager.secretAccessor
```

## Data Protection

### Database Security

1. **Encryption at Rest**
   - Cloud SQL: Enable encryption by default
   - Local PostgreSQL: Use encrypted filesystem

2. **Encryption in Transit**
   - Use SSL/TLS for database connections
   - Configure `sslmode=require` in connection strings

3. **Access Control**
   - Use least privilege principle
   - Separate users for different services
   - Regular audit of database access

### Log Data Protection

1. **Sanitize Logs**
   - Remove sensitive data before logging
   - Hash IP addresses if required by privacy laws
   - Implement log retention policies

2. **Secure Log Storage**
   - Encrypt log files at rest
   - Restrict access to log files
   - Use secure log aggregation services

## Security Updates

### Regular Updates

1. **Dependencies**
   ```bash
   # Update Python packages
   pip list --outdated
   pip install --upgrade package-name
   
   # Update Node.js packages
   npm outdated
   npm update
   ```

2. **System Packages**
   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt upgrade
   
   # Container images
   docker pull python:3.11-slim
   ```

3. **Security Advisories**
   - Subscribe to security mailing lists
   - Monitor CVE databases
   - Apply patches promptly

### Vulnerability Scanning

1. **Container Scanning**
   ```bash
   gcloud container images scan IMAGE_URL
   ```

2. **Dependency Scanning**
   ```bash
   # Python
   pip-audit
   
   # Node.js
   npm audit
   ```

3. **Code Scanning**
   - Use static analysis tools
   - Run security linters
   - Perform regular penetration testing

## Incident Response

### Security Incident Plan

1. **Detection**
   - Monitor logs for suspicious activity
   - Set up alerts for anomalies
   - Regular security audits

2. **Response**
   - Isolate affected systems
   - Preserve evidence
   - Notify stakeholders

3. **Recovery**
   - Restore from backups
   - Patch vulnerabilities
   - Update security measures

### Reporting

- Report security issues to: security@tokioia.com
- Use responsible disclosure
- Include steps to reproduce
- Provide fix suggestions if possible

## Compliance

### GDPR

- Implement data retention policies
- Provide data export capabilities
- Allow data deletion requests
- Document data processing activities

### SOC 2

- Implement access controls
- Regular security audits
- Document security procedures
- Monitor and log all access

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks/)
- [GCP Security Best Practices](https://cloud.google.com/security/best-practices)
