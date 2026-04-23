"""
TokioAI Blender Tools - 3D modeling and rendering via Blender headless on GCP
"""
import os
import json
import httpx
import asyncio
import logging

logger = logging.getLogger("blender_tools")

# Blender VM config
BLENDER_VM_NAME = "blender-worker"
BLENDER_VM_ZONE = "us-central1-a"
BLENDER_VM_IP = "10.10.0.4"
BLENDER_API = f"http://{BLENDER_VM_IP}:5000"
GCP_PROJECT = "tactical-unison-417816"


async def _ensure_vm_running() -> dict:
    """Start the Blender VM if it's stopped"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gcloud", "compute", "instances", "describe", BLENDER_VM_NAME,
            f"--zone={BLENDER_VM_ZONE}", "--format=value(status)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip()
        
        if status == "RUNNING":
            return {"status": "running", "started": False}
        
        # Start the VM
        proc = await asyncio.create_subprocess_exec(
            "gcloud", "compute", "instances", "start", BLENDER_VM_NAME,
            f"--zone={BLENDER_VM_ZONE}", "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        
        # Wait for API to be ready (up to 120s)
        for i in range(24):
            await asyncio.sleep(5)
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(f"{BLENDER_API}/health")
                    if r.status_code == 200:
                        return {"status": "running", "started": True, "wait_seconds": (i+1)*5}
            except:
                continue
        
        return {"status": "started_but_api_not_ready", "started": True}
    except Exception as e:
        return {"error": str(e)}


async def _stop_vm() -> dict:
    """Stop the Blender VM to save costs"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gcloud", "compute", "instances", "stop", BLENDER_VM_NAME,
            f"--zone={BLENDER_VM_ZONE}", "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return {"status": "stopped", "message": "Blender VM stopped to save costs"}
    except Exception as e:
        return {"error": str(e)}


async def _call_blender(endpoint: str, data: dict = None, method: str = "POST") -> dict:
    """Call the Blender API"""
    # Ensure VM is running
    vm = await _ensure_vm_running()
    if "error" in vm:
        return vm
    
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            if method == "GET":
                r = await client.get(f"{BLENDER_API}{endpoint}")
            else:
                r = await client.post(f"{BLENDER_API}{endpoint}", json=data)
            return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_blender_tools():
    """Register all Blender tools"""
    
    async def blender_status(params: dict) -> str:
        """Check Blender VM status and health"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gcloud", "compute", "instances", "describe", BLENDER_VM_NAME,
                f"--zone={BLENDER_VM_ZONE}",
                "--format=json(status,machineType,scheduling,networkInterfaces[0].networkIP)",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            vm_info = json.loads(stdout.decode()) if stdout else {}
            
            result = {
                "vm_name": BLENDER_VM_NAME,
                "vm_status": vm_info.get("status", "UNKNOWN"),
                "machine_type": vm_info.get("machineType", "").split("/")[-1],
                "internal_ip": BLENDER_VM_IP,
                "zone": BLENDER_VM_ZONE,
            }
            
            if vm_info.get("status") == "RUNNING":
                try:
                    async with httpx.AsyncClient(timeout=5) as client:
                        r = await client.get(f"{BLENDER_API}/health")
                        result["api"] = r.json()
                except:
                    result["api"] = "not_responding"
            
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    async def blender_start(params: dict) -> str:
        """Start the Blender VM"""
        result = await _ensure_vm_running()
        return json.dumps(result, indent=2)
    
    async def blender_stop(params: dict) -> str:
        """Stop the Blender VM to save costs"""
        result = await _stop_vm()
        return json.dumps(result, indent=2)
    
    async def blender_render(params: dict) -> str:
        """Execute a Blender Python script headless.
        params: script (str), format (stl|obj|png|glb), job_id (optional)
        """
        script = params.get("script", "")
        fmt = params.get("format", "stl")
        job_id = params.get("job_id", "")
        
        if not script:
            return json.dumps({"error": "No script provided"})
        
        data = {"script": script, "format": fmt}
        if job_id:
            data["job_id"] = job_id
        
        result = await _call_blender("/render", data)
        
        # Clean up large stdout/stderr
        if "stdout" in result:
            result["stdout"] = result["stdout"][-500:]
        if "stderr" in result:
            result["stderr"] = result["stderr"][-500:]
        
        return json.dumps(result, indent=2)
    
    async def blender_badge(params: dict) -> str:
        """Generate a 3D badge for printing.
        params: text, shape (rectangle|hexagon|circle|shield), 
                thickness (mm), width (mm), height (mm), font_size (mm),
                format (stl|obj|glb)
        """
        data = {
            "text": params.get("text", "TokioAI"),
            "shape": params.get("shape", "rectangle"),
            "thickness": params.get("thickness", 3.0),
            "width": params.get("width", 60.0),
            "height": params.get("height", 30.0),
            "font_size": params.get("font_size", 10.0),
            "format": params.get("format", "stl"),
        }
        
        result = await _call_blender("/badge", data)
        return json.dumps(result, indent=2)
    
    async def blender_download(params: dict) -> str:
        """Download a rendered file.
        params: job_id, format (stl|obj|png|glb), save_to (local path)
        """
        job_id = params.get("job_id", "")
        fmt = params.get("format", "stl")
        save_to = params.get("save_to", f"/tmp/{job_id}.{fmt}")
        
        vm = await _ensure_vm_running()
        if "error" in vm:
            return json.dumps(vm)
        
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(f"{BLENDER_API}/download/{job_id}/{fmt}")
                if r.status_code == 200:
                    with open(save_to, "wb") as f:
                        f.write(r.content)
                    return json.dumps({
                        "downloaded": save_to,
                        "size_bytes": len(r.content),
                        "format": fmt
                    })
                else:
                    return json.dumps({"error": r.text})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    return {
        "blender_status": {
            "fn": blender_status,
            "description": "Check Blender VM status. Shows if VM is running, stopped, and API health."
        },
        "blender_start": {
            "fn": blender_start,
            "description": "Start the Blender VM (auto-stops after 15min idle). Costs ~$0.13/hr while running."
        },
        "blender_stop": {
            "fn": blender_stop,
            "description": "Stop the Blender VM to save costs. VM costs $0 when stopped."
        },
        "blender_render": {
            "fn": blender_render,
            "description": "Execute a Blender Python script headless. Auto-starts VM if needed. Params: script (Python code), format (stl/obj/png/glb), job_id (optional)."
        },
        "blender_badge": {
            "fn": blender_badge,
            "description": "Generate a 3D printable badge. Params: text, shape (rectangle/hexagon/circle/shield), thickness (mm), width (mm), height (mm), font_size (mm), format (stl/obj/glb)."
        },
        "blender_download": {
            "fn": blender_download,
            "description": "Download a rendered file from Blender VM. Params: job_id, format, save_to (local path)."
        },
    }
