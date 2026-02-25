"""
NginxTenantManager - Gestión dinámica de configuraciones Nginx por tenant
En local: usa Docker SDK para exec en el container de modsecurity
En GCP: usa HTTP a un agente ligero en la VM (tokio-nginx-agent)
"""
import os
import subprocess
import logging
import base64
from typing import Optional
from pathlib import Path

# Structured logging
try:
    import structlog
    logger = structlog.get_logger().bind(service="dashboard-api", component="nginx_manager")
except ImportError:
    logger = logging.getLogger(__name__)

TENANT_TEMPLATE = """
# Tenant: {tenant_name} ({domain})
server {{
    listen 8080;
    server_name {domain} www.{domain};
    modsecurity on;
    modsecurity_rules_file /etc/modsecurity/rules/modsecurity-main.conf;
    
    location / {{
        proxy_pass {backend_url};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Tenant-ID {tenant_id};
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
}}
"""


class NginxTenantManager:
    """
    Gestiona configuraciones de Nginx por tenant.
    En local: usa Docker SDK para exec en el container de modsecurity.
    En GCP: usa HTTP a un agente ligero en la VM (tokio-nginx-agent).
    """
    
    def __init__(self):
        self.deploy_mode = os.getenv("DEPLOY_MODE", "local")
        self.container_name = os.getenv("NGINX_CONTAINER_NAME", "tokio-ai-modsecurity")
        self.nginx_agent_url = os.getenv("NGINX_AGENT_URL", "")
    
    async def add_tenant(
        self, 
        tenant_id: int, 
        domain: str, 
        tenant_name: str, 
        backend_url: str
    ) -> bool:
        """
        Agrega un tenant a la configuración de Nginx
        """
        config = TENANT_TEMPLATE.format(
            tenant_id=tenant_id,
            domain=domain,
            tenant_name=tenant_name,
            backend_url=backend_url
        )
        
        if self.deploy_mode == "gcp":
            return await self._reload_via_agent(domain, config)
        else:
            return await self._reload_via_docker_socket(domain, config)
    
    async def _reload_via_docker_socket(self, domain: str, config: str) -> bool:
        """
        En local: escribir config al volumen compartido y recargar Nginx
        """
        try:
            import docker
            client = docker.from_env()
            container = client.containers.get(self.container_name)
            
            # Escribir config al volumen compartido
            config_path = f"/etc/nginx/conf.d/tenant-{domain}.conf"
            config_b64 = base64.b64encode(config.encode("utf-8")).decode("ascii")
            write_result = container.exec_run(
                f"sh -c 'echo {config_b64} | base64 -d > {config_path}'",
                user="root"
            )
            if write_result.exit_code != 0:
                write_err = write_result.output.decode() if write_result.output else "Unknown error"
                logger.error(f"Error escribiendo config tenant {domain}: {write_err}")
                return False
            # Ensure nginx worker user can read the generated config.
            container.exec_run(f"chown nginx:nginx {config_path}", user="root")
            
            # Test config antes de recargar
            result = container.exec_run("nginx -t", user="nginx")
            if result.exit_code != 0:
                error_output = result.output.decode() if result.output else "Unknown error"
                logger.error(f"Nginx config inválida: {error_output}")
                raise ValueError(f"Nginx config inválida: {error_output}")
            
            # Recargar Nginx sin downtime
            reload_result = container.exec_run("nginx -s reload", user="nginx")
            if reload_result.exit_code != 0:
                logger.error(f"Error recargando Nginx: {reload_result.output.decode()}")
                return False
            
            logger.info(f"✅ Tenant {domain} agregado y Nginx recargado")
            return True
            
        except ImportError:
            logger.error("docker SDK no instalado. Instalar con: pip install docker")
            return False
        except Exception as e:
            logger.error(f"Error en _reload_via_docker_socket: {e}")
            return False
    
    async def _reload_via_agent(self, domain: str, config: str) -> bool:
        """
        En GCP: enviar config al agente HTTP en la VM
        """
        try:
            import aiohttp
            
            if not self.nginx_agent_url:
                logger.error("NGINX_AGENT_URL no configurado para modo GCP")
                return False
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.nginx_agent_url}/api/nginx/tenant",
                    json={
                        "domain": domain,
                        "config": config
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info(f"✅ Tenant {domain} agregado vía agente")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Error del agente Nginx: {error_text}")
                        return False
                        
        except ImportError:
            logger.error("aiohttp no instalado. Instalar con: pip install aiohttp")
            return False
        except Exception as e:
            logger.error(f"Error en _reload_via_agent: {e}")
            return False
    
    async def remove_tenant(self, domain: str) -> bool:
        """
        Elimina un tenant de la configuración de Nginx
        """
        if self.deploy_mode == "gcp":
            return await self._remove_via_agent(domain)
        else:
            return await self._remove_via_docker_socket(domain)
    
    async def _remove_via_docker_socket(self, domain: str) -> bool:
        """
        Elimina el archivo de config y recarga Nginx
        """
        try:
            import docker
            client = docker.from_env()
            container = client.containers.get(self.container_name)
            
            config_path = f"/etc/nginx/conf.d/tenant-{domain}.conf"
            
            # Eliminar archivo
            result = container.exec_run(
                f"rm -f {config_path}",
                user="root"
            )
            
            if result.exit_code != 0:
                logger.warning(f"No se pudo eliminar {config_path} (puede que no exista)")
            
            # Recargar Nginx
            reload_result = container.exec_run("nginx -s reload", user="nginx")
            if reload_result.exit_code != 0:
                logger.error(f"Error recargando Nginx: {reload_result.output.decode()}")
                return False
            
            logger.info(f"✅ Tenant {domain} eliminado y Nginx recargado")
            return True
            
        except Exception as e:
            logger.error(f"Error en _remove_via_docker_socket: {e}")
            return False
    
    async def _remove_via_agent(self, domain: str) -> bool:
        """
        Elimina tenant vía agente HTTP
        """
        try:
            import aiohttp
            
            if not self.nginx_agent_url:
                logger.error("NGINX_AGENT_URL no configurado")
                return False
            
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    f"{self.nginx_agent_url}/api/nginx/tenant/{domain}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        logger.info(f"✅ Tenant {domain} eliminado vía agente")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Error del agente Nginx: {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error en _remove_via_agent: {e}")
            return False
