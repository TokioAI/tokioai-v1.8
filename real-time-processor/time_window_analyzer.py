"""
Time Window Batch Analyzer - Analiza tráfico en ventanas temporales
Como un analista SOC experto mirando el tráfico completo
"""
import logging
import time
import threading
from typing import Dict, Any, List, Optional
from collections import defaultdict, Counter
from datetime import datetime

logger = logging.getLogger(__name__)


class TimeWindowBatchAnalyzer:
    """
    Analiza tráfico en ventanas temporales para detectar patrones globales,
    ataques distribuidos, escaneos coordinados, etc.
    Como un analista SOC experto mirando el tráfico completo.
    """
    
    def __init__(self, window_size_logs: int = 100, window_size_seconds: int = 60):
        """
        Inicializa el analizador de ventanas temporales.
        
        Args:
            window_size_logs: Analizar cada N logs (default: 100)
            window_size_seconds: Analizar cada N segundos (default: 60)
        """
        self.window_size_logs = window_size_logs
        self.window_size_seconds = window_size_seconds
        self.current_window = []
        self.window_start_time = time.time()
        self.window_lock = threading.Lock()
        self.last_analysis_time = time.time()
        
    def add_log(self, log: Dict[str, Any], classification_result: Dict[str, Any]) -> bool:
        """
        Agrega un log a la ventana actual.
        
        Args:
            log: Log normalizado
            classification_result: Resultado de clasificación (threat_type, severity, etc.)
            
        Returns:
            True si se debe analizar la ventana, False si no
        """
        with self.window_lock:
            # Solo agregar logs sospechosos o con amenazas detectadas
            threat_type = classification_result.get('threat_type')
            severity = classification_result.get('severity', 'low')
            is_waf_blocked = log.get('status') == 403
            
            # MEJORADO: Incluir logs sospechosos (incluso si no están bloqueados por WAF)
            # También incluir logs con SCAN_PROBE aunque threat_type sea None en algunos casos
            uri = log.get('uri', '')
            is_scan_pattern = any(pattern in uri.lower() for pattern in [
                'wp-admin', 'wp-content', 'wp-includes', '.well-known',
                '/admin', '/actuator', '/.env', '/config', '/backup'
            ])
            
            should_include = (
                threat_type or  # Tiene threat_type detectado
                severity in ['high', 'medium'] or  # Alta o media severidad
                is_waf_blocked or  # Bloqueado por WAF
                (is_scan_pattern and log.get('status') in [404, 301])  # Patrón de escaneo con 404/301
            )
            
            if should_include:
                self.current_window.append({
                    'log': log,
                    'classification': classification_result,
                    'timestamp': time.time()
                })
            
            # Verificar si debemos analizar la ventana
            should_analyze = False
            
            # Criterio 1: Ventana llena (número de logs)
            if len(self.current_window) >= self.window_size_logs:
                should_analyze = True
                logger.info(f"📊 Ventana temporal lista para análisis: {len(self.current_window)} logs acumulados")
            
            # Criterio 2: Tiempo transcurrido
            elif time.time() - self.window_start_time >= self.window_size_seconds:
                if len(self.current_window) > 0:  # Solo si hay logs
                    should_analyze = True
                    logger.info(f"📊 Ventana temporal lista para análisis: {time.time() - self.window_start_time:.0f}s transcurridos, {len(self.current_window)} logs")
            
            return should_analyze
    
    def get_window_for_analysis(self) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene la ventana actual para análisis y la limpia.
        
        Returns:
            Lista de logs con clasificaciones o None si está vacía
        """
        with self.window_lock:
            if not self.current_window:
                return None
            
            window_to_analyze = self.current_window.copy()
            self.current_window = []
            self.window_start_time = time.time()
            self.last_analysis_time = time.time()
            
            return window_to_analyze
    
    def build_window_summary(self, window: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Construye un resumen inteligente de la ventana para análisis LLM.
        
        Args:
            window: Lista de logs con clasificaciones
            
        Returns:
            Dict con resumen agregado de la ventana
        """
        if not window:
            return {}
        
        # Agrupar por IP
        ip_data = defaultdict(lambda: {
            'logs': [],
            'threat_types': Counter(),
            'endpoints': set(),
            'methods': set(),
            'severities': Counter(),
            'first_seen': float('inf'),
            'last_seen': 0,
            'total_logs': 0
        })
        
        # Agrupar por endpoint
        endpoint_data = defaultdict(lambda: {
            'ips': set(),
            'threat_types': Counter(),
            'total_requests': 0
        })
        
        # Estadísticas globales
        total_logs = len(window)
        unique_ips = set()
        unique_endpoints = set()
        threat_types_global = Counter()
        severities_global = Counter()
        
        window_start = min(entry['timestamp'] for entry in window)
        window_end = max(entry['timestamp'] for entry in window)
        time_span = window_end - window_start
        
        # Procesar cada entrada
        for entry in window:
            log = entry['log']
            classification = entry.get('classification', {})
            
            ip = log.get('ip') or log.get('remote_addr', 'unknown')
            uri = log.get('uri') or log.get('request_uri', '')
            method = log.get('method', 'GET')
            threat_type = classification.get('threat_type') or 'NONE'
            severity = classification.get('severity', 'low')
            timestamp = entry['timestamp']
            
            unique_ips.add(ip)
            unique_endpoints.add(uri)
            threat_types_global[threat_type] += 1
            severities_global[severity] += 1
            
            # Agrupar por IP
            ip_data[ip]['logs'].append(entry)
            ip_data[ip]['threat_types'][threat_type] += 1
            ip_data[ip]['endpoints'].add(uri)
            ip_data[ip]['methods'].add(method)
            ip_data[ip]['severities'][severity] += 1
            ip_data[ip]['first_seen'] = min(ip_data[ip]['first_seen'], timestamp)
            ip_data[ip]['last_seen'] = max(ip_data[ip]['last_seen'], timestamp)
            ip_data[ip]['total_logs'] += 1
            
            # Agrupar por endpoint
            endpoint_data[uri]['ips'].add(ip)
            endpoint_data[uri]['threat_types'][threat_type] += 1
            endpoint_data[uri]['total_requests'] += 1
        
        # Construir resumen de IPs sospechosas
        suspicious_ips = []
        for ip, data in ip_data.items():
            # Calcular métricas por IP
            unique_threat_types = len([t for t in data['threat_types'].keys() if t != 'NONE'])
            high_severity_count = data['severities'].get('high', 0)
            severity_ratio = high_severity_count / data['total_logs'] if data['total_logs'] > 0 else 0
            unique_endpoints_count = len(data['endpoints'])
            
            # Criterios para considerar IP sospechosa (MÁS AGRESIVOS)
            # Reducir umbrales para detectar escaneos más rápido
            scan_probe_count = data['threat_types'].get('SCAN_PROBE', 0)
            is_suspicious = (
                unique_threat_types >= 1 or  # Cualquier tipo de amenaza (no NONE) - REDUCIDO
                high_severity_count >= 2 or  # 2+ amenazas de alta severidad - REDUCIDO
                (data['total_logs'] >= 3 and severity_ratio >= 0.3) or  # 30%+ alta severidad - REDUCIDO
                unique_endpoints_count >= 5 or  # 5+ endpoints diferentes (escaneo) - REDUCIDO
                scan_probe_count >= 5 or  # 5+ escaneos detectados - NUEVO
                (data['total_logs'] >= 5 and scan_probe_count >= data['total_logs'] * 0.5)  # Mayoría SCAN_PROBE - NUEVO
            )
            
            if is_suspicious:
                suspicious_ips.append({
                    'ip': ip,
                    'total_logs': data['total_logs'],
                    'unique_threat_types': unique_threat_types,
                    'threat_types': dict(data['threat_types']),
                    'high_severity_count': high_severity_count,
                    'severity_ratio': severity_ratio,
                    'unique_endpoints': unique_endpoints_count,
                    'time_span': data['last_seen'] - data['first_seen'],
                    'sample_endpoints': list(data['endpoints'])[:5]  # Primeros 5
                })
        
        # Detectar endpoints atacados por múltiples IPs (ataque distribuido)
        distributed_attacks = []
        for endpoint, data in endpoint_data.items():
            if len(data['ips']) >= 3:  # 3+ IPs diferentes atacando el mismo endpoint
                unique_threats = len([t for t in data['threat_types'].keys() if t != 'NONE'])
                if unique_threats > 0:
                    distributed_attacks.append({
                        'endpoint': endpoint,
                        'attacking_ips': len(data['ips']),
                        'total_requests': data['total_requests'],
                        'threat_types': dict(data['threat_types'])
                    })
        
        # Detectar patrones de escaneo (múltiples endpoints desde pocas IPs)
        scan_patterns = []
        for ip, data in ip_data.items():
            if len(data['endpoints']) >= 10 and data['total_logs'] >= 10:
                scan_patterns.append({
                    'ip': ip,
                    'endpoints_scanned': len(data['endpoints']),
                    'total_requests': data['total_logs'],
                    'time_span': data['last_seen'] - data['first_seen']
                })
        
        # Construir resumen final
        summary = {
            'window_id': f"window_{int(time.time())}",
            'total_logs': total_logs,
            'unique_ips': len(unique_ips),
            'unique_endpoints': len(unique_endpoints),
            'time_span_seconds': time_span,
            'time_span_formatted': f"{time_span:.0f}s" if time_span < 60 else f"{time_span/60:.1f}m",
            'threat_types_global': dict(threat_types_global),
            'severities_global': dict(severities_global),
            'suspicious_ips': suspicious_ips,
            'distributed_attacks': distributed_attacks,
            'scan_patterns': scan_patterns,
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"📊 Resumen de ventana: {total_logs} logs, {len(unique_ips)} IPs, "
                   f"{len(suspicious_ips)} IPs sospechosas, {len(distributed_attacks)} ataques distribuidos, "
                   f"{len(scan_patterns)} patrones de escaneo")
        
        return summary



