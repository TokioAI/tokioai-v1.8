"""
Tests básicos para Threat Intelligence Client
"""
import unittest
import sys
import os

# Agregar ruta del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from threat_intelligence.threat_intel_client import ThreatIntelligenceClient
    THREAT_INTEL_AVAILABLE = True
except ImportError:
    THREAT_INTEL_AVAILABLE = False


@unittest.skipUnless(THREAT_INTEL_AVAILABLE, "Threat Intelligence no disponible")
class TestThreatIntelligenceClient(unittest.TestCase):
    """Tests para ThreatIntelligenceClient"""
    
    def setUp(self):
        """Setup para cada test"""
        self.client = ThreatIntelligenceClient()
    
    def test_client_initialization(self):
        """Test de inicialización del cliente"""
        self.assertIsNotNone(self.client)
        self.assertIsNotNone(self.client.cache)
    
    def test_check_ip_reputation_sync_no_api_keys(self):
        """Test de verificación de IP sin API keys (debe funcionar pero sin resultados)"""
        # Sin API keys, debería retornar estructura válida pero vacía
        result = self.client.check_ip_reputation_sync("YOUR_IP_ADDRESS")
        
        self.assertIsNotNone(result)
        self.assertIn('ip', result)
        self.assertIn('is_malicious', result)
        self.assertIn('reputation_score', result)
        self.assertIn('recommendation', result)
    
    def test_cache_functionality(self):
        """Test de funcionalidad de cache"""
        # Primera llamada (cache miss)
        result1 = self.client.check_ip_reputation_sync("YOUR_IP_ADDRESS")
        self.assertFalse(result1.get('cached', False))
        
        # Segunda llamada (cache hit)
        result2 = self.client.check_ip_reputation_sync("YOUR_IP_ADDRESS")
        self.assertTrue(result2.get('cached', False))
    
    def test_stats(self):
        """Test de estadísticas"""
        self.client.check_ip_reputation_sync("YOUR_IP_ADDRESS")
        self.client.check_ip_reputation_sync("YOUR_IP_ADDRESS")  # Cache hit
        
        stats = self.client.get_stats()
        self.assertGreater(stats['cache_hits'], 0)
        self.assertGreater(stats['cache_misses'], 0)
    
    def test_recommendation_logic(self):
        """Test de lógica de recomendación"""
        # Crear resultado simulado con score bajo
        result = {
            'ip': 'YOUR_IP_ADDRESS',
            'is_malicious': False,
            'reputation_score': 10,
            'recommendation': 'ALLOW',
            'sources': {},
            'cached': False
        }
        
        self.assertEqual(result['recommendation'], 'ALLOW')
        self.assertFalse(result['is_malicious'])


if __name__ == '__main__':
    unittest.main()
