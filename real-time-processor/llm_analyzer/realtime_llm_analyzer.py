"""
LLM Analyzer en Tiempo Real - Análisis profundo con LLM para amenazas críticas (< 500ms)
"""
import logging
import os
import time
import json
import re
from typing import Dict, Any, Optional, List
from collections import deque
import threading

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("google-generativeai no disponible, análisis LLM limitado")

logger = logging.getLogger(__name__)


class RealtimeLLMAnalyzer:
    """
    Analizador LLM optimizado para tiempo real.
    Solo se usa para amenazas críticas detectadas por ML (threat_score > 0.7).
    """
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.0-flash"):
        """
        Inicializa el analizador LLM.
        
        Args:
            api_key: API key de Gemini (o desde env GEMINI_API_KEY)
            model_name: Nombre del modelo a usar
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY', '')
        self.model_name = model_name
        self.model = None
        self.enabled = False
        
        # Cache de análisis recientes (evitar análisis duplicados)
        self.analysis_cache = {}
        self.cache_max_size = 1000
        self.cache_ttl = 300  # 5 minutos
        
        # Métricas
        self.metrics = {
            'total_analyses': 0,
            'total_time_ms': 0.0,
            'avg_time_ms': 0.0,
            'max_time_ms': 0.0,
            'min_time_ms': float('inf'),
            'errors': 0,
            'cache_hits': 0,
            'llm_analyses': 0,  # Agregado para analyze_episode y quick_dashboard_scan
            'llm_latency_ms': []  # Lista para latencias de LLM
        }
        self.metrics_lock = threading.Lock()
        
        # Inicializar modelo
        if GEMINI_AVAILABLE and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.model_name)
                self.enabled = True
                logger.info(f"✅ LLM Analyzer inicializado: {self.model_name}")
            except Exception as e:
                logger.error(f"Error inicializando LLM: {e}")
                self.enabled = False
        else:
            logger.warning("LLM no disponible, análisis limitado a heurísticas")
            self.enabled = False
    
    def _get_cache_key(self, log: Dict[str, Any]) -> str:
        """Genera una clave de cache para un log"""
        # Usar IP + URI + timestamp (redondeado a minuto) como clave
        ip = log.get('ip', '')
        uri = log.get('uri', '')[:100]  # Limitar tamaño
        timestamp = log.get('timestamp', '')
        if timestamp:
            # Redondear a minuto
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                timestamp = dt.strftime('%Y-%m-%dT%H:%M')
            except:
                pass
        
        return f"{ip}:{uri}:{timestamp}"
    
    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Verifica si una entrada de cache es válida"""
        return time.time() - cache_entry['timestamp'] < self.cache_ttl
    
    def analyze(self, log: Dict[str, Any], ml_prediction: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Analiza un log con LLM (solo para amenazas críticas).
        
        Args:
            log: Log normalizado
            ml_prediction: Predicción previa de ML (opcional)
        
        Returns:
            Dict con análisis detallado
        """
        start_time = time.time()
        
        # Verificar si es necesario analizar (solo amenazas críticas)
        if ml_prediction:
            threat_score = ml_prediction.get('threat_score', 0)
            if threat_score < 0.7:  # Solo analizar amenazas críticas
                return {
                    "success": True,
                    "analyzed": False,
                    "reason": "Threat score too low for LLM analysis",
                    "analysis_time_ms": 0
                }
        
        # Verificar cache
        cache_key = self._get_cache_key(log)
        if cache_key in self.analysis_cache:
            cache_entry = self.analysis_cache[cache_key]
            if self._is_cache_valid(cache_entry):
                with self.metrics_lock:
                    self.metrics['cache_hits'] += 1
                return {
                    **cache_entry['result'],
                    "from_cache": True,
                    "analysis_time_ms": 0
                }
        
        # Si LLM no está disponible, usar análisis heurístico
        if not self.enabled:
            return self._analyze_heuristic(log, start_time)
        
        try:
            # Preparar prompt
            prompt = self._build_analysis_prompt(log, ml_prediction)
            
            # Analizar con LLM
            response = self.model.generate_content(prompt)
            response_text = response.text
            
            # Parsear respuesta
            analysis = self._parse_llm_response(response_text, log)
            
            # Calcular tiempo
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Actualizar métricas
            with self.metrics_lock:
                self.metrics['total_analyses'] += 1
                self.metrics['total_time_ms'] += elapsed_ms
                self.metrics['avg_time_ms'] = self.metrics['total_time_ms'] / self.metrics['total_analyses']
                self.metrics['max_time_ms'] = max(self.metrics['max_time_ms'], elapsed_ms)
                self.metrics['min_time_ms'] = min(self.metrics['min_time_ms'], elapsed_ms)
            
            # Guardar en cache
            if len(self.analysis_cache) >= self.cache_max_size:
                # Eliminar entrada más antigua
                oldest_key = min(self.analysis_cache.keys(), 
                               key=lambda k: self.analysis_cache[k]['timestamp'])
                del self.analysis_cache[oldest_key]
            
            result = {
                "success": True,
                "analyzed": True,
                "severity": analysis.get('severity', 'medium'),
                "action": analysis.get('action', 'monitor'),
                "threat_type": analysis.get('threat_type'),
                "explanation": analysis.get('explanation', ''),
                "confidence": analysis.get('confidence', 0.8),
                "analysis_time_ms": round(elapsed_ms, 2),
                "from_cache": False
            }
            
            self.analysis_cache[cache_key] = {
                'result': result,
                'timestamp': time.time()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error en análisis LLM: {e}", exc_info=True)
            with self.metrics_lock:
                self.metrics['errors'] += 1
            
            # Fallback a heurística
            return self._analyze_heuristic(log, start_time)
    
    def _build_analysis_prompt(self, log: Dict[str, Any], ml_prediction: Optional[Dict[str, Any]]) -> str:
        """Construye el prompt para el LLM con enfoque en tipo de ataque"""
        uri = log.get('uri', '') or (log.get('raw_log', {}) or {}).get('uri', '')
        query = log.get('query_string', '') or (log.get('raw_log', {}) or {}).get('query_string', '')
        ip = log.get('ip', '') or (log.get('raw_log', {}) or {}).get('ip', '')
        method = log.get('method', 'GET') or (log.get('raw_log', {}) or {}).get('method', 'GET')
        status = log.get('status', 200) or (log.get('raw_log', {}) or {}).get('status', 200)
        user_agent = log.get('user_agent', '') or (log.get('raw_log', {}) or {}).get('user_agent', '')
        blocked = log.get('blocked', False)
        is_waf_blocked = (status == 403) or blocked
        
        ml_info = ""
        if ml_prediction:
            ml_info = f"""
Predicción ML previa:
- Severidad: {ml_prediction.get('predicted_severity', 'unknown')}
- Threat Score: {ml_prediction.get('threat_score', 0):.2f}
- Confianza: {ml_prediction.get('confidence', 0):.2f}
- Modelo: {ml_prediction.get('model_id', 'unknown')}
"""
        
        # Indicar si hay duda
        has_doubt = ml_prediction and ml_prediction.get('confidence', 1.0) < 0.5
        doubt_info = "\n⚠️ NOTA: El modelo ML tiene BAJA CONFIANZA en esta predicción. Necesitamos tu análisis detallado." if has_doubt else ""
        
        prompt = f"""
Eres un experto analista de seguridad SOC. Analiza este log del WAF y clasifica el tipo de ataque.

Log:
- IP: {ip}
- Método: {method}
- URI: {uri}
- Query String: {query[:300]}
- Status Code: {status}
- Bloqueado por WAF: {is_waf_blocked}
- User Agent: {user_agent[:150]}
{ml_info}{doubt_info}

IMPORTANTE - DETECCIÓN DE ESCANEOS:
1. Si el URI contiene archivos comunes de información/configuración (phpinfo.php, info.php, 
   server-info.php, test.php, debug.php, config.php, .env, etc.) → clasificar como SCAN_PROBE
2. Si hay múltiples intentos a diferentes archivos desde la misma IP → SCAN_PROBE
3. Si status es 404 en rutas de archivos de configuración → SCAN_PROBE
4. Si status es 301/302 en rutas sospechosas → SCAN_PROBE
5. NUNCA usar "NONE" para escaneos - siempre usar SCAN_PROBE

IMPORTANTE:
1. Si el WAF NO bloqueó (status != 403) pero detectas un ataque, clasifica el TIPO DE ATAQUE específico
2. Tipos de ataque posibles: SQLI, XSS, PATH_TRAVERSAL, CMD_INJECTION, RFI_LFI, XXE, SSRF, CSRF, BRUTE_FORCE, SCAN_PROBE, OTHER, NONE
3. NONE solo debe usarse para tráfico completamente normal (páginas estáticas, assets, rutas comunes conocidas)
4. Clasifica según OWASP Top 10 2021 cuando sea posible:
   - A01 (Broken Access Control): PATH_TRAVERSAL, SCAN_PROBE, UNAUTHORIZED_ACCESS
   - A03 (Injection): SQLI, XSS, CMD_INJECTION, RFI_LFI, XXE
   - A07 (Authentication Failures): BRUTE_FORCE, CREDENTIAL_STUFFING
   - A10 (SSRF): SSRF

Responde SOLO en formato JSON válido (sin markdown, sin texto adicional):
{{
    "severity": "low|medium|high",
    "threat_type": "SQLI|XSS|PATH_TRAVERSAL|CMD_INJECTION|RFI_LFI|XXE|SSRF|CSRF|BRUTE_FORCE|SCAN_PROBE|OTHER|NONE",
    "owasp_code": "A01|A02|A03|A05|A07|A08|A10|null",
    "owasp_category": "Nombre de la categoría OWASP (opcional)",
    "action": "log_only|monitor|block_ip",
    "explanation": "Explicación breve del tipo de ataque detectado",
    "confidence": 0.0-1.0
}}

Si es un ataque real, threat_type debe ser específico (SQLI, XSS, etc.), NO "OTHER" a menos que sea realmente otro tipo.
"""
        return prompt
    
    def _parse_llm_response(self, response_text: str, log: Dict[str, Any]) -> Dict[str, Any]:
        """Parsea la respuesta del LLM con mejor detección de tipo de ataque"""
        try:
            # Limpiar respuesta (puede venir con markdown)
            cleaned = response_text.strip()
            if cleaned.startswith('```json'):
                cleaned = cleaned[7:]
            if cleaned.startswith('```'):
                cleaned = cleaned[3:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            # Buscar JSON en la respuesta (mejorado para multilínea)
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                # Validar y normalizar threat_type
                valid_threat_types = ['SQLI', 'XSS', 'PATH_TRAVERSAL', 'CMD_INJECTION', 'RFI_LFI', 'XXE', 'SSRF', 'CSRF', 'BRUTE_FORCE', 'SCAN_PROBE', 'OTHER', 'NONE']
                if result.get('threat_type'):
                    threat_type_upper = result['threat_type'].upper()
                    if threat_type_upper in valid_threat_types:
                        result['threat_type'] = threat_type_upper
                    else:
                        # Mapear variaciones comunes
                        threat_type_map = {
                            'SQL_INJECTION': 'SQLI',
                            'SQLI': 'SQLI',
                            'CROSS_SITE_SCRIPTING': 'XSS',
                            'XSS': 'XSS',
                            'PATH_TRAVERSAL': 'PATH_TRAVERSAL',
                            'COMMAND_INJECTION': 'CMD_INJECTION',
                            'CMD_INJECTION': 'CMD_INJECTION',
                            'RFI': 'RFI_LFI',
                            'LFI': 'RFI_LFI',
                            'RFI_LFI': 'RFI_LFI'
                        }
                        result['threat_type'] = threat_type_map.get(threat_type_upper, 'OTHER')
                return result
        except json.JSONDecodeError as e:
            logger.warning(f"Error parseando JSON del LLM: {e}, respuesta: {response_text[:200]}")
        except Exception as e:
            logger.warning(f"Error parseando respuesta LLM: {e}")
        
        # Fallback: parsear texto libre con mejor detección
        response_lower = response_text.lower()
        
        # Inferir severidad
        if 'high' in response_lower or 'critical' in response_lower:
            severity = 'high'
        elif 'medium' in response_lower:
            severity = 'medium'
        else:
            severity = 'low'
        
        # Inferir acción
        if 'block' in response_lower:
            action = 'block_ip'
        elif 'monitor' in response_lower:
            action = 'monitor'
        else:
            action = 'log_only'
        
        # Inferir tipo de amenaza con mejor detección
        threat_type = 'NONE'
        if any(kw in response_lower for kw in ['sql', 'sql injection', 'union select', "'--", "'1'='1"]):
            threat_type = 'SQLI'
        elif any(kw in response_lower for kw in ['xss', 'cross-site scripting', 'script', 'javascript:', '<script']):
            threat_type = 'XSS'
        elif any(kw in response_lower for kw in ['path traversal', '../', '/etc/passwd', 'directory traversal']):
            threat_type = 'PATH_TRAVERSAL'
        elif any(kw in response_lower for kw in ['command injection', 'cmd=', 'exec=', 'system(']):
            threat_type = 'CMD_INJECTION'
        elif any(kw in response_lower for kw in ['rfi', 'lfi', 'remote file inclusion', 'local file inclusion']):
            threat_type = 'RFI_LFI'
        elif any(kw in response_lower for kw in ['xxe', 'xml external entity']):
            threat_type = 'XXE'
        elif any(kw in response_lower for kw in ['ssrf', 'server-side request forgery']):
            threat_type = 'SSRF'
        elif any(kw in response_lower for kw in ['csrf', 'cross-site request forgery']):
            threat_type = 'CSRF'
        elif any(kw in response_lower for kw in ['attack', 'malicious', 'threat', 'exploit']):
            threat_type = 'OTHER'
        
        return {
            'severity': severity,
            'action': action,
            'threat_type': threat_type,
            'explanation': response_text[:200],
            'confidence': 0.7
        }
    
    def _analyze_heuristic(self, log: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        """Análisis heurístico cuando LLM no está disponible"""
        uri = log.get('uri', '')
        query = log.get('query_string', '')
        text = f"{uri} {query}".lower()
        
        # Detectar amenazas
        has_sqli = any(kw in text for kw in ['union', 'select', 'drop', "'--", "'1'='1"])
        has_xss = any(kw in text for kw in ['<script', 'javascript:', 'onerror='])
        has_path_traversal = any(kw in text for kw in ['../', '/etc/passwd'])
        has_cmd_injection = any(kw in text for kw in ['cmd=', 'exec=', 'system('])
        
        # Determinar severidad y acción
        if has_sqli or has_xss or has_path_traversal or has_cmd_injection:
            severity = 'high'
            action = 'block_ip'
            threat_type = 'SQLI' if has_sqli else ('XSS' if has_xss else ('PATH_TRAVERSAL' if has_path_traversal else 'CMD_INJECTION'))
        elif log.get('blocked') or log.get('status') == 403:
            severity = 'medium'
            action = 'monitor'
            threat_type = None
        else:
            severity = 'low'
            action = 'log_only'
            threat_type = None
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return {
            "success": True,
            "analyzed": True,
            "severity": severity,
            "action": action,
            "threat_type": threat_type,
            "explanation": "Análisis heurístico (LLM no disponible)",
            "confidence": 0.6,
            "analysis_time_ms": round(elapsed_ms, 2),
            "from_cache": False
        }
    
    def analyze_batch(self, batch_summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza un batch completo de logs sospechosos de una IP con LLM.
        El LLM actúa como agente de decisión inteligente para determinar si bloquear la IP
        basándose en el patrón completo de comportamiento.
        
        Args:
            batch_summary: Resumen del batch con:
                - ip: IP address
                - total_logs: Número de logs en el batch
                - threat_types: Dict con tipos de amenazas y sus conteos
                - time_span_seconds: Tiempo que abarca el batch
                - sample_logs: Lista de 3-5 logs de muestra (más recientes)
                - severity_ratio: Ratio de logs con severidad alta
                - unique_threat_types: Número de tipos de amenazas diferentes
        
        Returns:
            Dict con decision, action, reason, confidence, threat_type
        """
        start_time = time.time()
        
        if not self.enabled:
            # Fallback: análisis heurístico si LLM no está disponible
            return {
                "success": True,
                "analyzed": False,
                "decision": "block_ip" if batch_summary.get('unique_threat_types', 0) >= 2 else "monitor",
                "action": "block_ip" if batch_summary.get('unique_threat_types', 0) >= 2 else "monitor",
                "reason": "LLM no disponible, usando heurística",
                "confidence": 0.7,
                "analysis_time_ms": 0
            }
        
        try:
            # Preparar prompt para análisis de batch
            prompt = self._build_batch_analysis_prompt(batch_summary)
            
            # Analizar con LLM
            response = self.model.generate_content(prompt)
            response_text = response.text
            
            # Parsear respuesta
            analysis = self._parse_batch_llm_response(response_text, batch_summary)
            
            # Calcular tiempo
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Actualizar métricas
            with self.metrics_lock:
                self.metrics['total_analyses'] += 1
                self.metrics['total_time_ms'] += elapsed_ms
                self.metrics['avg_time_ms'] = self.metrics['total_time_ms'] / self.metrics['total_analyses']
                self.metrics['max_time_ms'] = max(self.metrics['max_time_ms'], elapsed_ms)
                self.metrics['min_time_ms'] = min(self.metrics['min_time_ms'], elapsed_ms)
            
            return {
                "success": True,
                "analyzed": True,
                "decision": analysis.get('decision', 'monitor'),
                "action": analysis.get('action', 'monitor'),
                "threat_type": analysis.get('threat_type', 'MULTIPLE_ATTACKS'),
                "reason": analysis.get('reason', ''),
                "confidence": analysis.get('confidence', 0.8),
                "severity": analysis.get('severity', 'high'),
                "analysis_time_ms": round(elapsed_ms, 2)
            }
            
        except Exception as e:
            logger.error(f"Error en análisis LLM de batch: {e}", exc_info=True)
            with self.metrics_lock:
                self.metrics['errors'] += 1
            
            # Fallback: decidir basándose en criterios heurísticos
            unique_threats = batch_summary.get('unique_threat_types', 0)
            severity_ratio = batch_summary.get('severity_ratio', 0)
            
            return {
                "success": True,
                "analyzed": False,
                "decision": "block_ip" if (unique_threats >= 2 or severity_ratio >= 0.5) else "monitor",
                "action": "block_ip" if (unique_threats >= 2 or severity_ratio >= 0.5) else "monitor",
                "reason": f"Fallback heurístico: {unique_threats} tipos de amenazas, ratio severidad={severity_ratio:.2f}",
                "confidence": 0.6,
                "analysis_time_ms": round((time.time() - start_time) * 1000, 2)
            }
    
    def _build_batch_analysis_prompt(self, batch_summary: Dict[str, Any]) -> str:
        """Construye el prompt para análisis de batch completo"""
        ip = batch_summary.get('ip', 'unknown')
        total_logs = batch_summary.get('total_logs', 0)
        threat_types = batch_summary.get('threat_types', {})
        time_span = batch_summary.get('time_span_seconds', 0)
        severity_ratio = batch_summary.get('severity_ratio', 0)
        unique_threats = batch_summary.get('unique_threat_types', 0)
        sample_logs = batch_summary.get('sample_logs', [])
        
        # Formatear tipos de amenazas
        threat_types_text = "\n".join([f"  - {threat}: {count} ocurrencias" for threat, count in threat_types.items()])
        
        # Formatear logs de muestra (máximo 5)
        sample_text = ""
        for i, log_sample in enumerate(sample_logs[:5], 1):
            uri = log_sample.get('uri', '')[:100]
            method = log_sample.get('method', 'GET')
            threat = log_sample.get('threat_type', 'UNKNOWN')
            sample_text += f"\n  {i}. {method} {uri} → {threat}"
        
        time_window = f"{time_span:.0f} segundos" if time_span < 60 else f"{time_span/60:.1f} minutos"
        
        # Información sobre bloqueos WAF
        waf_blocked_count = batch_summary.get('waf_blocked_count', 0)
        not_blocked_count = batch_summary.get('not_blocked_count', 0)
        waf_blocked_ratio = batch_summary.get('waf_blocked_ratio', 0)
        
        waf_info = f"""
- Logs bloqueados por WAF (403): {waf_blocked_count} ({waf_blocked_ratio:.1%})
- Logs NO bloqueados por WAF: {not_blocked_count} ({1-waf_blocked_ratio:.1%})
  ⚠️ IMPORTANTE: Los ataques NO bloqueados por WAF son más peligrosos (bypass de protección)
        """
        
        prompt = f"""
Eres un experto analista de seguridad SOC. Analiza este patrón de comportamiento sospechoso de una IP
y decide si debe ser BLOQUEADA automáticamente con DURACIÓN INTELIGENTE.

RESUMEN DEL BATCH:
- IP: {ip}
- Total de logs sospechosos: {total_logs}
- Ventana de tiempo: {time_window}
- Tipos de amenazas detectados: {unique_threats}
- Ratio de severidad alta: {severity_ratio:.1%}
{waf_info}

TIPOS DE AMENAZAS ENCONTRADOS:
{threat_types_text if threat_types_text else "  - No específico"}

LOGS DE MUESTRA (más recientes):
{sample_text if sample_text else "  - Sin logs de muestra"}

ANÁLISIS REQUERIDO:
Debes analizar el patrón COMPLETO de comportamiento y decidir:

1. **¿BLOQUEAR O MONITOREAR?**
   - BLOQUEAR si: Múltiples tipos de ataques diferentes, O muchos ataques en poco tiempo, O ataques NO bloqueados por WAF (más peligrosos - bypass de protección)
   - MONITOREAR si: Patrón sospechoso pero no concluyente, pocos ataques del mismo tipo, o solo intentos bloqueados por WAF

2. **DURACIÓN DEL BLOQUEO** (si decides bloquear):
   - Escaneos normales/múltiples ataques no bloqueados por WAF: 1 hora (3600 segundos)
   - Escaneos abusivos/múltiples tipos de ataques: 1 día (86400 segundos)  
   - Ataques muy agresivos/sistemáticos desde múltiples endpoints: 1 día (86400 segundos)
   - Ataques coordinados desde múltiples IPs simultáneas: 1 día (86400 segundos)

CONTEXTO IMPORTANTE:
- Ataques NO bloqueados por WAF son MÁS PELIGROSOS (bypass de protección) → bloqueo más justificado
- Múltiples tipos de ataques = escaneo/exploit sistemático (más grave) → duración más larga
- Ataques en corto tiempo = automatización (más grave) → duración más larga
- Considera la gravedad y el patrón para decidir duración apropiada

DURACIÓN DEL BLOQUEO (si decides block_ip):
- Escaneos normales/múltiples ataques no bloqueados por WAF: 1 hora (3600 segundos)
- Escaneos abusivos desde múltiples endpoints: 1 día (86400 segundos)
- Ataques muy agresivos/sistemáticos: 1 día (86400 segundos)
- Casos especiales: decide según la gravedad (mínimo 1 hora, máximo 7 días)

Responde SOLO en formato JSON válido (sin markdown, sin texto adicional):
{{
    "decision": "block_ip|monitor",
    "action": "block_ip|monitor",
    "threat_type": "MULTIPLE_ATTACKS|XSS|SQLI|PATH_TRAVERSAL|SCAN_PROBE|etc",
    "severity": "high|medium|low",
    "block_duration_seconds": 3600,
    "reason": "Explicación breve de la decisión y duración elegida (máximo 200 caracteres)",
    "confidence": 0.0-1.0
}}

IMPORTANTE: 
- Si decides "block_ip", DEBES incluir "block_duration_seconds" con la duración en segundos
- Analiza el patrón completo: múltiples tipos de ataques, frecuencia, severidad, si fueron bloqueados por WAF o no
- Para escaneos desde múltiples IPs simultáneos (ataques coordinados), usa duración más larga (1 día)
- Sé preciso y solo bloquea si hay evidencia clara de comportamiento malicioso
"""
        return prompt
    
    def analyze_time_window_batch(self, window_summary: Dict[str, Any], 
                                   baseline_paths: Optional[set] = None) -> Dict[str, Any]:
        """
        Analiza una ventana temporal de logs como un analista SOC experto.
        Detecta ataques distribuidos, escaneos coordinados, bypass de firmas, etc.
        
        Args:
            window_summary: Resumen de la ventana temporal construido por TimeWindowBatchAnalyzer
            baseline_paths: Set de paths válidos conocidos del sitio (opcional)
            
        Returns:
            Dict con decisiones de bloqueo/monitoreo de IPs
        """
        start_time = time.time()
        
        if not self.enabled or not self.model:
            logger.warning("LLM no disponible para análisis de ventana temporal")
            return {
                "success": True,
                "analyzed": False,
                "ips_to_block": [],
                "ips_to_monitor": [],
                "reasoning": "LLM no disponible",
                "confidence": 0.5
            }
        
        try:
            # Construir prompt como analista SOC senior (con baseline)
            prompt = self._build_soc_level_prompt(window_summary, baseline_paths=baseline_paths)
            
            # Analizar con LLM
            response = self.model.generate_content(prompt)
            response_text = response.text
            
            # Parsear respuesta
            analysis = self._parse_window_llm_response(response_text, window_summary)
            
            # Calcular tiempo
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Actualizar métricas
            with self.metrics_lock:
                self.metrics['total_analyses'] += 1
                self.metrics['total_time_ms'] += elapsed_ms
                self.metrics['avg_time_ms'] = self.metrics['total_time_ms'] / self.metrics['total_analyses']
                self.metrics['max_time_ms'] = max(self.metrics['max_time_ms'], elapsed_ms)
                self.metrics['min_time_ms'] = min(self.metrics['min_time_ms'], elapsed_ms)
            
            logger.info(f"🧠 Análisis SOC de ventana temporal completado en {elapsed_ms:.0f}ms: "
                       f"{len(analysis.get('ips_to_block', []))} IPs a bloquear, "
                       f"{len(analysis.get('ips_to_monitor', []))} IPs a monitorear")
            
            return {
                "success": True,
                "analyzed": True,
                "ips_to_block": analysis.get('ips_to_block', []),
                "ips_to_monitor": analysis.get('ips_to_monitor', []),
                "attack_patterns_detected": analysis.get('attack_patterns_detected', []),
                "reasoning": analysis.get('reasoning', ''),
                "confidence": analysis.get('confidence', 0.8),
                "analysis_time_ms": round(elapsed_ms, 2)
            }
            
        except Exception as e:
            logger.error(f"Error en análisis LLM de ventana temporal: {e}", exc_info=True)
            with self.metrics_lock:
                self.metrics['errors'] += 1
            
            # Fallback: usar heurísticas simples
            return self._fallback_window_analysis(window_summary)
    
    def _build_soc_level_prompt(self, window_summary: Dict[str, Any], 
                                 baseline_paths: Optional[set] = None) -> str:
        """
        Construye un prompt como si fuera un analista SOC senior.
        Incluye contexto completo: IPs, endpoints, patrones, timing, etc.
        Ahora también incluye información del baseline de URLs válidas.
        """
        total_logs = window_summary.get('total_logs', 0)
        unique_ips = window_summary.get('unique_ips', 0)
        unique_endpoints = window_summary.get('unique_endpoints', 0)
        time_span = window_summary.get('time_span_formatted', '0s')
        threat_types_global = window_summary.get('threat_types_global', {})
        suspicious_ips = window_summary.get('suspicious_ips', [])
        distributed_attacks = window_summary.get('distributed_attacks', [])
        scan_patterns = window_summary.get('scan_patterns', [])
        
        # Formatear tipos de amenazas globales
        threat_types_text = "\n".join([f"  - {threat}: {count} ocurrencias" 
                                      for threat, count in sorted(threat_types_global.items(), 
                                                                 key=lambda x: x[1], reverse=True)])
        
        # Formatear IPs sospechosas
        suspicious_ips_text = ""
        for ip_data in suspicious_ips[:15]:  # Máximo 15 IPs para no saturar el prompt
            ip = ip_data['ip']
            total = ip_data['total_logs']
            threats = ip_data['unique_threat_types']
            severity_ratio = ip_data['severity_ratio']
            endpoints = ip_data['unique_endpoints']
            sample_endpoints = ip_data.get('sample_endpoints', [])[:3]
            
            suspicious_ips_text += f"\n  • {ip}:"
            suspicious_ips_text += f"\n    - {total} logs, {threats} tipos de amenazas"
            suspicious_ips_text += f"\n    - Ratio severidad alta: {severity_ratio:.1%}"
            suspicious_ips_text += f"\n    - {endpoints} endpoints diferentes"
            if sample_endpoints:
                suspicious_ips_text += f"\n    - Ejemplos: {', '.join(sample_endpoints[:3])}"
        
        # Formatear ataques distribuidos
        distributed_text = ""
        for attack in distributed_attacks[:10]:  # Máximo 10
            endpoint = attack['endpoint'][:80]  # Truncar si es muy largo
            ips_count = attack['attacking_ips']
            requests = attack['total_requests']
            threats = list(attack['threat_types'].keys())[:3]
            
            distributed_text += f"\n  • {endpoint}: {ips_count} IPs, {requests} requests, amenazas: {', '.join(threats)}"
        
        # Formatear patrones de escaneo
        scan_text = ""
        for scan in scan_patterns[:10]:  # Máximo 10
            ip = scan['ip']
            endpoints = scan['endpoints_scanned']
            requests = scan['total_requests']
            time_span_scan = scan['time_span']
            time_formatted = f"{time_span_scan:.0f}s" if time_span_scan < 60 else f"{time_span_scan/60:.1f}m"
            
            scan_text += f"\n  • {ip}: {endpoints} endpoints en {time_formatted} ({requests} requests)"
        
        # Información del baseline
        baseline_info = ""
        if baseline_paths:
            baseline_sample = list(baseline_paths)[:15]  # Primeros 15 para no saturar
            baseline_info = f"""
BASELINE DEL SITIO (URLs válidas conocidas):
- Total de paths válidos conocidos: {len(baseline_paths)}
- Ejemplos de paths válidos: {', '.join(baseline_sample)}

IMPORTANTE - USAR BASELINE PARA DIFERENCIAR NAVEGACIÓN NORMAL VS ESCANEOS:
1. Si un path está en el baseline → Es navegación normal (considerar como tráfico legítimo)
2. Si un path NO está en el baseline y devuelve 404 → Probable escaneo (SCAN_PROBE)
3. Si un path NO está en el baseline y devuelve 200/301/302 → Puede ser nueva página legítima (monitorear)
4. Combinar con otros factores:
   - Status code (200 = válido, 404 = no existe, 403 = bloqueado)
   - User Agent (navegadores reales vs. bots de escaneo)
   - Timing (navegación normal tiene pausas, escaneos son rápidos)
   - Frecuencia (muchos endpoints diferentes rápidamente = escaneo)

"""
        else:
            baseline_info = "\n⚠️ BASELINE NO DISPONIBLE - Usar criterios generales para detectar escaneos\n"
        
        prompt = f"""
Eres un analista SOC senior con 10+ años de experiencia analizando tráfico web y detectando amenazas avanzadas.

{baseline_info}

VISTA GENERAL DEL TRÁFICO (última ventana temporal):
- Total de requests analizados: {total_logs}
- IPs únicas involucradas: {unique_ips}
- Endpoints únicos accedidos: {unique_endpoints}
- Ventana temporal: {time_span}

TIPOS DE AMENAZAS DETECTADAS GLOBALMENTE:
{threat_types_text if threat_types_text else "  - Ninguna amenaza específica detectada"}

IPs SOSPECHOSAS (comportamiento anómalo):
{suspicious_ips_text if suspicious_ips_text else "  - Ninguna IP sospechosa identificada"}

ATAQUES DISTRIBUIDOS (múltiples IPs coordinadas):
{distributed_text if distributed_text else "  - No se detectaron ataques distribuidos evidentes"}

PATRONES DE ESCANEO (reconocimiento sistemático):
{scan_text if scan_text else "  - No se detectaron patrones de escaneo evidentes"}

ANÁLISIS REQUERIDO (como analista SOC experto):
1. **Navegación Normal vs. Escaneo**: 
   - ¿Los paths están en el baseline? → Navegación normal
   - ¿Paths desconocidos con 404? → Escaneo
   - ¿Múltiples 404s rápidos? → Escaneo agresivo
   - ¿Status codes consistentes con navegación normal? → Considerar contexto
2. **Ataques Distribuidos**: ¿Ves múltiples IPs coordinadas atacando el mismo endpoint/patrón? Esto indica botnet o ataque coordinado.
3. **Escaneo Sistemático**: ¿Hay IPs escaneando múltiples endpoints de forma sistemática (especialmente si NO están en el baseline)? Esto es reconocimiento previo a explotación.
4. **Bypass de Firmas**: ¿Hay variaciones/ofuscación de payloads conocidos? Patrones evasivos que evaden detección básica.
5. **Progresión de Ataque**: ¿Hay evolución de reconocimiento (404s) a explotación (XSS/SQLI)? Esto indica ataque activo.
6. **Amenazas OWASP**: Clasifica según OWASP Top 10 2021 (A01-A10).

CRITERIOS PARA BLOQUEAR IPs:
- ✅ BLOQUEAR SI:
  1. **Escaneo Agresivo**: >10 endpoints diferentes en < 2 minutos, especialmente si devuelven 404 (paths no existen según baseline) → BLOQUEAR INMEDIATAMENTE
  2. **Múltiples SCAN_PROBE**: >15 requests clasificados como SCAN_PROBE desde la misma IP → BLOQUEAR (escaneo sistemático)
  3. **Ataque Distribuido**: Múltiples IPs coordinadas atacando el mismo endpoint/patrón → BLOQUEAR TODAS
  4. **Múltiples Tipos de Amenaza**: >2 tipos diferentes de amenazas (SQLI, XSS, PATH_TRAVERSAL, etc.) → BLOQUEAR
  5. **Alta Frecuencia de Amenazas**: >5 amenazas de alta severidad o >10 amenazas totales en ventana temporal → BLOQUEAR
- ⚠️ MONITOREAR SI: Comportamiento sospechoso pero no concluyente (1-2 amenazas aisladas, pocos endpoints)

REGLA ESPECIAL PARA ESCANEOS:
- Si una IP tiene >10 endpoints diferentes con mayoría de 404/301 (paths no válidos según baseline) → Es escaneo agresivo → BLOQUEAR
- Los escaneos de WordPress (wp-admin, wp-content, wp-includes) con 404 son claramente maliciosos → BLOQUEAR
- NO ser conservador con escaneos obvios - los escaneos NO son tráfico legítimo

Responde SOLO en formato JSON válido (sin markdown, sin texto adicional):
{{
    "ips_to_block": ["ip1", "ip2"],
    "ips_to_monitor": ["ip3"],
    "attack_patterns_detected": ["distributed_attack", "systematic_scan", "signature_bypass"],
    "confidence": 0.0-1.0,
    "reasoning": "Explicación detallada como analista SOC (máximo 500 caracteres): ¿Por qué estas IPs deben bloquearse? ¿Qué patrones detectaste?"
}}

IMPORTANTE: 
- Para ESCANEOS AGRESIVOS (>10 endpoints diferentes con 404): BLOQUEAR sin dudar
- Para ataques activos (SQLI, XSS, etc.): BLOQUEAR inmediatamente
- Ser conservador SOLO con tráfico que podría ser legítimo (navegación normal con paths válidos)
"""
        return prompt
    
    def _parse_window_llm_response(self, response_text: str, window_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Parsea la respuesta del LLM para análisis de ventana temporal"""
        try:
            # Limpiar respuesta (remover markdown si existe)
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            # Parsear JSON
            import json
            parsed = json.loads(cleaned_text)
            
            # Validar estructura
            ips_to_block = parsed.get('ips_to_block', [])
            if not isinstance(ips_to_block, list):
                ips_to_block = []
            
            ips_to_monitor = parsed.get('ips_to_monitor', [])
            if not isinstance(ips_to_monitor, list):
                ips_to_monitor = []
            
            attack_patterns = parsed.get('attack_patterns_detected', [])
            if not isinstance(attack_patterns, list):
                attack_patterns = []
            
            confidence = float(parsed.get('confidence', 0.8))
            confidence = max(0.0, min(1.0, confidence))  # Asegurar rango válido
            
            reasoning = parsed.get('reasoning', '')
            
            return {
                'ips_to_block': ips_to_block,
                'ips_to_monitor': ips_to_monitor,
                'attack_patterns_detected': attack_patterns,
                'confidence': confidence,
                'reasoning': reasoning
            }
            
        except Exception as e:
            logger.error(f"Error parseando respuesta LLM de ventana temporal: {e}. Respuesta: {response_text[:200]}")
            # Fallback a análisis heurístico
            return self._fallback_window_analysis(window_summary)
    
    def analyze_dashboard_scan(self, suspicious_ips: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analiza logs recientes como un analista humano mirando el dashboard.
        Hace un 'paneo rápido' visual y decide qué bloquear de forma inteligente.
        
        Args:
            suspicious_ips: Lista de IPs sospechosas con resumen de actividad reciente
        
        Returns:
            Dict con decisiones de bloqueo
        """
        start_time = time.time()
        
        if not self.enabled or not self.model:
            logger.warning("LLM no disponible para análisis de paneo rápido")
            return {
                "success": True,
                "analyzed": False,
                "ips_to_block": []
            }
        
        try:
            prompt = self._build_dashboard_scan_prompt(suspicious_ips)
            
            logger.info(f"🤖 Consultando LLM para paneo rápido tipo dashboard ({len(suspicious_ips)} IPs sospechosas)...")
            
            response = self.model.generate_content(prompt)
            response_text = response.text if hasattr(response, 'text') else str(response)
            
            result = self._parse_dashboard_scan_response(response_text, suspicious_ips)
            result['success'] = True
            result['analyzed'] = True
            
            latency = (time.time() - start_time) * 1000
            self.metrics['llm_analyses'] += 1
            self.metrics['llm_latency_ms'].append(latency)
            
            logger.info(f"✅ LLM completó paneo rápido en {latency:.0f}ms: {len(result.get('ips_to_block', []))} IPs a bloquear")
            
            return result
        
        except Exception as e:
            logger.error(f"❌ Error en análisis de paneo rápido: {e}", exc_info=True)
            self.metrics['errors'] += 1
            return {
                "success": False,
                "analyzed": False,
                "ips_to_block": []
            }
    
    def _build_dashboard_scan_prompt(self, suspicious_ips: List[Dict[str, Any]]) -> str:
        """
        Construye prompt como si fuera un analista humano mirando el dashboard rápidamente.
        """
        prompt = f"""Eres un analista de seguridad SOC experto. Acabas de hacer un PANEO RÁPIDO del dashboard
y ves los siguientes logs sospechosos de las últimas actividades (últimos 3 minutos).

Tu tarea: Mirar RÁPIDAMENTE como si fueras un humano, identificar patrones obvios y decidir QUÉ BLOQUEAR.

PATRÓN 1: ESCANEOS REPETIDOS
- Misma IP escaneando múltiples endpoints (.env, .git, /wp-, /admin, etc.)
- Múltiples IPs escaneando los mismos endpoints (ataque coordinado)

PATRÓN 2: BYPASS DE FIRMAS (WAF NO BLOQUEÓ PERO DEBERÍA)
- Ataques detectados (PATH_TRAVERSAL, XSS, SQLI, etc.) pero status != 403
- Estos son críticos porque el WAF falló

PATRÓN 3: ESCANEO AGRESIVO
- Muchos bloqueos WAF (403) de la misma IP = escaneo sistemático

IPs SOSPECHOSAS DETECTADAS:
"""
        
        for i, ip_data in enumerate(suspicious_ips, 1):
            ip = ip_data['ip']
            total = ip_data['total_requests']
            endpoints = ip_data['unique_endpoints']
            bypass = ip_data['bypass_detected']
            waf_blocked = ip_data['waf_blocked']
            threats = ip_data.get('threat_types', {})
            scans = ip_data.get('scan_patterns', [])
            samples = ip_data.get('sample_logs', [])[:5]  # Primeros 5 logs
            
            threats_str = ", ".join([f"{k}({v})" for k, v in threats.items()])
            scans_str = ", ".join(scans[:3]) if scans else "ninguno"
            
            prompt += f"""
IP {i}: {ip}
  • Total requests: {total}
  • Endpoints únicos: {endpoints}
  • BYPASS detectados: {bypass} (ataques que pasaron WAF pero deberían estar bloqueados)
  • Bloqueos WAF (403): {waf_blocked}
  • Tipos de amenazas: {threats_str or "ninguno"}
  • Patrones de escaneo: {scans_str}
  
  Muestra de logs recientes:
"""
            for log in samples:
                timestamp = log.get('timestamp', 'N/A')
                uri = log.get('uri', '')
                status = log.get('status', 200)
                threat = log.get('threat_type', 'NONE')
                method = log.get('method', 'GET')
                
                # Marcar si es bypass (threat != NONE pero status != 403)
                bypass_mark = "⚠️ BYPASS" if threat != 'NONE' and status != 403 else ""
                
                prompt += f"    - {method} {uri} → {status} [{threat}] {bypass_mark}\n"
        
        prompt += """

DECISIÓN REQUERIDA:
Como analista experto mirando el dashboard, BLOQUEA solo lo que tiene sentido:

✅ BLOQUEAR INMEDIATAMENTE si:
  1. BYPASS claro: 2+ ataques detectados (PATH_TRAVERSAL, XSS, SQLI, etc.) que pasaron WAF (status != 403)
  2. Escaneo sistemático: 5+ endpoints diferentes escaneados (ej: .env, .git, /wp-, /admin)
  3. Escaneo coordinado: Múltiples IPs escaneando los mismos endpoints sospechosos
  4. Escaneo agresivo: 3+ bloqueos WAF (403) indican escaneo sistemático

❌ NO BLOQUEAR si:
  - Solo tráfico normal (navegación legítima)
  - Pocos requests sin patrones claros
  - Solo 404s normales (sin patrones de escaneo)

DURACIÓN DEL BLOQUEO:
- Escaneos normales / bypasses menores: 1 hora (3600 segundos)
- Escaneos agresivos / múltiples bypasses: 1 día (86400 segundos)
- Ataques coordinados / bypasses críticos: 1 día (86400 segundos)

Responde SOLO en formato JSON válido (sin markdown, sin texto adicional):
{
    "ips_to_block": [
        {
            "ip": "YOUR_IP_ADDRESS",
            "block_duration_seconds": 3600,
            "reason": "Bypass detectado: 3 ataques PATH_TRAVERSAL pasaron WAF"
        }
    ],
    "reasoning": "Resumen breve: Detecté X bypasses, Y escaneos sistemáticos, Z ataques coordinados"
}

IMPORTANTE:
- Sé preciso: solo bloquea si hay evidencia clara de comportamiento malicioso
- Prioriza bypasses (son críticos porque el WAF falló)
- Considera el contexto completo, no solo números
"""
        return prompt
    
    def _parse_dashboard_scan_response(self, response_text: str, suspicious_ips: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parsea la respuesta del LLM para análisis de paneo rápido"""
        try:
            # Limpiar respuesta
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            # Parsear JSON
            import json
            parsed = json.loads(cleaned_text)
            
            ips_to_block = parsed.get('ips_to_block', [])
            if not isinstance(ips_to_block, list):
                ips_to_block = []
            
            reasoning = parsed.get('reasoning', 'Análisis de paneo rápido')
            
            return {
                "ips_to_block": ips_to_block,
                "reasoning": reasoning,
                "confidence": 0.8
            }
        
        except Exception as e:
            logger.error(f"Error parseando respuesta LLM de paneo rápido: {e}. Respuesta: {response_text[:200]}")
            return {
                "ips_to_block": [],
                "reasoning": "Error parseando respuesta",
                "confidence": 0.0
            }
    
    def analyze_episode(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza un episodio (solo se llama si decision = UNCERTAIN).
        Input: JSON estructurado del episodio (no logs crudos).
        
        Args:
            episode: Episodio con features agregadas
            
        Returns:
            Dict con label, confidence, reasoning, rule_candidate
        """
        start_time = time.time()
        
        if not self.enabled or not self.model:
            logger.warning("LLM no disponible para análisis de episodio")
            return {
                "success": False,
                "analyzed": False,
                "label": "ALLOW",
                "confidence": 0.5,
                "reasoning": "LLM no disponible"
            }
        
        try:
            prompt = self._build_episode_prompt(episode)
            
            logger.info(f"🤖 Consultando LLM para episodio UNCERTAIN: IP={episode.get('src_ip')}, "
                       f"requests={episode.get('total_requests', 0)}")
            
            response = self.model.generate_content(prompt)
            response_text = response.text if hasattr(response, 'text') else str(response)
            
            result = self._parse_episode_response(response_text, episode)
            result['success'] = True
            result['analyzed'] = True
            
            latency = (time.time() - start_time) * 1000
            self.metrics['llm_analyses'] += 1
            self.metrics['llm_latency_ms'].append(latency)
            
            logger.info(f"✅ LLM analizó episodio en {latency:.0f}ms: label={result.get('label')}, "
                       f"confidence={result.get('confidence', 0):.2f}")
            
            return result
        
        except Exception as e:
            logger.error(f"❌ Error en análisis de episodio: {e}", exc_info=True)
            self.metrics['errors'] += 1
            return {
                "success": False,
                "analyzed": False,
                "label": "ALLOW",
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}"
            }
    
    def _build_episode_prompt(self, episode: Dict[str, Any]) -> str:
        """
        Construye prompt con features del episodio (no logs crudos).
        El LLM recibe un resumen estructurado, no logs individuales.
        MEJORADO: Ahora incluye contexto de detecciones avanzadas (zero-day, ofuscación, DDoS).
        """
        import json
        
        src_ip = episode.get('src_ip', 'unknown')
        total_requests = episode.get('total_requests', 0)
        unique_uris = episode.get('unique_uris', 0)
        request_rate = episode.get('request_rate', 0)
        status_ratio = episode.get('status_code_ratio', {})
        presence_flags = episode.get('presence_flags', {})
        path_entropy = episode.get('path_entropy_avg', 0)
        threat_types = episode.get('threat_types', {})
        sample_uris = episode.get('sample_uris', [])[:5]
        
        # Formatear threat types
        threat_types_text = ", ".join([f"{k}({v})" for k, v in threat_types.items()]) if threat_types else "ninguno"
        
        # Formatear presence flags activos
        active_flags = [flag for flag, active in presence_flags.items() if active]
        flags_text = ", ".join(active_flags) if active_flags else "ninguno"
        
        # NUEVO: Obtener análisis de inteligencia si existe
        intelligence = episode.get('intelligence_analysis', {})
        
        # Asegurar que intelligence sea un diccionario (puede ser bool o None)
        if not isinstance(intelligence, dict):
            intelligence = {}
        
        # Construir sección de detecciones avanzadas
        intelligence_section = ""
        
        obfuscation = intelligence.get('obfuscation')
        if isinstance(obfuscation, dict) and obfuscation.get('is_obfuscated'):
            obf = obfuscation
            intelligence_section += f"""
⚠️ OFUSCACIÓN DETECTADA:
- Score de ofuscación: {obf.get('score', 0):.2f} (alto = muy ofuscado)
- Entropía promedio: {obf.get('avg_entropy', 0):.2f} bits (alto = aleatorio/ofuscado, normal <5)
- Ratio de encoding: {obf.get('avg_encoded_ratio', 0):.2%} (mucho %XX = encoding para evadir)
- Patrones raros: {obf.get('rare_patterns', 0):.1f} (encoding múltiple, unicode, etc.)
- IMPACTO: Las URIs pueden estar ofuscadas para evadir detección estándar.
  Si hay ofuscación alta pero NO hay threat_types conocidos = posible ataque nuevo/zero-day.
"""
        
        zero_day_risk = intelligence.get('zero_day_risk', {})
        if isinstance(zero_day_risk, dict) and zero_day_risk.get('is_zero_day'):
            zd = zero_day_risk
            intelligence_section += f"""
🚨 POSIBLE ZERO-DAY DETECTADO:
- Score de zero-day: {zd.get('score', 0):.2f} (alto = muy anómalo)
- Features anómalos: {zd.get('deviations', 0)} de {len(zd.get('avg_deviation', 0) or [])} features
- Desviación promedio: {zd.get('avg_deviation', 0):.2f} desviaciones estándar (muy alto)
- Baseline: {zd.get('baseline_episodes', 0)} episodios normales
- IMPACTO CRÍTICO: Comportamiento muy anómalo comparado con baseline normal PERO sin
  threat_types conocidos. Esto sugiere un ataque nuevo no visto antes (zero-day).
  DEBES analizar cuidadosamente: puede ser ataque sofisticado o tráfico legítimo raro.
"""
        
        ddos_risk = intelligence.get('ddos_risk', {})
        if isinstance(ddos_risk, dict) and ddos_risk.get('is_ddos'):
            ddos = ddos_risk
            ddos_details = ddos.get('details', [])
            intelligence_section += f"""
🌐 POSIBLE DDoS DISTRIBUIDO DETECTADO:
- Ataques coordinados: {ddos.get('coordinated_attacks', 0)} grupos
- Episodios sospechosos recientes: {ddos.get('total_suspicious_episodes', 0)}
- IMPACTO: Múltiples IPs diferentes (5+) con mismo comportamiento coordinado en
  ventana temporal corta (<30 segundos). Esto sugiere ataque distribuido coordinado.
"""
            if ddos_details:
                intelligence_section += "- Detalles: " + ", ".join([
                    f"{d.get('ips', 0)} IPs en {d.get('time_span', 0):.1f}s"
                    for d in ddos_details[:2]
                ]) + "\n"
        
        prompt = f"""Eres un analista de seguridad SOC experto. Analiza este EPISODIO de tráfico
y decide si es malicioso o legítimo.

EPISODIO (resumen agregado de {total_requests} requests en ventana temporal):
- IP: {src_ip}
- Total requests: {total_requests}
- Unique URIs: {unique_uris}
- Request rate: {request_rate:.2f} req/s
- Status codes: 2xx={status_ratio.get('2xx', 0):.1%}, 3xx={status_ratio.get('3xx', 0):.1%}, 
  4xx={status_ratio.get('4xx', 0):.1%}, 5xx={status_ratio.get('5xx', 0):.1%}
- Presence flags (indicadores de ataque): {flags_text}
- Path entropy promedio: {path_entropy:.2f} (bajo = patrones repetitivos, alto = variado)
- Threat types detectados: {threat_types_text}
- Sample URIs: {', '.join(sample_uris) if sample_uris else 'ninguno'}{intelligence_section}
CONTEXTO:
Este episodio fue marcado como UNCERTAIN porque el risk_score está entre los umbrales
de bloqueo y permitir. Necesitas decidir si es:
- Ataque real (PATH_TRAVERSAL, XSS, SQLI, SCAN_PROBE, CMD_INJECTION, etc.)
- Tráfico legítimo (ALLOW)

INDICADORES DE ATAQUE:
- Muchos unique URIs + presence flags (.env, ../, wp-) = escaneo
- Alto request rate + muchos 4xx = bot/escaneo
- Bajo path entropy + patrones repetitivos = bot
- Threat types detectados = ataques confirmados
- Ofuscación detectada = posible evasión de detección
- Zero-day risk = ataque nuevo no visto antes

INDICADORES DE TRÁFICO LEGÍTIMO:
- Pocos URIs únicos
- Request rate normal (< 2 req/s)
- Path entropy alto (variedad natural)
- Sin presence flags sospechosos
- Sin ofuscación
- Comportamiento dentro del baseline normal

Responde SOLO en formato JSON válido (sin markdown, sin texto adicional):
{{
    "label": "ALLOW|PATH_TRAVERSAL|XSS|SQLI|SCAN_PROBE|CMD_INJECTION|MULTIPLE_ATTACKS",
    "confidence": 0.0-1.0,
    "reasoning": "Explicación breve de la decisión (máximo 200 caracteres)",
    "rule_candidate": "Regla sugerida para detección futura (opcional)"
}}

IMPORTANTE:
- Si hay zero-day risk: analiza cuidadosamente, puede ser ataque nuevo sofisticado
- Si hay ofuscación: prioriza análisis de URIs, puede evadir detección estándar
- Si hay DDoS risk: considera bloqueo inmediato de IPs coordinadas
- Sé preciso: solo marca como ataque si hay evidencia clara
- Considera el contexto completo: detecciones avanzadas + features básicas
- Si es ambiguo, usa confidence bajo pero label apropiado
"""
        return prompt
    
    def _parse_episode_response(self, response_text: str, episode: Dict[str, Any]) -> Dict[str, Any]:
        """Parsea la respuesta del LLM para análisis de episodio"""
        try:
            # Limpiar respuesta
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            # Parsear JSON
            import json
            parsed = json.loads(cleaned_text)
            
            label = parsed.get('label', 'ALLOW')
            confidence = float(parsed.get('confidence', 0.5))
            reasoning = parsed.get('reasoning', 'Análisis de episodio')
            rule_candidate = parsed.get('rule_candidate')
            
            # Validar label
            valid_labels = ['ALLOW', 'PATH_TRAVERSAL', 'XSS', 'SQLI', 'SCAN_PROBE', 
                          'CMD_INJECTION', 'SSRF', 'MULTIPLE_ATTACKS', 'UNAUTHORIZED_ACCESS']
            if label not in valid_labels:
                logger.warning(f"Label inválido del LLM: {label}, usando ALLOW")
                label = 'ALLOW'
            
            return {
                "label": label,
                "confidence": max(0.0, min(1.0, confidence)),
                "reasoning": reasoning[:500],  # Limitar longitud
                "rule_candidate": rule_candidate
            }
        
        except Exception as e:
            logger.error(f"Error parseando respuesta LLM de episodio: {e}. Respuesta: {response_text[:200]}")
            return {
                "label": "ALLOW",
                "confidence": 0.0,
                "reasoning": "Error parseando respuesta",
                "rule_candidate": None
            }
    
    def _fallback_window_analysis(self, window_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Análisis de fallback usando heurísticas cuando LLM no está disponible"""
        suspicious_ips = window_summary.get('suspicious_ips', [])
        ips_to_block = []
        ips_to_monitor = []
        
        for ip_data in suspicious_ips:
            ip = ip_data['ip']
            severity_ratio = ip_data.get('severity_ratio', 0)
            unique_threat_types = ip_data.get('unique_threat_types', 0)
            total_logs = ip_data.get('total_logs', 0)
            unique_endpoints = ip_data.get('unique_endpoints', 0)
            threat_types = ip_data.get('threat_types', {})
            
            # Contar escaneos (SCAN_PROBE)
            scan_probe_count = threat_types.get('SCAN_PROBE', 0)
            
            # CRITERIOS DE BLOQUEO MUY AGRESIVOS PARA ESCANEOS:
            # 1. Escaneo agresivo: >=5 endpoints diferentes = escaneo sistemático → BLOQUEAR (reducido de 10)
            # 2. Múltiples escaneos: >=5 SCAN_PROBE → BLOQUEAR (reducido de 10)
            # 3. Muchos logs de escaneo: >=8 logs totales con mayoría SCAN_PROBE → BLOQUEAR (reducido de 15)
            # 4. Múltiples tipos de amenaza: >=1 tipo diferente (no NONE) → BLOQUEAR (reducido de 2)
            # 5. Alta severidad: >=3 logs con alta severidad → BLOQUEAR (reducido de 5)
            # 6. Volumen alto: >=10 logs totales → BLOQUEAR (reducido de 20)
            
            should_block = (
                unique_endpoints >= 5 or  # Escaneo agresivo (>=5 endpoints diferentes) - REDUCIDO
                scan_probe_count >= 5 or  # >=5 escaneos detectados - REDUCIDO
                (total_logs >= 8 and scan_probe_count >= total_logs * 0.5) or  # Mayoría de escaneos - REDUCIDO
                unique_threat_types >= 1 or  # Cualquier tipo de amenaza (no NONE) - REDUCIDO
                (total_logs >= 3 and severity_ratio >= 0.4) or  # 40%+ alta severidad - REDUCIDO
                total_logs >= 10  # Volumen alto - REDUCIDO
            )
            
            if should_block:
                ips_to_block.append(ip)
            elif unique_threat_types >= 1 or total_logs >= 5:
                ips_to_monitor.append(ip)
        
        return {
            'ips_to_block': ips_to_block,
            'ips_to_monitor': ips_to_monitor,
            'attack_patterns_detected': ['heuristic_analysis'],
            'confidence': 0.7,
            'reasoning': f'Análisis heurístico de fallback: {len(ips_to_block)} IPs bloqueadas por escaneo agresivo o múltiples amenazas'
        }
    
    def _parse_batch_llm_response(self, response_text: str, batch_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Parsea la respuesta del LLM para análisis de batch"""
        try:
            # Limpiar respuesta (puede venir con markdown)
            cleaned = response_text.strip()
            if cleaned.startswith('```json'):
                cleaned = cleaned[7:]
            if cleaned.startswith('```'):
                cleaned = cleaned[3:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            # Buscar JSON en la respuesta
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                # Validar decision
                decision = result.get('decision', '').lower()
                if decision not in ['block_ip', 'monitor']:
                    decision = 'monitor'  # Por defecto monitorear si la decisión no es clara
                result['decision'] = decision
                result['action'] = decision  # Asegurar que action = decision
                
                # Extraer y validar block_duration_seconds si está presente
                block_duration = result.get('block_duration_seconds', 3600)  # Default: 1 hora
                try:
                    block_duration = int(block_duration)
                    # Validar rango: mínimo 1 hora (3600s), máximo 7 días (604800s)
                    block_duration = max(3600, min(604800, block_duration))
                except (ValueError, TypeError):
                    block_duration = 3600  # Default si no es válido
                result['block_duration_seconds'] = block_duration
                
                return result
        except json.JSONDecodeError as e:
            logger.warning(f"Error parseando JSON del LLM batch: {e}, respuesta: {response_text[:200]}")
        except Exception as e:
            logger.warning(f"Error parseando respuesta LLM batch: {e}")
        
        # Fallback: decidir basándose en criterios heurísticos
        unique_threats = batch_summary.get('unique_threat_types', 0)
        severity_ratio = batch_summary.get('severity_ratio', 0)
        total_logs = batch_summary.get('total_logs', 0)
        
        decision = "block_ip" if (unique_threats >= 2 or total_logs >= 3 or severity_ratio >= 0.5) else "monitor"
        
        return {
            'decision': decision,
            'action': decision,
            'threat_type': 'MULTIPLE_ATTACKS' if unique_threats > 1 else 'UNKNOWN',
            'severity': 'high' if severity_ratio >= 0.5 else 'medium',
            'block_duration_seconds': 3600,  # Default: 1 hora para fallback
            'reason': f'Fallback: {unique_threats} tipos, {total_logs} logs, ratio={severity_ratio:.1%}',
            'confidence': 0.6
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas de rendimiento"""
        with self.metrics_lock:
            return {
                **self.metrics,
                'enabled': self.enabled,
                'model': self.model_name if self.enabled else None,
                'cache_size': len(self.analysis_cache)
            }
    
    def reset_metrics(self):
        """Resetea las métricas"""
        with self.metrics_lock:
            self.metrics = {
                'total_analyses': 0,
                'total_time_ms': 0.0,
                'avg_time_ms': 0.0,
                'max_time_ms': 0.0,
                'min_time_ms': float('inf'),
                'errors': 0,
                'cache_hits': 0
            }



