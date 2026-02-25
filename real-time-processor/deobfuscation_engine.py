"""
Deobfuscation Engine - Desobfusca payloads antes de análisis ML/LLM
Soporta 10+ técnicas de encoding/obfuscation recursivo
"""
import base64
import urllib.parse
import html
import re
import logging
from typing import Dict, Any, List, Set, Optional
from collections import deque

logger = logging.getLogger(__name__)


class DeobfuscationEngine:
    """
    Pipeline de deobfuscation multi-layer.
    Detecta encoding/obfuscation recursivo hasta 5 niveles.
    """
    
    def __init__(self, max_depth: int = 5):
        """
        Args:
            max_depth: Máxima profundidad de deobfuscation recursivo
        """
        self.max_depth = max_depth
        self.stats = {
            'total_deobfuscations': 0,
            'obfuscation_detected': 0,
            'multi_layer_obfuscation': 0,
            'techniques_found': {}
        }
    
    def deobfuscate(self, payload: str) -> Dict[str, Any]:
        """
        Desobfusca un payload aplicando múltiples técnicas recursivamente.
        
        Args:
            payload: Payload a desobfuscar (URI, query string, body, etc.)
            
        Returns:
            Dict con:
            - original: Payload original
            - deobfuscated_variants: Lista de todas las variantes decodificadas
            - max_decoded: Variante más decodificada (más larga)
            - obfuscation_layers: Número de capas de ofuscación detectadas
            - techniques_detected: Lista de técnicas detectadas
            - is_obfuscated: Boolean indicando si había ofuscación
        """
        if not payload or not isinstance(payload, str):
            return {
                'original': payload,
                'deobfuscated_variants': [payload] if payload else [],
                'max_decoded': payload,
                'obfuscation_layers': 0,
                'techniques_detected': [],
                'is_obfuscated': False
            }
        
        self.stats['total_deobfuscations'] += 1
        
        original = payload
        decoded_variants = [payload]  # Empezar con el original
        
        # Detectar técnicas iniciales
        initial_techniques = self._detect_techniques(original)
        is_obfuscated = len(initial_techniques) > 0
        
        if is_obfuscated:
            self.stats['obfuscation_detected'] += 1
            for technique in initial_techniques:
                self.stats['techniques_found'][technique] = \
                    self.stats['techniques_found'].get(technique, 0) + 1
        
        # Aplicar deobfuscation recursivo
        current_layer = [original]
        
        for depth in range(self.max_depth):
            next_layer = []
            
            for variant in current_layer:
                # Aplicar todas las técnicas de decodificación
                decoded = self._apply_all_techniques(variant)
                
                # Agregar variantes únicas
                if isinstance(decoded, list):
                    next_layer.extend(decoded)
                else:
                    if decoded not in current_layer:
                        next_layer.append(decoded)
            
            # Si no hay cambios, detener
            if not next_layer or set(next_layer) == set(current_layer):
                break
            
            # Si hay múltiples capas, incrementar contador
            if depth > 0:
                self.stats['multi_layer_obfuscation'] += 1
            
            current_layer = next_layer
            decoded_variants.extend(next_layer)
        
        # Eliminar duplicados manteniendo orden
        unique_variants = []
        seen = set()
        for variant in decoded_variants:
            if variant not in seen:
                seen.add(variant)
                unique_variants.append(variant)
        
        # Encontrar la variante más decodificada (más larga generalmente)
        max_decoded = max(unique_variants, key=len) if unique_variants else original
        
        # Contar capas de ofuscación
        obfuscation_layers = len(unique_variants) - 1  # -1 porque el original cuenta
        
        return {
            'original': original,
            'deobfuscated_variants': unique_variants,
            'max_decoded': max_decoded,
            'obfuscation_layers': obfuscation_layers,
            'techniques_detected': initial_techniques,
            'is_obfuscated': is_obfuscated
        }
    
    def _apply_all_techniques(self, text: str) -> List[str]:
        """
        Aplica todas las técnicas de deobfuscation y retorna lista de variantes.
        """
        variants = []
        
        # 1. URL decode (simple y double encoding)
        url_decoded = self._url_decode_recursive(text)
        if url_decoded != text:
            variants.append(url_decoded)
        
        # 2. Base64 decode (atob(), btoa(), base64 en query params)
        base64_variants = self._base64_decode(text)
        variants.extend(base64_variants)
        
        # 3. HTML entities
        html_decoded = html.unescape(text)
        if html_decoded != text:
            variants.append(html_decoded)
        
        # 4. Unicode escape sequences
        unicode_decoded = self._unicode_decode(text)
        if unicode_decoded != text:
            variants.append(unicode_decoded)
        
        # 5. Hex escape sequences
        hex_decoded = self._hex_decode(text)
        if hex_decoded != text:
            variants.append(hex_decoded)
        
        # 6. Octal escape sequences
        octal_decoded = self._octal_decode(text)
        if octal_decoded != text:
            variants.append(octal_decoded)
        
        # 7. JavaScript String.fromCharCode
        charcode_decoded = self._decode_char_codes(text)
        if charcode_decoded != text:
            variants.append(charcode_decoded)
        
        # 8. PHP chr() concatenation
        php_chr_decoded = self._decode_php_chr(text)
        if php_chr_decoded != text:
            variants.append(php_chr_decoded)
        
        # 9. JavaScript escape/unescape
        js_unescaped = self._js_unescape(text)
        if js_unescaped != text:
            variants.append(js_unescaped)
        
        # 10. Mixed encoding (combinaciones)
        mixed_decoded = self._decode_mixed(text)
        if mixed_decoded != text:
            variants.append(mixed_decoded)
        
        return variants if variants else [text]
    
    def _url_decode_recursive(self, text: str, max_iter: int = 3) -> str:
        """URL decode recursivo para manejar double/triple encoding"""
        decoded = text
        for _ in range(max_iter):
            new_decoded = urllib.parse.unquote(decoded)
            if new_decoded == decoded:
                break
            decoded = new_decoded
        return decoded
    
    def _base64_decode(self, text: str) -> List[str]:
        """Decodifica Base64 en múltiples contextos"""
        variants = []
        
        # 1. atob('base64string')
        atob_pattern = r"atob\([\"']([A-Za-z0-9+/=]+)[\"']\)"
        for match in re.finditer(atob_pattern, text):
            try:
                decoded = base64.b64decode(match.group(1)).decode('utf-8', errors='ignore')
                variants.append(text.replace(match.group(0), decoded))
            except:
                pass
        
        # 2. btoa (menos común pero existe)
        btoa_pattern = r"btoa\([\"']([^\"']+)[\"']\)"
        for match in re.finditer(btoa_pattern, text):
            try:
                # btoa es encode, pero a veces se usa mal
                variants.append(text.replace(match.group(0), match.group(1)))
            except:
                pass
        
        # 3. Base64 puro en query params (detectar por patrón)
        base64_pattern = r'[A-Za-z0-9+/]{20,}={0,2}'
        for match in re.finditer(base64_pattern, text):
            b64_str = match.group(0)
            try:
                decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
                if len(decoded) > 5:  # Solo si tiene sentido
                    variants.append(text.replace(b64_str, decoded))
            except:
                pass
        
        return variants
    
    def _unicode_decode(self, text: str) -> str:
        """Decodifica secuencias Unicode escape (\u003c, \U0000003c)"""
        # \uXXXX (4 hex digits)
        def unicode_replace(match):
            try:
                return chr(int(match.group(1), 16))
            except:
                return match.group(0)
        
        decoded = re.sub(r'\\u([0-9a-fA-F]{4})', unicode_replace, text)
        
        # \UXXXXXXXX (8 hex digits)
        def unicode_long_replace(match):
            try:
                return chr(int(match.group(1), 16))
            except:
                return match.group(0)
        
        decoded = re.sub(r'\\U([0-9a-fA-F]{8})', unicode_long_replace, decoded)
        
        return decoded
    
    def _hex_decode(self, text: str) -> str:
        """Decodifica secuencias hex (\x3c, %3c)"""
        # \xXX
        def hex_replace(match):
            try:
                return chr(int(match.group(1), 16))
            except:
                return match.group(0)
        
        decoded = re.sub(r'\\x([0-9a-fA-F]{2})', hex_replace, text)
        return decoded
    
    def _octal_decode(self, text: str) -> str:
        """Decodifica secuencias octal (\074)"""
        def octal_replace(match):
            try:
                return chr(int(match.group(1), 8))
            except:
                return match.group(0)
        
        decoded = re.sub(r'\\([0-7]{1,3})', octal_replace, text)
        return decoded
    
    def _decode_char_codes(self, text: str) -> str:
        """Decodifica String.fromCharCode(60,115,99,...)"""
        pattern = r'String\.fromCharCode\(([0-9,\s]+)\)'
        
        def charcode_replace(match):
            try:
                codes = [int(c.strip()) for c in match.group(1).split(',')]
                decoded = ''.join(chr(c) for c in codes if 0 <= c <= 127)
                return decoded
            except:
                return match.group(0)
        
        return re.sub(pattern, charcode_replace, text)
    
    def _decode_php_chr(self, text: str) -> str:
        """Decodifica PHP chr() concatenation (chr(60).chr(115)...)"""
        pattern = r'chr\((\d+)\)'
        matches = list(re.finditer(pattern, text))
        
        if matches:
            try:
                codes = [int(m.group(1)) for m in matches]
                decoded = ''.join(chr(c) for c in codes if 0 <= c <= 255)
                
                # Reemplazar toda la expresión
                if len(matches) > 1:
                    # Encontrar inicio y fin de la expresión completa
                    start = matches[0].start()
                    end = matches[-1].end()
                    return text[:start] + decoded + text[end:]
                else:
                    return text.replace(matches[0].group(0), decoded)
            except:
                pass
        
        return text
    
    def _js_unescape(self, text: str) -> str:
        """JavaScript unescape() function"""
        try:
            # Simular unescape de JavaScript
            def unescape_replace(match):
                hex_code = match.group(1)
                try:
                    return chr(int(hex_code, 16))
                except:
                    return match.group(0)
            
            decoded = re.sub(r'%u([0-9a-fA-F]{4})', unescape_replace, text)
            decoded = re.sub(r'%([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), decoded)
            return decoded
        except:
            return text
    
    def _decode_mixed(self, text: str) -> str:
        """Intenta decodificar encodings mixtos (combinaciones)"""
        decoded = text
        
        # Aplicar múltiples técnicas en secuencia
        try:
            decoded = urllib.parse.unquote(decoded)
            decoded = html.unescape(decoded)
            # Solo intentar base64 si tiene longitud múltiplo de 4
            if len(decoded) % 4 == 0 and len(decoded) > 4:
                try:
                    decoded = base64.b64decode(decoded).decode('utf-8', errors='ignore')
                except:
                    pass
        except:
            pass
        
        return decoded
    
    def _detect_techniques(self, payload: str) -> List[str]:
        """Identifica técnicas de obfuscación usadas"""
        techniques = []
        
        if re.search(r'%[0-9A-Fa-f]{2}', payload):
            techniques.append('URL_ENCODING')
        
        if re.search(r'atob\(|btoa\(', payload, re.IGNORECASE):
            techniques.append('BASE64')
        
        if re.search(r'&[a-z]+;|&#\d+;|&#x[0-9a-f]+;', payload):
            techniques.append('HTML_ENTITIES')
        
        if re.search(r'\\u[0-9a-fA-F]{4}', payload):
            techniques.append('UNICODE_ESCAPE')
        
        if re.search(r'\\x[0-9a-fA-F]{2}', payload):
            techniques.append('HEX_ESCAPE')
        
        if re.search(r'\\([0-7]{1,3})', payload):
            techniques.append('OCTAL_ESCAPE')
        
        if re.search(r'String\.fromCharCode', payload, re.IGNORECASE):
            techniques.append('CHAR_CODE')
        
        if re.search(r'chr\(', payload, re.IGNORECASE):
            techniques.append('PHP_CHR')
        
        if re.search(r'eval\(|Function\(|setTimeout\(|setInterval\(', payload, re.IGNORECASE):
            techniques.append('DYNAMIC_EXECUTION')
        
        if re.search(r'unescape\(', payload, re.IGNORECASE):
            techniques.append('JS_UNESCAPE')
        
        return techniques
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas de deobfuscation"""
        return self.stats.copy()
