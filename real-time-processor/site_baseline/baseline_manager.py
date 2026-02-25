"""
Gestor del baseline - escanea periódicamente y actualiza
"""
import os
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from .scanner import SiteBaselineScanner
from .persistence import save_baseline_scan, create_baseline_table_if_not_exists

logger = logging.getLogger(__name__)

class BaselineManager:
    """Gestiona el escaneo y actualización del baseline"""
    
    def __init__(self, base_url: str, tenant_id: Optional[int] = None, 
                 scan_interval_hours: int = 24):
        """
        Args:
            base_url: URL base del sitio
            tenant_id: ID del tenant (opcional)
            scan_interval_hours: Intervalo entre escaneos (por defecto 24h)
        """
        self.base_url = base_url
        self.tenant_id = tenant_id
        self.scan_interval_hours = scan_interval_hours
        self.last_scan: Optional[datetime] = None
        self.running = False
        self.scan_thread: Optional[threading.Thread] = None
        
    def start_periodic_scanning(self):
        """Inicia el escaneo periódico en un thread separado"""
        if self.running:
            return
        
        self.running = True
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.scan_thread.start()
        logger.info(f"✅ BaselineManager iniciado para {self.base_url}")
    
    def stop(self):
        """Detiene el escaneo periódico"""
        self.running = False
        if self.scan_thread:
            self.scan_thread.join(timeout=5)
    
    def _scan_loop(self):
        """Loop principal de escaneo periódico"""
        # Escanear inmediatamente al inicio (con delay pequeño para no bloquear inicio)
        time.sleep(30)  # Esperar 30 segundos antes del primer escaneo
        if self.running:
            self.scan_now()
        
        # Luego escanear periódicamente
        while self.running:
            time.sleep(self.scan_interval_hours * 3600)  # Convertir horas a segundos
            if self.running:
                self.scan_now()
    
    def scan_now(self) -> dict:
        """Ejecuta un escaneo inmediato"""
        logger.info(f"🔍 Iniciando escaneo de baseline para {self.base_url}")
        
        try:
            create_baseline_table_if_not_exists()
            
            scanner = SiteBaselineScanner(
                base_url=self.base_url,
                max_depth=2,
                max_urls=500
            )
            
            result = scanner.scan()
            
            if result.get('total_urls', 0) > 0:
                save_baseline_scan(result, tenant_id=self.tenant_id)
                self.last_scan = datetime.now()
                logger.info(f"✅ Baseline escaneado: {result['total_urls']} URLs válidas")
            else:
                logger.warning(f"⚠️ Escaneo completado pero no se encontraron URLs válidas")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error en escaneo de baseline: {e}", exc_info=True)
            return {'error': str(e)}








