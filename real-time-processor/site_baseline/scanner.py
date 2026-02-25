"""
Módulo para escanear el sitio y crear un baseline de URLs válidas
"""
import os
import logging
import requests
import time
from typing import Set, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("BeautifulSoup4 no disponible, escaneo limitado")

class SiteBaselineScanner:
    """Escanea el sitio para crear un baseline de URLs válidas"""
    
    def __init__(self, base_url: str, max_depth: int = 2, max_urls: int = 500):
        """
        Args:
            base_url: URL base del sitio a escanear (ej: http://modsecurity-nginx:8080)
            max_depth: Profundidad máxima de navegación (por defecto 2)
            max_urls: Número máximo de URLs a escanear
        """
        self.base_url = base_url.rstrip('/')
        self.max_depth = max_depth
        self.max_urls = max_urls
        self.session = requests.Session()
        self.session.timeout = 5
        self.session.headers.update({
            'User-Agent': 'SOC-AI-Baseline-Scanner/1.0'
        })
        self.visited_urls: Set[str] = set()
        self.valid_urls: Dict[str, Dict] = {}  # url -> {status, method, last_seen}
        
    def scan(self) -> Dict[str, any]:
        """
        Escanea el sitio y retorna un diccionario con URLs válidas
        
        Returns:
            Dict con estructura:
            {
                'base_url': str,
                'valid_urls': List[Dict],
                'scan_timestamp': str,
                'total_urls': int
            }
        """
        logger.info(f"🔍 Iniciando escaneo de baseline para {self.base_url}")
        
        try:
            # 1. Escanear robots.txt y sitemap
            self._scan_robots_and_sitemap()
            
            # 2. Navegar desde la página principal
            if BS4_AVAILABLE:
                self._crawl_from_root()
            
            # 3. Buscar enlaces comunes (páginas típicas)
            self._scan_common_paths()
            
            # Compilar resultados
            result = {
                'base_url': self.base_url,
                'valid_urls': [
                    {
                        'url': url,
                        'path': urlparse(url).path,
                        'status': info['status'],
                        'method': info.get('method', 'GET'),
                        'last_seen': info.get('last_seen', datetime.now().isoformat())
                    }
                    for url, info in self.valid_urls.items()
                ],
                'scan_timestamp': datetime.now().isoformat(),
                'total_urls': len(self.valid_urls)
            }
            
            logger.info(f"✅ Escaneo completado: {len(self.valid_urls)} URLs válidas encontradas")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error en escaneo de baseline: {e}", exc_info=True)
            return {
                'base_url': self.base_url,
                'valid_urls': [],
                'scan_timestamp': datetime.now().isoformat(),
                'total_urls': 0,
                'error': str(e)
            }
    
    def _scan_robots_and_sitemap(self):
        """Escanea robots.txt y sitemap.xml si existen"""
        try:
            # Robots.txt
            robots_url = urljoin(self.base_url, '/robots.txt')
            response = self.session.get(robots_url, timeout=5)
            if response.status_code == 200:
                self.valid_urls[robots_url] = {
                    'status': 200,
                    'method': 'GET',
                    'last_seen': datetime.now().isoformat()
                }
                # Parsear robots.txt para encontrar sitemap
                for line in response.text.split('\n'):
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        self._fetch_url(sitemap_url)
            
            # Sitemap.xml
            sitemap_url = urljoin(self.base_url, '/sitemap.xml')
            self._fetch_sitemap(sitemap_url)
            
        except Exception as e:
            logger.debug(f"No se pudo escanear robots.txt/sitemap: {e}")
    
    def _fetch_sitemap(self, sitemap_url: str):
        """Descarga y parsea sitemap.xml"""
        if not BS4_AVAILABLE:
            return
            
        try:
            response = self.session.get(sitemap_url, timeout=10)
            if response.status_code == 200:
                self.valid_urls[sitemap_url] = {
                    'status': 200,
                    'method': 'GET',
                    'last_seen': datetime.now().isoformat()
                }
                # Parsear XML del sitemap (simplificado)
                if 'xml' in response.headers.get('content-type', ''):
                    # Extraer URLs del sitemap
                    soup = BeautifulSoup(response.content, 'xml')
                    for loc in soup.find_all('loc'):
                        url = loc.text.strip()
                        if url.startswith(self.base_url):
                            self._fetch_url(url, method='HEAD')  # Solo HEAD para sitemap
        except Exception as e:
            logger.debug(f"No se pudo parsear sitemap: {e}")
    
    def _crawl_from_root(self, current_url: str = None, depth: int = 0):
        """Navega recursivamente desde la raíz"""
        if depth > self.max_depth or len(self.valid_urls) >= self.max_urls:
            return
        
        start_url = current_url or self.base_url
        
        if start_url in self.visited_urls:
            return
        
        self.visited_urls.add(start_url)
        
        try:
            response = self._fetch_url(start_url)
            if response and response.status_code == 200:
                # Extraer enlaces de la página
                soup = BeautifulSoup(response.text, 'html.parser')
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    absolute_url = urljoin(start_url, href)
                    
                    # Solo seguir URLs del mismo dominio
                    parsed = urlparse(absolute_url)
                    base_parsed = urlparse(self.base_url)
                    if parsed.netloc == base_parsed.netloc or not parsed.netloc:
                        if absolute_url not in self.visited_urls and len(self.valid_urls) < self.max_urls:
                            self._crawl_from_root(absolute_url, depth + 1)
                            
        except Exception as e:
            logger.debug(f"Error navegando desde {start_url}: {e}")
    
    def _scan_common_paths(self):
        """Escanea rutas comunes (páginas típicas de sitios web)"""
        common_paths = [
            '/', '/index.html', '/index.php', '/home', '/about', '/contact',
            '/login', '/signin', '/register', '/signup',
            '/api', '/api/health', '/api/docs', '/api/v1',
            '/docs', '/documentation', '/help', '/faq',
            '/blog', '/news', '/products', '/services',
            '/assets/', '/static/', '/css/', '/js/', '/img/', '/images/',
            # CRÍTICO: Paths comunes que SIEMPRE deben estar permitidos
            '/favicon.ico', '/robots.txt', '/sitemap.xml',
            '/logo-tokio-removebg-preview.png',  # Logo de Tokio AI
            '/health', '/status', '/ping', '/ready', '/live'
        ]
        
        for path in common_paths:
            if len(self.valid_urls) >= self.max_urls:
                break
            
            url = urljoin(self.base_url, path)
            if url not in self.visited_urls:
                response = self._fetch_url(url, method='HEAD')  # Usar HEAD para ser más rápido
                
                # CRÍTICO: Si retorna 403 pero es un path común del sitio, agregarlo igual al baseline
                # porque ModSecurity puede estar bloqueando temporalmente
                if response and response.status_code == 403 and path in [
                    '/favicon.ico', 
                    '/logo-tokio-removebg-preview.png', 
                    '/robots.txt',
                    '/sitemap.xml',
                    '/health',
                    '/status'
                ]:
                    # Marcar como válido aunque ModSecurity retorne 403 (es un path legítimo)
                    self.valid_urls[url] = {
                        'status': 200,  # Marcar como válido
                        'method': 'HEAD',
                        'last_seen': datetime.now().isoformat(),
                        'note': 'Path común, agregado manualmente aunque ModSecurity bloquee'
                    }
                    logger.debug(f"✅ Path común '{path}' agregado al baseline aunque retornó 403")
                
                time.sleep(0.1)  # Pequeña pausa para no sobrecargar
    
    def _fetch_url(self, url: str, method: str = 'GET') -> Optional[requests.Response]:
        """Hace una petición HTTP y guarda el resultado si es válido"""
        try:
            if method.upper() == 'HEAD':
                response = self.session.head(url, timeout=5, allow_redirects=True)
            else:
                response = self.session.get(url, timeout=5, allow_redirects=True)
            
            # Considerar válidas: 200, 301, 302, 401, 403 (pero no 404)
            # CRÍTICO: Incluso si ModSecurity retorna 403, guardar como válido si es path común
            parsed_path = urlparse(url).path
            is_common_path = parsed_path in [
                '/favicon.ico', 
                '/logo-tokio-removebg-preview.png', 
                '/robots.txt',
                '/sitemap.xml',
                '/health',
                '/status'
            ]
            
            if response.status_code in [200, 301, 302, 401] or (response.status_code == 403 and is_common_path):
                self.valid_urls[url] = {
                    'status': 200 if (response.status_code == 403 and is_common_path) else response.status_code,
                    'method': method,
                    'last_seen': datetime.now().isoformat(),
                    'original_status': response.status_code if (response.status_code == 403 and is_common_path) else None
                }
            
            return response
            
        except Exception as e:
            logger.debug(f"Error fetching {url}: {e}")
            return None








