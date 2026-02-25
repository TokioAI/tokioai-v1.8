"""
Infrastructure Control Tools - Complete system control
CPU, RAM, disk, processes, services, logs, backups
"""
import os
import psutil
import subprocess
import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

def get_system_info() -> str:
    """Get complete system information"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    info = f"""🖥️ SYSTEM INFORMATION

CPU Usage: {cpu_percent}%
Memory: {memory.percent}% ({memory.used / (1024**3):.1f}GB / {memory.total / (1024**3):.1f}GB)
Disk: {disk.percent}% ({disk.used / (1024**3):.1f}GB / {disk.total / (1024**3):.1f}GB)

Load Average: {os.getloadavg()}
"""
    return info

def list_processes(limit: int = 20) -> str:
    """List top processes by CPU/Memory"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            processes.append(proc.info)
        except:
            pass

    processes.sort(key=lambda x: x['cpu_percent'], reverse=True)

    output = f"🔄 TOP {limit} PROCESSES\n\n"
    output += f"{'PID':<8} {'NAME':<30} {'CPU%':<8} {'MEM%':<8}\n"
    output += "-" * 60 + "\n"

    for proc in processes[:limit]:
        output += f"{proc['pid']:<8} {proc['name'][:30]:<30} {proc['cpu_percent']:<8.1f} {proc['memory_percent']:<8.1f}\n"

    return output

def control_service(service: str, action: str) -> str:
    """Control systemd service (start/stop/restart/status)"""
    valid_actions = ['start', 'stop', 'restart', 'status', 'enable', 'disable']

    if action not in valid_actions:
        return f"❌ Invalid action. Use: {', '.join(valid_actions)}"

    try:
        cmd = ['systemctl', action, service]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return f"✅ Service {service}: {action} successful\n\n{result.stdout}"
        else:
            return f"❌ Failed: {result.stderr}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def view_logs(service: str = "tokio-cli", lines: int = 50, follow: bool = False) -> str:
    """View service logs"""
    try:
        # For Docker services
        if service.startswith('tokio-') or service in ['postgres', 'kafka', 'nginx']:
            cmd = ['docker-compose', 'logs', '--tail', str(lines), service]
        else:
            # For systemd services
            cmd = ['journalctl', '-u', service, '-n', str(lines), '--no-pager']

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return f"📋 LOGS - {service} (last {lines} lines)\n\n{result.stdout}"
        else:
            return f"❌ Error: {result.stderr}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def backup_database(backup_path: str = "/tmp/tokio_backup.sql") -> str:
    """Backup PostgreSQL database"""
    try:
        db_host = os.getenv('POSTGRES_HOST', 'postgres')
        db_name = os.getenv('POSTGRES_DB', 'soc_ai')
        db_user = os.getenv('POSTGRES_USER', 'soc_user')
        db_pass = os.getenv('POSTGRES_PASSWORD', 'changeme_please')

        # Using docker exec for containerized postgres
        cmd = [
            'docker-compose', 'exec', '-T', 'postgres',
            'pg_dump', '-U', db_user, db_name
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0:
            with open(backup_path, 'w') as f:
                f.write(result.stdout)

            size_mb = os.path.getsize(backup_path) / (1024*1024)
            return f"✅ Database backup created: {backup_path} ({size_mb:.1f}MB)"
        else:
            return f"❌ Backup failed: {result.stderr}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def restore_database(backup_path: str) -> str:
    """Restore PostgreSQL database from backup"""
    try:
        if not os.path.exists(backup_path):
            return f"❌ Backup file not found: {backup_path}"

        db_host = os.getenv('POSTGRES_HOST', 'postgres')
        db_name = os.getenv('POSTGRES_DB', 'soc_ai')
        db_user = os.getenv('POSTGRES_USER', 'soc_user')

        # Read backup file
        with open(backup_path, 'r') as f:
            backup_data = f.read()

        # Restore using docker exec
        cmd = [
            'docker-compose', 'exec', '-T', 'postgres',
            'psql', '-U', db_user, '-d', db_name
        ]

        result = subprocess.run(
            cmd,
            input=backup_data,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            return f"✅ Database restored from: {backup_path}"
        else:
            return f"❌ Restore failed: {result.stderr}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def get_disk_usage(path: str = "/") -> str:
    """Get disk usage for path"""
    try:
        disk = psutil.disk_usage(path)

        output = f"💾 DISK USAGE - {path}\n\n"
        output += f"Total: {disk.total / (1024**3):.1f} GB\n"
        output += f"Used: {disk.used / (1024**3):.1f} GB ({disk.percent}%)\n"
        output += f"Free: {disk.free / (1024**3):.1f} GB\n"

        return output
    except Exception as e:
        return f"❌ Error: {str(e)}"

def get_network_stats() -> str:
    """Get network statistics"""
    try:
        net_io = psutil.net_io_counters()

        output = "🌐 NETWORK STATISTICS\n\n"
        output += f"Bytes Sent: {net_io.bytes_sent / (1024**2):.1f} MB\n"
        output += f"Bytes Received: {net_io.bytes_recv / (1024**2):.1f} MB\n"
        output += f"Packets Sent: {net_io.packets_sent:,}\n"
        output += f"Packets Received: {net_io.packets_recv:,}\n"
        output += f"Errors In: {net_io.errin}\n"
        output += f"Errors Out: {net_io.errout}\n"

        return output
    except Exception as e:
        return f"❌ Error: {str(e)}"

def cleanup_docker() -> str:
    """Clean up Docker (unused images, containers, volumes)"""
    try:
        cmd = ['docker', 'system', 'prune', '-a', '-f', '--volumes']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            return f"✅ Docker cleanup completed\n\n{result.stdout}"
        else:
            return f"❌ Cleanup failed: {result.stderr}"
    except Exception as e:
        return f"❌ Error: {str(e)}"
