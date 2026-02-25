"""
Sliding Window Pattern Detector - Detecta patrones en ventanas de tiempo deslizantes
"""
import logging
import time
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)


class SlidingWindowPatternDetector:
    """
    Detecta patrones sospechosos en ventanas de tiempo deslizantes.
    Útil para detectar escaneos, ataques distribuidos, etc.
    """
    
    def __init__(self, window_size_seconds: int = 300, min_events: int = 5):
        """
        Inicializa el detector de patrones.
        
        Args:
            window_size_seconds: Tamaño de la ventana en segundos (default: 5 minutos)
            min_events: Número mínimo de eventos para considerar un patrón
        """
        self.window_size_seconds = window_size_seconds
        self.min_events = min_events
        
        # Ventanas deslizantes por IP
        self.ip_windows = defaultdict(lambda: deque())
        self.ip_locks = defaultdict(lambda: threading.Lock())
        
        # Ventanas deslizantes por patrón
        self.pattern_windows = defaultdict(lambda: deque())
        self.pattern_locks = defaultdict(lambda: threading.Lock())
        
        # Métricas
        self.metrics = {
            'total_patterns_detected': 0,
            'active_windows': 0,
            'total_ips_tracked': 0
        }
        self.metrics_lock = threading.Lock()
    
    def add_event(self, log: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Agrega un evento y detecta patrones.
        
        Args:
            log: Log normalizado
        
        Returns:
            Lista de patrones detectados
        """
        current_time = time.time()
        ip = log.get('ip', 'unknown')
        uri = log.get('uri', '')
        threat_type = log.get('threat_type') or log.get('threat_type')
        blocked = log.get('blocked', False)
        
        patterns_detected = []
        
        # Limpiar eventos antiguos de la ventana
        self._clean_old_events(current_time)
        
        # Agregar evento a ventana por IP
        with self.ip_locks[ip]:
            self.ip_windows[ip].append({
                'timestamp': current_time,
                'log': log,
                'uri': uri,
                'threat_type': threat_type,
                'blocked': blocked
            })
        
        # Detectar patrones por IP
        ip_patterns = self._detect_ip_patterns(ip, current_time)
        patterns_detected.extend(ip_patterns)
        
        # Detectar patrones por tipo de amenaza
        if threat_type:
            pattern_key = f"{threat_type}:{ip}"
            with self.pattern_locks[pattern_key]:
                self.pattern_windows[pattern_key].append({
                    'timestamp': current_time,
                    'log': log,
                    'ip': ip,
                    'threat_type': threat_type
                })
            
            threat_patterns = self._detect_threat_patterns(pattern_key, current_time)
            patterns_detected.extend(threat_patterns)
        
        # Actualizar métricas
        with self.metrics_lock:
            self.metrics['total_patterns_detected'] += len(patterns_detected)
            self.metrics['active_windows'] = len(self.ip_windows) + len(self.pattern_windows)
            self.metrics['total_ips_tracked'] = len(self.ip_windows)
        
        return patterns_detected
    
    def _clean_old_events(self, current_time: float):
        """Elimina eventos fuera de la ventana"""
        cutoff_time = current_time - self.window_size_seconds
        
        # Limpiar ventanas de IPs
        ips_to_remove = []
        for ip, window in self.ip_windows.items():
            with self.ip_locks[ip]:
                while window and window[0]['timestamp'] < cutoff_time:
                    window.popleft()
                if not window:
                    ips_to_remove.append(ip)
        
        for ip in ips_to_remove:
            del self.ip_windows[ip]
            del self.ip_locks[ip]
        
        # Limpiar ventanas de patrones
        patterns_to_remove = []
        for pattern_key, window in self.pattern_windows.items():
            with self.pattern_locks[pattern_key]:
                while window and window[0]['timestamp'] < cutoff_time:
                    window.popleft()
                if not window:
                    patterns_to_remove.append(pattern_key)
        
        for pattern_key in patterns_to_remove:
            del self.pattern_windows[pattern_key]
            del self.pattern_locks[pattern_key]
    
    def _detect_ip_patterns(self, ip: str, current_time: float) -> List[Dict[str, Any]]:
        """Detecta patrones sospechosos por IP"""
        patterns = []
        
        with self.ip_locks[ip]:
            window = self.ip_windows[ip]
            
            if len(window) < self.min_events:
                return patterns
            
            # Calcular estadísticas
            events = list(window)
            blocked_count = sum(1 for e in events if e['blocked'])
            unique_uris = len(set(e['uri'] for e in events))
            threat_types = [e['threat_type'] for e in events if e['threat_type']]
            
            # Patrón 1: Múltiples intentos bloqueados
            if blocked_count >= 5:
                patterns.append({
                    'pattern_type': 'multiple_blocked_attempts',
                    'ip': ip,
                    'severity': 'high',
                    'description': f"{blocked_count} intentos bloqueados en {self.window_size_seconds}s",
                    'count': blocked_count,
                    'window_start': events[0]['timestamp'],
                    'window_end': current_time
                })
            
            # Patrón 2: Escaneo (muchas URIs diferentes)
            if unique_uris >= 20:
                patterns.append({
                    'pattern_type': 'scanning',
                    'ip': ip,
                    'severity': 'medium',
                    'description': f"Escaneo detectado: {unique_uris} URIs diferentes",
                    'unique_uris': unique_uris,
                    'window_start': events[0]['timestamp'],
                    'window_end': current_time
                })
            
            # Patrón 3: Ataque persistente (mismo tipo de amenaza repetido)
            if threat_types:
                from collections import Counter
                threat_counter = Counter(threat_types)
                most_common = threat_counter.most_common(1)[0]
                if most_common[1] >= 5:
                    patterns.append({
                        'pattern_type': 'persistent_attack',
                        'ip': ip,
                        'threat_type': most_common[0],
                        'severity': 'high',
                        'description': f"Ataque persistente: {most_common[0]} ({most_common[1]} veces)",
                        'count': most_common[1],
                        'window_start': events[0]['timestamp'],
                        'window_end': current_time
                    })
            
            # Patrón 4: Alta frecuencia de requests
            if len(events) >= 50:
                time_span = current_time - events[0]['timestamp']
                if time_span > 0:
                    rate = len(events) / time_span
                    if rate > 10:  # Más de 10 requests/segundo
                        patterns.append({
                            'pattern_type': 'high_frequency',
                            'ip': ip,
                            'severity': 'medium',
                            'description': f"Alta frecuencia: {rate:.1f} requests/segundo",
                            'rate': rate,
                            'window_start': events[0]['timestamp'],
                            'window_end': current_time
                        })
        
        return patterns
    
    def _detect_threat_patterns(self, pattern_key: str, current_time: float) -> List[Dict[str, Any]]:
        """Detecta patrones por tipo de amenaza"""
        patterns = []
        
        with self.pattern_locks[pattern_key]:
            window = self.pattern_windows[pattern_key]
            
            if len(window) < self.min_events:
                return patterns
            
            # Patrón: Ataque distribuido (mismo tipo de amenaza desde múltiples IPs)
            events = list(window)
            unique_ips = len(set(e['ip'] for e in events))
            
            if unique_ips >= 3 and len(events) >= 10:
                threat_type = pattern_key.split(':')[0]
                patterns.append({
                    'pattern_type': 'distributed_attack',
                    'threat_type': threat_type,
                    'severity': 'high',
                    'description': f"Ataque distribuido: {threat_type} desde {unique_ips} IPs",
                    'unique_ips': unique_ips,
                    'total_events': len(events),
                    'window_start': events[0]['timestamp'],
                    'window_end': current_time
                })
        
        return patterns
    
    def get_ip_statistics(self, ip: str) -> Optional[Dict[str, Any]]:
        """Obtiene estadísticas de una IP"""
        if ip not in self.ip_windows:
            return None
        
        with self.ip_locks[ip]:
            window = self.ip_windows[ip]
            if not window:
                return None
            
            events = list(window)
            current_time = time.time()
            
            return {
                'ip': ip,
                'total_events': len(events),
                'blocked_count': sum(1 for e in events if e['blocked']),
                'unique_uris': len(set(e['uri'] for e in events)),
                'threat_types': list(set(e['threat_type'] for e in events if e['threat_type'])),
                'window_start': events[0]['timestamp'],
                'window_end': current_time,
                'window_duration': current_time - events[0]['timestamp']
            }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas del detector"""
        with self.metrics_lock:
            return {
                **self.metrics,
                'window_size_seconds': self.window_size_seconds,
                'min_events': self.min_events
            }



