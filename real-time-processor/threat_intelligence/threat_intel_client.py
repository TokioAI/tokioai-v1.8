"""
Threat Intelligence Integration
Integra múltiples fuentes: AbuseIPDB, VirusTotal, AlienVault OTX
"""
import os
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import requests
from cachetools import TTLCache

logger = logging.getLogger(__name__)


class ThreatIntelligenceClient:
    """
    Cliente unificado para múltiples fuentes de threat intelligence.
    Con cache para evitar rate limits.
    """
    
    def __init__(self):
        self.abuseipdb_api_key = os.getenv('ABUSEIPDB_API_KEY', '')
        self.virustotal_api_key = os.getenv('VIRUSTOTAL_API_KEY', '')
        self.otx_api_key = os.getenv('ALIENVAULT_OTX_API_KEY', '')
        
        # Cache con TTL de 1 hora
        self.cache = TTLCache(maxsize=10000, ttl=3600)
        
        # Stats
        self.stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'abuseipdb_queries': 0,
            'virustotal_queries': 0,
            'otx_queries': 0,
            'known_malicious_ips': 0,
            'errors': 0
        }
    
    async def check_ip_reputation(self, ip: str) -> Dict[str, Any]:
        """
        Verifica reputación de IP en múltiples fuentes.
        
        Args:
            ip: IP a verificar
            
        Returns:
            Dict con:
            - ip: IP verificada
            - is_malicious: Boolean
            - reputation_score: 0-100 (mayor = más maliciosa)
            - sources: Dict con resultados por fuente
            - recommendation: 'BLOCK' | 'ALLOW' | 'MONITOR'
            - cached: Boolean
        """
        # Verificar cache primero
        if ip in self.cache:
            self.stats['cache_hits'] += 1
            result = self.cache[ip]
            result['cached'] = True
            return result
        
        self.stats['cache_misses'] += 1
        
        # Queries paralelas a todas las fuentes
        results = await asyncio.gather(
            self._check_abuseipdb(ip),
            self._check_virustotal(ip),
            self._check_otx(ip),
            return_exceptions=True
        )
        
        abuseipdb_result = results[0] if not isinstance(results[0], Exception) else {}
        vt_result = results[1] if not isinstance(results[1], Exception) else {}
        otx_result = results[2] if not isinstance(results[2], Exception) else {}
        
        # Calcular score de reputación (0-100)
        reputation_score = 0
        sources = {
            'abuseipdb': abuseipdb_result,
            'virustotal': vt_result,
            'otx': otx_result
        }
        
        # AbuseIPDB: 0-100 confidence score
        abuse_score = abuseipdb_result.get('abuseConfidenceScore', 0)
        reputation_score = max(reputation_score, abuse_score)
        
        # VirusTotal: Malicious count (múltiples engines)
        vt_malicious = vt_result.get('malicious', 0)
        if vt_malicious > 0:
            reputation_score = max(reputation_score, min(vt_malicious * 10, 100))
        
        # OTX: Pulse count (indicadores de compromiso)
        otx_pulses = otx_result.get('pulse_count', 0)
        if otx_pulses > 0:
            reputation_score = max(reputation_score, min(otx_pulses * 5, 100))
        
        # Determinar si es maliciosa
        is_malicious = reputation_score >= 80  # Threshold configurable
        
        # Recomendación
        if reputation_score >= 80:
            recommendation = 'BLOCK'
            self.stats['known_malicious_ips'] += 1
        elif reputation_score >= 50:
            recommendation = 'MONITOR'
        else:
            recommendation = 'ALLOW'
        
        result = {
            'ip': ip,
            'is_malicious': is_malicious,
            'reputation_score': reputation_score,
            'sources': sources,
            'recommendation': recommendation,
            'cached': False,
            'timestamp': datetime.now().isoformat()
        }
        
        # Guardar en cache
        self.cache[ip] = result
        
        return result
    
    def check_ip_reputation_sync(self, ip: str) -> Dict[str, Any]:
        """
        Versión síncrona para uso en código no-async.
        Crea un event loop nuevo si es necesario.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.check_ip_reputation(ip))
    
    async def _check_abuseipdb(self, ip: str) -> Dict[str, Any]:
        """Verifica IP en AbuseIPDB"""
        if not self.abuseipdb_api_key:
            return {}
        
        try:
            self.stats['abuseipdb_queries'] += 1
            
            url = 'https://api.abuseipdb.com/api/v2/check'
            headers = {
                'Key': self.abuseipdb_api_key,
                'Accept': 'application/json'
            }
            params = {
                'ipAddress': ip,
                'maxAgeInDays': 90,
                'verbose': ''
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=5)
            response.raise_for_status()
            
            data = response.json().get('data', {})
            
            return {
                'abuseConfidenceScore': data.get('abuseConfidencePercentage', 0),
                'usageType': data.get('usageType', ''),
                'isPublic': data.get('isPublic', False),
                'countryCode': data.get('countryCode', ''),
                'lastReportedAt': data.get('lastReportedAt', '')
            }
        except Exception as e:
            logger.warning(f"Error consultando AbuseIPDB para {ip}: {e}")
            self.stats['errors'] += 1
            return {}
    
    async def _check_virustotal(self, ip: str) -> Dict[str, Any]:
        """Verifica IP en VirusTotal"""
        if not self.virustotal_api_key:
            return {}
        
        try:
            self.stats['virustotal_queries'] += 1
            
            url = f'https://www.virustotal.com/api/v3/ip_addresses/{ip}'
            headers = {
                'x-apikey': self.virustotal_api_key
            }
            
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            
            data = response.json().get('data', {})
            attributes = data.get('attributes', {})
            last_analysis_stats = attributes.get('last_analysis_stats', {})
            
            return {
                'malicious': last_analysis_stats.get('malicious', 0),
                'suspicious': last_analysis_stats.get('suspicious', 0),
                'harmless': last_analysis_stats.get('harmless', 0),
                'undetected': last_analysis_stats.get('undetected', 0),
                'asn': attributes.get('asn', 0),
                'country': attributes.get('country', ''),
                'last_analysis_date': attributes.get('last_analysis_date', 0)
            }
        except Exception as e:
            logger.warning(f"Error consultando VirusTotal para {ip}: {e}")
            self.stats['errors'] += 1
            return {}
    
    async def _check_otx(self, ip: str) -> Dict[str, Any]:
        """Verifica IP en AlienVault OTX"""
        if not self.otx_api_key:
            return {}
        
        try:
            self.stats['otx_queries'] += 1
            
            url = f'https://otx.alienvault.com/api/v1/indicators/IPv4/{ip}/general'
            headers = {
                'X-OTX-API-KEY': self.otx_api_key
            }
            
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            pulse_info = data.get('pulse_info', {})
            
            return {
                'pulse_count': pulse_info.get('count', 0),
                'pulses': pulse_info.get('pulses', [])[:5]  # Top 5
            }
        except Exception as e:
            logger.warning(f"Error consultando OTX para {ip}: {e}")
            self.stats['errors'] += 1
            return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas"""
        return self.stats.copy()
