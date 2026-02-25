#!/usr/bin/env python3
"""
TOKIO AI v3.0 - CLI Terminal Interactivo
CLI estilo OpenClaw con libertad total
"""

import asyncio
import sys
import os
from pathlib import Path

# Agregar tokio-core al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tokio_core import get_engine
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


# Colores ANSI
class Colors:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"


async def show_banner(engine):
    """Muestra el banner de inicio"""
    print(Colors.CYAN + """
████████╗ ██████╗ ██╗  ██╗██╗ ██████╗      █████╗ ██╗
   ██╔══╝██╔═══██╗██║ ██╔╝██║██╔═══██╗    ██╔══██╗██║
   ██║   ██║   ██║█████╔╝ ██║██║   ██║    ███████║██║
   ██║   ██║   ██║██╔═██╗ ██║██║   ██║    ██╔══██║██║
   ██║   ╚██████╔╝██║  ██╗██║╚██████╔╝    ██║  ██║██║
   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝     ╚═╝  ╚═╝╚═╝
    """ + Colors.RESET)

    print(Colors.BOLD + "    🤖 Agente Autónomo v3.0" + Colors.RESET)
    print(Colors.GRAY + "    WAF-as-a-Service · AI Security Platform" + Colors.RESET)
    print()

    # Estado del sistema
    tool_count = len(engine.tool_registry.tools)
    resources = list(engine.resources.connectors.keys())

    print(Colors.GREEN + f"    ✅ {tool_count} tools disponibles" + Colors.RESET)
    print(Colors.GREEN + f"    ✅ {len(resources)} recursos conectados: {', '.join(resources)}" + Colors.RESET)
    print(Colors.GREEN + "    ✅ Heartbeat activo (monitor cada 30s)" + Colors.RESET)
    print(Colors.GREEN + "    ✅ Modo: Libre (sin MCP)" + Colors.RESET)
    print()

    print(Colors.GRAY + "    Comandos:" + Colors.RESET)
    print(Colors.GRAY + "    • Hablá naturalmente: " + Colors.CYAN + '"dame los últimos ataques"' + Colors.RESET)
    print(Colors.GRAY + "    • /tools " + Colors.RESET + "- Ver tools disponibles")
    print(Colors.GRAY + "    • /status " + Colors.RESET + "- Estado del sistema")
    print(Colors.GRAY + "    • /create-tool " + Colors.RESET + "- Crear nueva tool")
    print(Colors.GRAY + "    • exit " + Colors.RESET + "- Salir")
    print()
    print(Colors.GRAY + "    " + "─" * 60 + Colors.RESET)
    print()


async def handle_command(engine, command: str):
    """Maneja comandos especiales (que empiezan con /)"""

    if command == "/tools":
        tools = engine.tool_registry.list_tools()
        print(Colors.BLUE + "\n📋 Tools Disponibles:\n" + Colors.RESET)

        for tool in tools:
            source_color = {
                "base": Colors.GREEN,
                "generated": Colors.YELLOW,
                "approved": Colors.CYAN
            }.get(tool.source, Colors.GRAY)

            print(f"{source_color}  • {tool.name}{Colors.RESET} - {tool.description[:60]}")
            print(f"{Colors.GRAY}    Source: {tool.source} | Uses: {tool.use_count} | Success: {tool.success_rate:.1%}{Colors.RESET}")

        print()
        return

    elif command == "/status":
        print(Colors.BLUE + "\n📊 Estado del Sistema:\n" + Colors.RESET)

        # Health de recursos
        health = engine.resources.get_all_health()
        for name, status in health.items():
            status_icon = "✅" if status.get("status") == "healthy" else "❌"
            print(f"  {status_icon} {name}: {status.get('status', 'unknown')}")

        # Stats de tools
        stats = engine.tool_registry.get_stats()
        print(f"\n{Colors.CYAN}Tools:{Colors.RESET}")
        print(f"  • Total: {stats['total_tools']}")
        print(f"  • Usos totales: {stats['total_uses']}")
        print(f"  • Success rate promedio: {stats['avg_success_rate']:.1%}")

        # Heartbeat
        hb_status = engine.heartbeat.get_status_summary()
        print(f"\n{Colors.CYAN}Heartbeat:{Colors.RESET}")
        print(f"  • Running: {hb_status['running']}")
        print(f"  • Checks: {hb_status['stats']['total_checks']}")
        print(f"  • Failed: {hb_status['stats']['failed_checks']}")
        print(f"  • Auto-repairs: {hb_status['stats']['auto_repairs']}")

        print()
        return

    elif command.startswith("/create-tool"):
        print(Colors.YELLOW + "\n🔧 Crear Nueva Tool\n" + Colors.RESET)
        print("Describí qué debe hacer la tool:")

        description = input(Colors.CYAN + "❯ " + Colors.RESET)

        if not description.strip():
            print(Colors.RED + "Descripción vacía. Cancelado." + Colors.RESET)
            return

        print(Colors.GRAY + "\nGenerando tool..." + Colors.RESET)

        # Crear tool
        tool = await engine.create_tool(description)

        print(Colors.GREEN + f"\n✅ Tool generada: {tool.name}\n" + Colors.RESET)
        print(Colors.GRAY + "Código:" + Colors.RESET)
        print(Colors.GRAY + "─" * 60 + Colors.RESET)
        print(tool.code)
        print(Colors.GRAY + "─" * 60 + Colors.RESET)

        # Testear
        print(Colors.GRAY + "\nTesteando..." + Colors.RESET)
        test_result = await engine.sandbox.test_tool(tool)

        if test_result.success:
            print(Colors.GREEN + "✅ Test pasado" + Colors.RESET)

            # Pedir aprobación
            approve = input(Colors.YELLOW + "\n¿Aprobar y registrar? (yes/no): " + Colors.RESET)

            if approve.lower() in ["yes", "y", "si", "s"]:
                engine.tool_registry.register(tool)
                print(Colors.GREEN + f"✅ Tool registrada y disponible para uso" + Colors.RESET)
            else:
                print(Colors.YELLOW + "Tool no registrada" + Colors.RESET)
        else:
            print(Colors.RED + f"❌ Test falló: {test_result.error}" + Colors.RESET)

        print()
        return

    else:
        print(Colors.RED + f"Comando desconocido: {command}" + Colors.RESET)
        print(Colors.GRAY + "Comandos disponibles: /tools, /status, /create-tool, exit" + Colors.RESET)


async def main():
    """Main loop del CLI"""

    # Inicializar engine
    print(Colors.GRAY + "Inicializando TokioAI v3.0..." + Colors.RESET)
    engine = await get_engine()

    # Mostrar banner
    await show_banner(engine)

    # REPL loop
    while True:
        try:
            # Prompt
            user_input = input(Colors.MAGENTA + "🦞 tokio" + Colors.GRAY + ">" + Colors.RESET + " ")

            if not user_input.strip():
                continue

            # Comando exit
            if user_input.strip().lower() in ["exit", "quit"]:
                print(Colors.YELLOW + "\n👋 Hasta luego!\n" + Colors.RESET)
                break

            # Comandos especiales
            if user_input.startswith("/"):
                await handle_command(engine, user_input)
                continue

            # Ejecutar tarea con el engine
            print(Colors.GRAY + "\n🤖 Procesando...\n" + Colors.RESET)

            result = await engine.execute_task(user_input, auto_approve=False)

            if result.success:
                print(Colors.GREEN + "✅ Completado\n" + Colors.RESET)

                # Mostrar output
                if result.output:
                    import json
                    try:
                        output_str = json.dumps(result.output, indent=2)
                        print(output_str)
                    except:
                        print(result.output)
            else:
                print(Colors.RED + f"❌ Error: {result.error}\n" + Colors.RESET)

            print()

        except KeyboardInterrupt:
            print(Colors.YELLOW + "\n\nInterrumpido. Usa 'exit' para salir.\n" + Colors.RESET)
            continue

        except Exception as e:
            print(Colors.RED + f"\n❌ Error: {e}\n" + Colors.RESET)
            logger.error(f"Error en CLI: {e}", exc_info=True)

    # Cleanup
    await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
