#!/usr/bin/env python3
"""
Script para ejecutar nmap desde VPN usando métodos alternativos
NO requiere impacket/wmiexec.py directamente
"""

import sys
import os
import argparse
import re
import subprocess
import logging
from io import StringIO

# Configurar logging básico
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def parse_nmap_output(output, target_ip, target_port):
    """Parsea la salida de nmap para determinar el estado del puerto"""
    if not output:
        return "indeterminado"
    
    output_lower = output.lower()
    
    if "host seems down" in output_lower or "0 hosts up" in output_lower:
        return "host_caido"
    
    # Regex para buscar la línea del puerto: "80/tcp   open   http"
    port_line_regex = re.compile(rf"^{target_port}(/tcp|/udp)\s+([a-zA-Z0-9\-\|]+)", re.MULTILINE)
    match = port_line_regex.search(output_lower)
    
    if match:
        state = match.group(2).strip()
        if state == "open":
            return "abierto"
        elif state == "closed":
            return "cerrado"
        elif "filtered" in state:
            return "filtrado"
        else:
            return f"desconocido_{state}"
    
    return "indeterminado"


def find_wmiexec():
    """Busca wmiexec.py en el sistema"""
    import shutil
    
    # Verificar variable de entorno
    wmiexec_path = os.getenv('WMIEXEC_PATH', None)
    if wmiexec_path and os.path.exists(wmiexec_path):
        return wmiexec_path
    
    # Buscar en PATH
    if shutil.which("wmiexec.py"):
        return "wmiexec.py"
    
    # Buscar en ubicaciones comunes
    common_paths = [
        "/irt/proyectos/soar-mcp-server/impacket-master/examples/wmiexec.py",  # Ruta local del zip extraído
        "/usr/local/bin/wmiexec.py",
        "/usr/bin/wmiexec.py",
        "/opt/impacket/examples/wmiexec.py",
        "/usr/share/impacket/examples/wmiexec.py",
        os.path.expanduser("~/.local/bin/wmiexec.py"),
        "/home/ddieser/.local/bin/wmiexec.py"
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Ejecuta Nmap en una máquina Windows remota vía WMI y reporta el estado de un puerto."
    )
    parser.add_argument("windows_ip", help="IP de la máquina Windows donde se ejecutará Nmap.")
    parser.add_argument("final_target_ip", help="IP que escaneará Nmap desde la máquina Windows.")
    parser.add_argument("final_target_port", type=int, help="Puerto que escaneará Nmap desde la máquina Windows.")
    parser.add_argument("-u", "--username", help="Usuario de Windows.", default="")
    parser.add_argument("-p", "--password", help="Contraseña de Windows.", default="")
    parser.add_argument("-d", "--domain", help="Dominio de Windows (usar '.' o nombre del host para cuenta local).", default=".")
    parser.add_argument("-nmap-path", "--nmap-path", help="Ruta completa a nmap.exe en la máquina Windows.", default="C:\\Program Files (x86)\\Nmap\\nmap.exe")
    
    args = parser.parse_args()
    
    # Construir el comando Nmap
    nmap_command = f'"{args.nmap_path}" -Pn -sT -e eth0 -p {args.final_target_port} {args.final_target_ip} --max-retries 1 --host-timeout 60s'
    
    logger.info(f"Preparando para ejecutar en Windows ({args.windows_ip}) el comando: {nmap_command}")
    
    # Intentar encontrar wmiexec.py
    wmiexec_path = find_wmiexec()
    
    if not wmiexec_path:
        logger.error("=" * 60)
        logger.error("ERROR: wmiexec.py no encontrado en el sistema")
        logger.error("=" * 60)
        logger.error("")
        logger.error("SOLUCIÓN: Instalar impacket para obtener wmiexec.py")
        logger.error("")
        logger.error("Opción 1 - Instalar impacket:")
        logger.error("  pip install impacket")
        logger.error("")
        logger.error("Opción 2 - Instalar desde GitHub (offline):")
        logger.error("  git clone https://github.com/fortra/impacket.git")
        logger.error("  cd impacket")
        logger.error("  pip install .")
        logger.error("")
        logger.error("Opción 3 - Configurar ruta manualmente:")
        logger.error("  export WMIEXEC_PATH=/ruta/a/wmiexec.py")
        logger.error("")
        logger.error("NOTA: Si tienes problemas con el proxy, descarga impacket")
        logger.error("      manualmente o usa otro método para instalar.")
        logger.error("")
        print("ERROR: wmiexec_not_found|wmiexec.py no está instalado. Ver logs para instrucciones.")
        sys.exit(1)
    
    logger.info(f"Usando wmiexec.py en: {wmiexec_path}")
    
    try:
        # Usar sys.executable para asegurar que usamos el mismo Python que ejecuta el script
        python_cmd = sys.executable  # python3.11
        
        # Construir argumentos de autenticación
        # wmiexec.py usa formato: [[domain/]username[:password]@]<targetName or address> [comando]
        # Ejemplo: wmiexec.py domain/username:password@YOUR_IP_ADDRESS "comando"
        # O: wmiexec.py username:password@YOUR_IP_ADDRESS "comando"
        target_arg = args.windows_ip
        
        # Construir el target con credenciales si se proporcionan
        if args.username and args.password:
            if args.domain and args.domain != '.':
                target_arg = f"{args.domain}/{args.username}:{args.password}@{args.windows_ip}"
            else:
                target_arg = f"{args.username}:{args.password}@{args.windows_ip}"
        
        wmiexec_cmd = [
            python_cmd,
            wmiexec_path,
            target_arg,
            nmap_command  # El comando se pasa como segundo argumento posicional
        ]
        
        logger.info(f"Ejecutando comando remoto vía WMI...")
        
        # Configurar PYTHONPATH para que encuentre los módulos de impacket
        # Asegurarnos de que impacket-master tenga prioridad sobre cualquier instalación en site-packages
        impacket_dir = os.path.dirname(os.path.dirname(wmiexec_path))  # Directorio impacket-master
        env = os.environ.copy()
        # Forzar el uso de impacket-master primero
        env['PYTHONPATH'] = impacket_dir
        if 'PYTHONPATH' in os.environ:
            # Agregar el PYTHONPATH original después, pero impacket_dir tiene prioridad
            env['PYTHONPATH'] = f"{impacket_dir}:{os.environ['PYTHONPATH']}"
        logger.info(f"PYTHONPATH configurado: {env['PYTHONPATH']}")
        
        # Ejecutar wmiexec
        result = subprocess.run(
            wmiexec_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )
        
        if result.returncode != 0:
            logger.error(f"Error ejecutando wmiexec (código {result.returncode})")
            logger.error(f"Stdout: {result.stdout[:500] if result.stdout else '(vacío)'}")
            logger.error(f"Stderr: {result.stderr[:500] if result.stderr else '(vacío)'}")
            
            # Verificar errores comunes en stdout y stderr
            combined_output = (result.stdout or "") + (result.stderr or "")
            combined_lower = combined_output.lower()
            
            if "STATUS_LOGON_FAILURE" in combined_output or "login failure" in combined_lower:
                print("ERROR: authentication_failed|Fallo de autenticación. Verifica credenciales.")
            elif "timeout" in combined_lower or "timed out" in combined_lower or "Connection error" in combined_output:
                print("ERROR: timeout|Timeout conectando a la máquina remota.")
            elif "network is unreachable" in combined_lower:
                print("ERROR: network_unreachable|No se puede alcanzar la máquina remota.")
            else:
                error_msg = combined_output[:200] if combined_output else "Error desconocido"
                print(f"ERROR: execution_failed|{error_msg}")
            sys.exit(1)
        
        # Parsear salida
        nmap_result = parse_nmap_output(result.stdout, args.final_target_ip, args.final_target_port)
        
        # Imprimir resultado para que el código que llama pueda leerlo
        print(f"RESULTADO: {nmap_result}")
        if result.stdout:
            print(f"SALIDA: {result.stdout[:1000]}")  # Primeros 1000 chars
        
        logger.info(f"Resultado del escaneo: {nmap_result}")
        sys.exit(0)
        
    except subprocess.TimeoutExpired:
        logger.error("Timeout ejecutando wmiexec (120s)")
        print("ERROR: timeout|Timeout ejecutando comando remoto")
        sys.exit(1)
    except FileNotFoundError:
        logger.error(f"wmiexec.py no encontrado en: {wmiexec_path}")
        print("ERROR: wmiexec_not_found|wmiexec.py no encontrado")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        print(f"ERROR: unexpected_error|{str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
