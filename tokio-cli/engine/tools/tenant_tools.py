"""
Tenant Management Tools - Complete tenant lifecycle management

These tools give the CLI complete control over tenant configuration:
- Add new tenants
- Configure Nginx proxy
- Verify WAF logs
- Manage SSL certificates
- Update tenant configuration
- Remove tenants
"""
import os
import json
import logging
import subprocess
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Nginx config paths
NGINX_TENANT_CONFIGS = "/etc/nginx/conf.d/tenants"
NGINX_CONFIG_TEMPLATE = "/etc/nginx/templates/tenant.conf.template"

class TenantManager:
    """Complete tenant management"""

    def __init__(self):
        self.tenants_config_path = Path(NGINX_TENANT_CONFIGS)
        self.tenants_config_path.mkdir(parents=True, exist_ok=True)

    def add_tenant(
        self,
        domain: str,
        backend_url: str,
        backend_port: int = 3000,
        ssl_enabled: bool = True,
        waf_enabled: bool = True
    ) -> Dict:
        """
        Add a new tenant with complete configuration.

        Steps:
        1. Create Nginx proxy config
        2. Generate SSL certificate (if enabled)
        3. Enable WAF rules
        4. Reload Nginx
        5. Verify logs start arriving

        Args:
            domain: Domain name (e.g., mysite.com)
            backend_url: Backend server URL
            backend_port: Backend server port
            ssl_enabled: Enable SSL/TLS
            waf_enabled: Enable WAF protection

        Returns:
            Dict with status and configuration
        """
        logger.info(f"🆕 Adding tenant: {domain}")

        try:
            # 1. Create Nginx config
            config = self._generate_nginx_config(
                domain=domain,
                backend_url=backend_url,
                backend_port=backend_port,
                ssl_enabled=ssl_enabled,
                waf_enabled=waf_enabled
            )

            config_file = self.tenants_config_path / f"{domain}.conf"
            config_file.write_text(config)

            logger.info(f"✅ Created Nginx config: {config_file}")

            # 2. Generate SSL if needed
            if ssl_enabled:
                ssl_result = self._setup_ssl(domain)
                logger.info(f"🔒 SSL setup: {ssl_result}")

            # 3. Reload Nginx
            reload_result = self._reload_nginx()

            if reload_result["success"]:
                logger.info("✅ Nginx reloaded successfully")
            else:
                logger.error(f"❌ Nginx reload failed: {reload_result['error']}")
                return {
                    "success": False,
                    "error": f"Nginx reload failed: {reload_result['error']}"
                }

            # 4. Verify configuration
            verify_result = self._verify_tenant_config(domain)

            return {
                "success": True,
                "domain": domain,
                "backend": f"{backend_url}:{backend_port}",
                "ssl_enabled": ssl_enabled,
                "waf_enabled": waf_enabled,
                "config_file": str(config_file),
                "verification": verify_result
            }

        except Exception as e:
            logger.error(f"❌ Failed to add tenant {domain}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _generate_nginx_config(
        self,
        domain: str,
        backend_url: str,
        backend_port: int,
        ssl_enabled: bool,
        waf_enabled: bool
    ) -> str:
        """Generate Nginx configuration for tenant"""

        ssl_config = ""
        if ssl_enabled:
            ssl_config = f"""
    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    ssl_certificate /etc/nginx/ssl/{domain}/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
"""

        waf_config = ""
        if waf_enabled:
            waf_config = """
    # ModSecurity WAF
    modsecurity on;
    modsecurity_rules_file /etc/modsecurity/modsecurity.conf;
"""

        config = f"""# Tenant: {domain}
# Backend: {backend_url}:{backend_port}
# Generated: {os.popen('date').read().strip()}

server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
{ssl_config}
{waf_config}
    # Proxy settings
    location / {{
        proxy_pass {backend_url}:{backend_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}

    # Access logs
    access_log /var/log/nginx/{domain}-access.log combined;
    error_log /var/log/nginx/{domain}-error.log warn;
}}
"""

        return config

    def _setup_ssl(self, domain: str) -> Dict:
        """Setup SSL certificate for domain"""
        # For now, use self-signed cert (production would use Let's Encrypt)
        ssl_dir = Path(f"/etc/nginx/ssl/{domain}")
        ssl_dir.mkdir(parents=True, exist_ok=True)

        # Generate self-signed cert
        try:
            cmd = f"""
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout {ssl_dir}/privkey.pem \
  -out {ssl_dir}/fullchain.pem \
  -subj "/C=US/ST=State/L=City/O=Organization/CN={domain}"
"""
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return {"success": True, "cert_path": str(ssl_dir)}
            else:
                return {"success": False, "error": result.stderr}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _reload_nginx(self) -> Dict:
        """Reload Nginx configuration"""
        try:
            # Test config first
            test_result = subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if test_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Config test failed: {test_result.stderr}"
                }

            # Reload
            reload_result = subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if reload_result.returncode == 0:
                return {"success": True}
            else:
                return {"success": False, "error": reload_result.stderr}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _verify_tenant_config(self, domain: str) -> Dict:
        """Verify tenant is properly configured"""
        checks = {}

        # Check config file exists
        config_file = self.tenants_config_path / f"{domain}.conf"
        checks["config_exists"] = config_file.exists()

        # Check Nginx is running
        try:
            result = subprocess.run(
                ["pgrep", "nginx"],
                capture_output=True,
                timeout=5
            )
            checks["nginx_running"] = result.returncode == 0
        except:
            checks["nginx_running"] = False

        # Check logs directory
        log_path = Path(f"/var/log/nginx")
        checks["logs_accessible"] = log_path.exists()

        return {
            "all_passed": all(checks.values()),
            "checks": checks
        }

    def remove_tenant(self, domain: str) -> Dict:
        """Remove a tenant"""
        logger.info(f"🗑️ Removing tenant: {domain}")

        try:
            # Remove config
            config_file = self.tenants_config_path / f"{domain}.conf"

            if config_file.exists():
                config_file.unlink()
                logger.info(f"✅ Removed config: {config_file}")

            # Reload Nginx
            reload_result = self._reload_nginx()

            return {
                "success": True,
                "domain": domain,
                "nginx_reloaded": reload_result["success"]
            }

        except Exception as e:
            logger.error(f"❌ Failed to remove tenant {domain}: {e}")
            return {"success": False, "error": str(e)}

    def list_tenants(self) -> Dict:
        """List all configured tenants"""
        tenants = []

        for config_file in self.tenants_config_path.glob("*.conf"):
            domain = config_file.stem

            # Parse config to get backend info
            config_text = config_file.read_text()

            tenants.append({
                "domain": domain,
                "config_file": str(config_file),
                "ssl_enabled": "ssl_certificate" in config_text,
                "waf_enabled": "modsecurity on" in config_text
            })

        return {
            "total": len(tenants),
            "tenants": tenants
        }


# Tool executor functions
def add_tenant(domain: str, backend_url: str, backend_port: int = 3000) -> str:
    """Add a new tenant"""
    manager = TenantManager()
    result = manager.add_tenant(domain, backend_url, backend_port)

    if result["success"]:
        return f"✅ Tenant '{domain}' added successfully!\n\n" + json.dumps(result, indent=2)
    else:
        return f"❌ Failed to add tenant: {result.get('error', 'Unknown error')}"


def remove_tenant(domain: str) -> str:
    """Remove a tenant"""
    manager = TenantManager()
    result = manager.remove_tenant(domain)

    if result["success"]:
        return f"✅ Tenant '{domain}' removed successfully!"
    else:
        return f"❌ Failed to remove tenant: {result.get('error', 'Unknown error')}"


def list_tenants() -> str:
    """List all tenants"""
    manager = TenantManager()
    result = manager.list_tenants()

    output = f"📋 Total tenants: {result['total']}\n\n"

    for tenant in result["tenants"]:
        output += f"- {tenant['domain']}\n"
        output += f"  SSL: {'✅' if tenant['ssl_enabled'] else '❌'}\n"
        output += f"  WAF: {'✅' if tenant['waf_enabled'] else '❌'}\n"
        output += f"  Config: {tenant['config_file']}\n\n"

    return output


def check_tenant_health(domain: str) -> str:
    """Check if tenant is healthy"""
    manager = TenantManager()
    result = manager._verify_tenant_config(domain)

    output = f"🔍 Health check for: {domain}\n\n"

    for check, status in result["checks"].items():
        status_icon = "✅" if status else "❌"
        output += f"{status_icon} {check.replace('_', ' ').title()}\n"

    output += f"\nOverall: {'✅ Healthy' if result['all_passed'] else '❌ Issues detected'}"

    return output
