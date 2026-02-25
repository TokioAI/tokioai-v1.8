#!/usr/bin/env python3
"""
Script para forzar la detección de bypasses directamente
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib.util

# Importar bypass_detector
bypass_spec = importlib.util.spec_from_file_location(
    "bypass_detector",
    "/home/osboxes/SOC-AI-LAB/adaptive-learning/bypass_detector.py"
)
bypass_module = importlib.util.module_from_spec(bypass_spec)
bypass_spec.loader.exec_module(bypass_module)
BypassDetector = bypass_module.BypassDetector

# Importar auto_mitigation
mitigation_spec = importlib.util.spec_from_file_location(
    "auto_mitigation",
    "/home/osboxes/SOC-AI-LAB/adaptive-learning/auto_mitigation.py"
)
mitigation_module = importlib.util.module_from_spec(mitigation_spec)
mitigation_spec.loader.exec_module(mitigation_module)
AutoMitigationSystem = mitigation_module.AutoMitigationSystem

# Importar incident_manager
incident_spec = importlib.util.spec_from_file_location(
    "incident_manager",
    "/home/osboxes/SOC-AI-LAB/incident-management/incident_manager.py"
)
incident_module = importlib.util.module_from_spec(incident_spec)
incident_spec.loader.exec_module(incident_module)
IncidentManager = incident_module.IncidentManager

print("🔍 Forzando detección de bypasses...")
print("=" * 60)

# Detectar bypasses
detector = BypassDetector()
bypasses = detector.detect_bypasses()

print(f"\n✅ Detectados {len(bypasses)} bypasses")

if bypasses:
    mitigation = AutoMitigationSystem()
    incident_mgr = IncidentManager()
    
    for bypass in bypasses:
        print(f"\n📋 Procesando bypass: IP={bypass['ip']}, Tipo={bypass['attack_type']}")
        
        # Guardar bypass
        bypass_id = detector.save_bypass(bypass)
        print(f"   ✅ Bypass guardado: ID {bypass_id}")
        
        # Crear incidente
        incident_id = incident_mgr.create_incident_for_bypass(bypass_id)
        print(f"   ✅ Incidente creado: ID {incident_id}")
        
        # Aplicar auto-mitigación
        result = mitigation.analyze_bypass_and_mitigate(bypass_id)
        if result.get("success"):
            print(f"   ✅ Auto-mitigación exitosa: Regla {result.get('rule_id')} aplicada")
        else:
            print(f"   ⚠️ Error en mitigación: {result.get('error')}")
    
    detector.close()
    mitigation.close()
    incident_mgr.close()
else:
    print("\n⚠️ No se detectaron bypasses")
    print("   Esto puede ser porque:")
    print("   - No hay suficientes logs en la ventana de tiempo")
    print("   - Los logs no tienen el patrón de bypass (bloqueado -> permitido)")
    detector.close()

print("\n" + "=" * 60)
print("✅ Proceso completado")


