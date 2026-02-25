"""
Sistema de Bloqueo Inteligente y Predictivo
- Predicción temprana de ataques
- Bloqueo progresivo (no reactivo)
- Auto-limpieza inteligente
- Evita falsos positivos
"""
import logging
import time
import threading
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum

logger = logging.getLogger(__name__)


class BlockStage(Enum):
    """Etapas progresivas de bloqueo"""
    CLEAN = "clean"              # IP limpia, sin problemas
    MONITOR = "monitor"          # Monitoreo activo (señales tempranas)
    WARNING = "warning"          # Advertencia (patrón sospechoso inicial)
    RATE_LIMIT = "rate_limit"    # Limitar requests (ataque en desarrollo)
    SOFT_BLOCK = "soft_block"    # Bloqueo temporal corto (ataque moderado)
    HARD_BLOCK = "hard_block"    # Bloqueo permanente (ataque confirmado)


class IntelligentBlockingSystem:
    """
    Sistema inteligente de bloqueo que:
    1. Predice ataques ANTES de que se vuelvan críticos
    2. Aplica bloqueo progresivo (no todo o nada)
    3. Auto-limpia bloqueos aprendiendo de comportamiento
    """
    
    def __init__(self, postgres_conn=None, config: Optional[Dict] = None):
        from improvements_config import ImprovementsConfig
        
        self.postgres_conn = postgres_conn
        self.config = config or {}
        
        # Configuración de umbrales (ajustables)
        self.scoring_config = {
            # Scoring multi-factor (cada factor contribuye 0-1)
            'weights': {
                'threat_severity': 0.30,      # Severidad de amenazas detectadas
                'behavior_anomaly': 0.25,     # Anomalías de comportamiento
                'pattern_match': 0.20,        # Coincidencia con patrones conocidos
                'volume_anomaly': 0.15,       # Anomalías de volumen
                'historical_reputation': 0.10  # Reputación histórica
            },
            
            # Umbrales por stage
            'stage_thresholds': {
                BlockStage.MONITOR: 0.25,     # >= 25% = monitorear
                BlockStage.WARNING: 0.40,     # >= 40% = advertencia
                BlockStage.RATE_LIMIT: 0.55,  # >= 55% = rate limit
                BlockStage.SOFT_BLOCK: 0.70,  # >= 70% = bloqueo temporal
                BlockStage.HARD_BLOCK: 0.85   # >= 85% = bloqueo permanente
            },
            
            # Duración de bloqueos
            'block_durations': {
                BlockStage.SOFT_BLOCK: 3600,      # 1 hora
                BlockStage.HARD_BLOCK: None       # Permanente (hasta auto-limpieza)
            },
            
            # Señales tempranas (predicción)
            'early_signals': {
                'min_threat_score': 0.15,      # Si threat_score > 15%, considerar señales
                'rapid_fire_threshold': 3,     # 3+ requests sospechosos en 10s = señal temprana
                'progressive_escalation': 0.10  # +10% de score por cada nueva señal
            }
        }
        
        # Estado de IPs (en memoria, se persiste en BD)
        self.ip_states = defaultdict(lambda: {
            'current_stage': BlockStage.CLEAN,
            'risk_score': 0.0,
            'risk_history': deque(maxlen=50),  # Últimos 50 scores
            'first_seen': time.time(),
            'last_activity': time.time(),
            'total_requests': 0,
            'threat_count': 0,
            'good_behavior_count': 0,
            'stage_history': deque(maxlen=20),
            'early_signals_count': 0,
            'auto_unblock_attempts': 0
        })
        
        # Cache de reputación (aprendizaje)
        self.reputation_cache = defaultdict(lambda: {
            'reputation_score': 0.5,  # 0.0 = malo, 1.0 = bueno, 0.5 = desconocido
            'good_behavior_ratio': 0.0,
            'total_episodes': 0,
            'last_updated': time.time()
        })
        
        self.lock = threading.Lock()
        logger.info("✅ IntelligentBlockingSystem inicializado")
    
    def analyze_and_decide(self, episode: Dict[str, Any], 
                          classification_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza un episodio y decide acción inteligente.
        
        Returns:
            {
                'action': 'allow'|'rate_limit'|'soft_block'|'hard_block',
                'stage': BlockStage,
                'risk_score': float,
                'reason': str,
                'confidence': float,
                'duration_seconds': Optional[int],
                'is_early_prediction': bool
            }
        """
        ip = episode.get('src_ip') or episode.get('ip', 'unknown')
        if ip == 'unknown':
            return {'action': 'allow', 'stage': BlockStage.CLEAN, 'risk_score': 0.0}
        
        # 1. Calcular risk score inteligente
        risk_score = self._calculate_intelligent_risk_score(episode, classification_result)
        
        # 2. Actualizar estado de IP
        with self.lock:
            ip_state = self.ip_states[ip]
            ip_state['risk_history'].append({
                'score': risk_score,
                'timestamp': time.time(),
                'episode_id': episode.get('episode_id')
            })
            ip_state['last_activity'] = time.time()
            ip_state['total_requests'] += episode.get('total_requests', 1)
            
            if classification_result.get('threat_type') and classification_result.get('threat_type') != 'NONE':
                ip_state['threat_count'] += 1
            else:
                ip_state['good_behavior_count'] += 1
        
        # 3. Detectar señales tempranas (PREDICCIÓN)
        early_signals = self._detect_early_signals(ip, risk_score, episode)
        is_early_prediction = len(early_signals) > 0
        
        if is_early_prediction:
            # Aumentar score por señales tempranas (predicción)
            risk_score += len(early_signals) * self.scoring_config['early_signals']['progressive_escalation']
            risk_score = min(1.0, risk_score)
            logger.info(f"🔮 PREDICCIÓN TEMPRANA para IP {ip}: {len(early_signals)} señales detectadas")
        
        # 4. Determinar stage actual
        current_stage = self._determine_stage(risk_score, ip)
        
        # 5. Decidir acción (puede ser más conservadora que el stage para evitar FPs)
        action_decision = self._decide_action(current_stage, risk_score, ip, is_early_prediction)
        
        # 6. Actualizar stage de IP
        with self.lock:
            self.ip_states[ip]['current_stage'] = current_stage
            self.ip_states[ip]['risk_score'] = risk_score
            self.ip_states[ip]['stage_history'].append({
                'stage': current_stage.value,
                'timestamp': time.time(),
                'risk_score': risk_score
            })
            if is_early_prediction:
                self.ip_states[ip]['early_signals_count'] += 1
        
        # 7. Actualizar reputación (aprendizaje)
        self._update_reputation(ip, classification_result)
        
        return action_decision
    
    def _calculate_intelligent_risk_score(self, episode: Dict[str, Any], 
                                         classification: Dict[str, Any]) -> float:
        """
        Calcula risk score multi-factor inteligente.
        Combina múltiples señales para evitar falsos positivos.
        """
        weights = self.scoring_config['weights']
        score = 0.0
        
        # 1. Threat Severity (30%)
        threat_score = self._calculate_threat_severity(episode, classification)
        score += threat_score * weights['threat_severity']
        
        # 2. Behavior Anomaly (25%)
        behavior_score = self._calculate_behavior_anomaly(episode)
        score += behavior_score * weights['behavior_anomaly']
        
        # 3. Pattern Match (20%)
        pattern_score = self._calculate_pattern_match(episode, classification)
        score += pattern_score * weights['pattern_match']
        
        # 4. Volume Anomaly (15%)
        volume_score = self._calculate_volume_anomaly(episode)
        score += volume_score * weights['volume_anomaly']
        
        # 5. Historical Reputation (10%)
        ip = episode.get('src_ip') or episode.get('ip', '')
        reputation_score = self._get_reputation_score(ip)
        # Reputación baja AUMENTA riesgo, reputación alta LO DISMINUYE
        score += (1.0 - reputation_score) * weights['historical_reputation']
        
        return min(1.0, max(0.0, score))
    
    def _calculate_threat_severity(self, episode: Dict[str, Any], 
                                   classification: Dict[str, Any]) -> float:
        """Calcula severidad de amenazas detectadas"""
        threat_type = classification.get('threat_type', 'NONE')
        severity = classification.get('severity', 'low')
        confidence = classification.get('confidence', 0.5)
        
        # Mapeo de severidad
        severity_map = {
            'critical': 1.0,
            'high': 0.8,
            'medium': 0.5,
            'low': 0.3
        }
        
        base_score = severity_map.get(severity, 0.1)
        
        # Si no hay threat_type o es NONE, score bajo
        if not threat_type or threat_type == 'NONE':
            return 0.1
        
        # Ajustar por confianza
        adjusted_score = base_score * confidence
        
        # Múltiples tipos de amenaza aumentan score
        threat_types = episode.get('threat_types', {})
        unique_threats = len([t for t in threat_types.keys() if t != 'NONE'])
        if unique_threats > 1:
            adjusted_score = min(1.0, adjusted_score * (1 + unique_threats * 0.1))
        
        return adjusted_score
    
    def _calculate_behavior_anomaly(self, episode: Dict[str, Any]) -> float:
        """Detecta anomalías de comportamiento"""
        score = 0.0
        
        # Request rate anormal
        request_rate = episode.get('request_rate', 0)
        if request_rate > 10:  # > 10 req/s es muy alto
            score += 0.4
        elif request_rate > 5:
            score += 0.2
        
        # Muchos endpoints diferentes (escaneo)
        unique_uris = episode.get('unique_uris', 0)
        if unique_uris > 20:
            score += 0.4
        elif unique_uris > 10:
            score += 0.2
        
        # Patrones de escaneo
        presence_flags = episode.get('presence_flags', {})
        if presence_flags.get('.env') or presence_flags.get('../'):
            score += 0.3
        if presence_flags.get('wp-') or presence_flags.get('.git'):
            score += 0.2
        
        # Ratio de errores 4xx (escaneo)
        status_ratios = episode.get('status_code_ratio', {})
        error_ratio = status_ratios.get('4xx', 0)
        if error_ratio > 0.7:  # >70% son errores
            score += 0.3
        elif error_ratio > 0.5:
            score += 0.15
        
        return min(1.0, score)
    
    def _calculate_pattern_match(self, episode: Dict[str, Any], 
                                classification: Dict[str, Any]) -> float:
        """Coincidencia con patrones de ataque conocidos"""
        # Si hay intelligence_analysis, usar esas señales
        intelligence = episode.get('intelligence_analysis', {})
        
        score = 0.0
        
        if intelligence.get('zero_day_risk'):
            score += 0.5  # Alto riesgo de zero-day
        if intelligence.get('ddos_risk'):
            score += 0.4  # Riesgo de DDoS
        if intelligence.get('obfuscation_detected'):
            score += 0.3  # Ofuscación detectada
        
        # Patrones conocidos de ataque
        threat_types = episode.get('threat_types', {})
        known_attack_patterns = ['SQLI', 'XSS', 'PATH_TRAVERSAL', 'CMD_INJECTION']
        if any(t in threat_types for t in known_attack_patterns):
            score += 0.3
        
        return min(1.0, score)
    
    def _calculate_volume_anomaly(self, episode: Dict[str, Any]) -> float:
        """Anomalías de volumen de tráfico"""
        total_requests = episode.get('total_requests', 0)
        
        # Para una IP normal, 100+ requests en 5 minutos es muy alto
        if total_requests > 100:
            return 0.6
        elif total_requests > 50:
            return 0.4
        elif total_requests > 20:
            return 0.2
        
        return 0.0
    
    def _get_reputation_score(self, ip: str) -> float:
        """Obtiene score de reputación histórica (0.0=malo, 1.0=bueno)"""
        if ip not in self.reputation_cache:
            return 0.5  # Desconocido = neutral
        
        # Si la reputación tiene más de 24 horas, considerar actualizar
        cache_age = time.time() - self.reputation_cache[ip]['last_updated']
        if cache_age > 86400:  # 24 horas
            # Recargar desde BD si es necesario
            self._load_reputation_from_db(ip)
        
        return self.reputation_cache[ip]['reputation_score']
    
    def _detect_early_signals(self, ip: str, risk_score: float, 
                             episode: Dict[str, Any]) -> List[str]:
        """
        Detecta señales tempranas que predicen un ataque ANTES de que sea crítico.
        PREDICCIÓN: Actúa antes de que el riesgo sea alto.
        """
        signals = []
        config = self.scoring_config['early_signals']
        
        # Señal 1: Risk score en aumento rápido
        with self.lock:
            ip_state = self.ip_states[ip]
            if len(ip_state['risk_history']) >= 2:
                recent_scores = [h['score'] for h in list(ip_state['risk_history'])[-3:]]
                if len(recent_scores) >= 2:
                    score_increase = recent_scores[-1] - recent_scores[0]
                    if score_increase > 0.15:  # Aumento rápido de 15%+
                        signals.append('rapid_score_increase')
            
            # Señal 2: Múltiples requests sospechosos en poco tiempo (rapid fire)
            threat_type = episode.get('threat_type') or episode.get('classification', {}).get('threat_type')
            if threat_type and threat_type != 'NONE':
                # Verificar si hay múltiples requests sospechosos recientes
                recent_threats = sum(1 for h in ip_state.get('risk_history', []) 
                                   if time.time() - h['timestamp'] < 10)  # Últimos 10 segundos
                if recent_threats >= config['rapid_fire_threshold']:
                    signals.append('rapid_fire_attack')
            
            # Señal 3: Progresión de amenazas (de bajo a alto)
            if len(ip_state.get('stage_history', [])) >= 2:
                recent_stages = [h['stage'] for h in list(ip_state['stage_history'])[-3:]]
                if recent_stages[-1] in ['warning', 'rate_limit'] and recent_stages[0] == 'clean':
                    signals.append('progressive_escalation')
            
            # Señal 4: Comportamiento nuevo pero sospechoso
            if risk_score > config['min_threat_score']:
                if ip_state['total_requests'] < 10:  # IP nueva pero ya sospechosa
                    signals.append('new_suspicious_behavior')
        
        return signals
    
    def _determine_stage(self, risk_score: float, ip: str) -> BlockStage:
        """Determina el stage actual basado en risk_score"""
        thresholds = self.scoring_config['stage_thresholds']
        
        # También considerar historial (si ha estado en stage alto, mantener un poco más)
        with self.lock:
            ip_state = self.ip_states[ip]
            if ip_state['stage_history']:
                last_stage_value = ip_state['stage_history'][-1]['stage']
                # Si estaba en stage alto recientemente, requerir score ligeramente menor para bajar
                if last_stage_value in ['soft_block', 'hard_block']:
                    risk_score = max(risk_score, risk_score * 1.1)  # +10% para mantener stage alto
        
        if risk_score >= thresholds[BlockStage.HARD_BLOCK]:
            return BlockStage.HARD_BLOCK
        elif risk_score >= thresholds[BlockStage.SOFT_BLOCK]:
            return BlockStage.SOFT_BLOCK
        elif risk_score >= thresholds[BlockStage.RATE_LIMIT]:
            return BlockStage.RATE_LIMIT
        elif risk_score >= thresholds[BlockStage.WARNING]:
            return BlockStage.WARNING
        elif risk_score >= thresholds[BlockStage.MONITOR]:
            return BlockStage.MONITOR
        else:
            return BlockStage.CLEAN
    
    def _decide_action(self, stage: BlockStage, risk_score: float, 
                      ip: str, is_early_prediction: bool) -> Dict[str, Any]:
        """
        Decide acción final. Puede ser más conservadora que el stage para evitar FPs.
        """
        # Para predicciones tempranas, ser más conservador (evitar FPs)
        if is_early_prediction and stage in [BlockStage.SOFT_BLOCK, BlockStage.HARD_BLOCK]:
            # En lugar de bloquear inmediatamente, aplicar rate limit primero
            stage = BlockStage.RATE_LIMIT
            reason = f"Predicción temprana de ataque - aplicando rate limit preventivo"
        else:
            reason = f"Riesgo {risk_score:.1%} - Stage {stage.value}"
        
        # Mapeo de stage a acción
        action_map = {
            BlockStage.CLEAN: 'allow',
            BlockStage.MONITOR: 'allow',  # Solo monitorear, no bloquear
            BlockStage.WARNING: 'allow',  # Solo alertar, no bloquear aún
            BlockStage.RATE_LIMIT: 'rate_limit',
            BlockStage.SOFT_BLOCK: 'soft_block',
            BlockStage.HARD_BLOCK: 'hard_block'
        }
        
        action = action_map.get(stage, 'allow')
        duration = self.scoring_config['block_durations'].get(stage)
        
        # Calcular confianza basada en qué tan claro es el riesgo
        confidence = min(1.0, risk_score * 1.2) if risk_score > 0.5 else risk_score * 2.0
        
        return {
            'action': action,
            'stage': stage,
            'risk_score': risk_score,
            'reason': reason,
            'confidence': confidence,
            'duration_seconds': duration,
            'is_early_prediction': is_early_prediction
        }
    
    def _update_reputation(self, ip: str, classification: Dict[str, Any]):
        """Actualiza reputación de IP basado en comportamiento"""
        if ip not in self.reputation_cache:
            self.reputation_cache[ip] = {
                'reputation_score': 0.5,
                'good_behavior_ratio': 0.0,
                'total_episodes': 0,
                'last_updated': time.time()
            }
        
        cache = self.reputation_cache[ip]
        cache['total_episodes'] += 1
        
        # Si no hay amenazas, es comportamiento bueno
        threat_type = classification.get('threat_type', 'NONE')
        if not threat_type or threat_type == 'NONE':
            cache['good_behavior_ratio'] = (
                (cache['good_behavior_ratio'] * (cache['total_episodes'] - 1) + 1.0) 
                / cache['total_episodes']
            )
        else:
            cache['good_behavior_ratio'] = (
                (cache['good_behavior_ratio'] * (cache['total_episodes'] - 1) + 0.0) 
                / cache['total_episodes']
            )
        
        # Reputación = ratio de comportamiento bueno
        cache['reputation_score'] = cache['good_behavior_ratio']
        cache['last_updated'] = time.time()
    
    def _load_reputation_from_db(self, ip: str):
        """Carga reputación desde BD si está disponible"""
        # TODO: Implementar si hay tabla de reputación
        pass
    
    def should_auto_unblock(self, ip: str) -> Tuple[bool, str]:
        """
        Determina si una IP bloqueada debe ser auto-desbloqueada.
        AUTO-LIMPIEZA INTELIGENTE.
        """
        with self.lock:
            ip_state = self.ip_states[ip]
            
            # Si está en CLEAN o MONITOR, no necesita desbloquear
            if ip_state['current_stage'] in [BlockStage.CLEAN, BlockStage.MONITOR]:
                return False, "IP ya está limpia"
            
            # Verificar tiempo desde último bloqueo
            if not ip_state['stage_history']:
                return False, "Sin historial de bloqueo"
            
            last_block = None
            for stage_entry in reversed(ip_state['stage_history']):
                if stage_entry['stage'] in ['soft_block', 'hard_block']:
                    last_block = stage_entry
                    break
            
            if not last_block:
                return False, "No hay bloqueo activo en historial"
            
            time_since_block = time.time() - last_block['timestamp']
            
            # Si es HARD_BLOCK, requerir más tiempo antes de considerar desbloquear
            min_wait_time = 3600 if ip_state['current_stage'] == BlockStage.HARD_BLOCK else 1800  # 1h o 30min
            
            if time_since_block < min_wait_time:
                return False, f"Esperando {min_wait_time/60:.0f} minutos antes de considerar desbloqueo"
            
            # Verificar si el comportamiento reciente es bueno
            recent_scores = [h['score'] for h in list(ip_state['risk_history'])[-10:] 
                           if time.time() - h['timestamp'] < 3600]  # Última hora
            
            if not recent_scores:
                return False, "Sin actividad reciente"
            
            avg_recent_score = sum(recent_scores) / len(recent_scores)
            
            # Si el score promedio reciente es bajo, considerar desbloquear
            if avg_recent_score < 0.3:  # Score bajo = comportamiento bueno
                # Pero verificar que no haya tenido muchos intentos de desbloqueo fallidos
                if ip_state['auto_unblock_attempts'] < 3:
                    ip_state['auto_unblock_attempts'] += 1
                    return True, f"Comportamiento bueno reciente (score promedio: {avg_recent_score:.2f})"
            
            return False, f"Score promedio aún alto: {avg_recent_score:.2f}"
    
    def execute_auto_unblock(self, ip: str) -> bool:
        """Ejecuta auto-desbloqueo de IP"""
        should_unblock, reason = self.should_auto_unblock(ip)
        
        if should_unblock:
            with self.lock:
                self.ip_states[ip]['current_stage'] = BlockStage.MONITOR
                self.ip_states[ip]['auto_unblock_attempts'] = 0  # Reset contador
                logger.info(f"🧹 AUTO-DESBLOQUEO: IP {ip} - {reason}")
            return True
        
        return False
