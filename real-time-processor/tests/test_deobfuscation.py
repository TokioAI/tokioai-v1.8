"""
Tests básicos para Deobfuscation Engine
"""
import unittest
import sys
import os

# Agregar ruta del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deobfuscation_engine import DeobfuscationEngine


class TestDeobfuscationEngine(unittest.TestCase):
    """Tests para DeobfuscationEngine"""
    
    def setUp(self):
        """Setup para cada test"""
        self.engine = DeobfuscationEngine(max_depth=5)
    
    def test_basic_deobfuscation(self):
        """Test de desobfuscación básica"""
        # URL encoding
        payload = "%3Cscript%3Ealert('XSS')%3C%2Fscript%3E"
        result = self.engine.deobfuscate(payload)
        
        self.assertTrue(result['is_obfuscated'])
        self.assertIn('URL_ENCODING', result['techniques_detected'])
        self.assertIn('<script>alert(\'XSS\')</script>', result['deobfuscated_variants'])
    
    def test_base64_deobfuscation(self):
        """Test de desobfuscación Base64"""
        # Base64 en atob()
        payload = "atob('PHNjcmlwdD5hbGVydCgnWFNTJyk8L3NjcmlwdD4=')"
        result = self.engine.deobfuscate(payload)
        
        self.assertTrue(result['is_obfuscated'])
        self.assertIn('BASE64', result['techniques_detected'])
    
    def test_html_entities(self):
        """Test de desobfuscación HTML entities"""
        payload = "&lt;script&gt;alert('XSS')&lt;/script&gt;"
        result = self.engine.deobfuscate(payload)
        
        self.assertTrue(result['is_obfuscated'])
        self.assertIn('HTML_ENTITIES', result['techniques_detected'])
    
    def test_unicode_escape(self):
        """Test de desobfuscación Unicode escape"""
        payload = "\\u003cscript\\u003ealert('XSS')\\u003c/script\\u003e"
        result = self.engine.deobfuscate(payload)
        
        self.assertTrue(result['is_obfuscated'])
        self.assertIn('UNICODE_ESCAPE', result['techniques_detected'])
    
    def test_multiple_layers(self):
        """Test de desobfuscación multi-capa"""
        # URL encoding + Base64
        payload = "%61%74%6f%62%28%27%50%48%4e%6a%63%6d%4e%76%62%47%39%77%27%29"
        result = self.engine.deobfuscate(payload)
        
        self.assertTrue(result['is_obfuscated'])
        self.assertGreater(result['obfuscation_layers'], 0)
    
    def test_no_obfuscation(self):
        """Test con payload sin ofuscación"""
        payload = "/normal/path"
        result = self.engine.deobfuscate(payload)
        
        self.assertFalse(result['is_obfuscated'])
        self.assertEqual(len(result['techniques_detected']), 0)
    
    def test_empty_payload(self):
        """Test con payload vacío"""
        payload = ""
        result = self.engine.deobfuscate(payload)
        
        self.assertFalse(result['is_obfuscated'])
        self.assertEqual(result['max_decoded'], "")
    
    def test_stats(self):
        """Test de estadísticas"""
        self.engine.deobfuscate("%3Cscript%3E")
        self.engine.deobfuscate("/normal")
        
        stats = self.engine.get_stats()
        self.assertGreater(stats['total_deobfuscations'], 0)
        self.assertGreater(stats['obfuscation_detected'], 0)


if __name__ == '__main__':
    unittest.main()
