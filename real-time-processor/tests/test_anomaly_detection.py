"""
Tests básicos para Anomaly Detection (Zero-Day Detector)
"""
import unittest
import sys
import os

# Agregar ruta del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from anomaly_detection.zero_day_detector import ZeroDayDetector
    from anomaly_detection.baseline_trainer import BaselineTrainer
    ANOMALY_DETECTION_AVAILABLE = True
except ImportError:
    ANOMALY_DETECTION_AVAILABLE = False


@unittest.skipUnless(ANOMALY_DETECTION_AVAILABLE, "Anomaly Detection no disponible")
class TestZeroDayDetector(unittest.TestCase):
    """Tests para ZeroDayDetector"""
    
    def setUp(self):
        """Setup para cada test"""
        self.detector = ZeroDayDetector(contamination=0.01)
    
    def test_detector_initialization(self):
        """Test de inicialización del detector"""
        self.assertIsNotNone(self.detector)
        if self.detector.enabled:
            self.assertIsNotNone(self.detector.isolation_forest)
            self.assertIsNotNone(self.detector.scaler)
    
    def test_extract_features(self):
        """Test de extracción de features"""
        log = {
            'uri': '/test/path',
            'query_string': 'param=value',
            'user_agent': 'Mozilla/5.0',
            'method': 'GET',
            'status': 200
        }
        
        features = self.detector.extract_features(log)
        
        self.assertEqual(len(features), 15)
        self.assertGreater(features[0], 0)  # URI length
        self.assertGreater(features[1], 0)  # Query length
    
    def test_detect_anomaly_not_trained(self):
        """Test de detección sin entrenamiento (debe retornar que no puede detectar)"""
        log = {
            'uri': '/test/path',
            'query_string': 'param=value',
            'user_agent': 'Mozilla/5.0',
            'method': 'GET',
            'status': 200
        }
        
        result = self.detector.detect_anomaly(log)
        
        self.assertIsNotNone(result)
        self.assertIn('is_zero_day_candidate', result)
        # Si no está entrenado, debería retornar False
        if not self.detector.stats.get('isolation_forest_trained', False):
            self.assertFalse(result.get('is_zero_day_candidate', False))
    
    def test_update_baseline(self):
        """Test de actualización de baseline"""
        log = {
            'uri': '/test/path',
            'user_agent': 'Mozilla/5.0',
            'ip': 'YOUR_IP_ADDRESS'
        }
        
        self.detector.update_baseline('YOUR_IP_ADDRESS', log)
        
        # Verificar que el baseline se creó
        self.assertIn('YOUR_IP_ADDRESS', self.detector.baselines)
        baseline = self.detector.baselines['YOUR_IP_ADDRESS']
        self.assertIn('known_uris', baseline)
        self.assertIn('/test/path', baseline['known_uris'])
    
    def test_get_stats(self):
        """Test de estadísticas"""
        stats = self.detector.get_stats()
        
        self.assertIsNotNone(stats)
        self.assertIn('total_analyses', stats)
        self.assertIn('anomalies_detected', stats)
        self.assertIn('zero_day_candidates', stats)
        self.assertIn('baselines_count', stats)


@unittest.skipUnless(ANOMALY_DETECTION_AVAILABLE, "Anomaly Detection no disponible")
class TestBaselineTrainer(unittest.TestCase):
    """Tests para BaselineTrainer"""
    
    def setUp(self):
        """Setup para cada test"""
        self.detector = ZeroDayDetector(contamination=0.01)
        self.trainer = BaselineTrainer(
            zero_day_detector=self.detector,
            postgres_conn=None  # Sin PostgreSQL para tests
        )
    
    def test_trainer_initialization(self):
        """Test de inicialización del trainer"""
        self.assertIsNotNone(self.trainer)
        self.assertIsNotNone(self.trainer.zero_day_detector)
        self.assertFalse(self.trainer.running)
    
    def test_get_legitimate_traffic_no_postgres(self):
        """Test de obtención de tráfico legítimo sin PostgreSQL"""
        # Sin PostgreSQL, debe retornar lista vacía
        logs = self.trainer._get_legitimate_traffic()
        
        self.assertIsInstance(logs, list)
        self.assertEqual(len(logs), 0)
    
    def test_trainer_start_stop(self):
        """Test de inicio y detención del trainer"""
        self.assertFalse(self.trainer.running)
        
        self.trainer.start()
        self.assertTrue(self.trainer.running)
        self.assertIsNotNone(self.trainer.thread)
        
        self.trainer.stop()
        self.assertFalse(self.trainer.running)


if __name__ == '__main__':
    unittest.main()
