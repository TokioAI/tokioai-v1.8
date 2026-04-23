#!/usr/bin/env python3
"""PiDog Server v10.0 — 100% SunFounder API
Uses ActionFlow for presets, do_action for movements,
set_rpy(pid=True) for IMU balance. Zero custom code."""

import json
import threading
import time
import signal
import sys
import os
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from pidog import Pidog
from pidog.action_flow import ActionFlow
from pidog.walk import Walk

# ── Globals ──
dog = None
action_flow = None
show_thread = None
show_stop = threading.Event()
patrol_thread = None
patrol_stop = threading.Event()
balance_thread = None
balance_stop = threading.Event()

SOUNDS_DIR = '/home/mrmoz/pidog/sounds'

def init_dog():
    """Initialize Pidog + ActionFlow exactly like official examples."""
    global dog, action_flow
    os.system('pinctrl set 12 op dh')  # Enable speaker GPIO
    dog = Pidog()
    time.sleep(0.5)
    action_flow = ActionFlow(dog)
    dog.do_action('stand', speed=50)
    dog.wait_all_done()
    print("[OK] PiDog + ActionFlow initialized")

# ── Balance Thread (from example 10_balance.py) ──
def start_balance():
    """IMU PID balance — keeps dog stable during movement."""
    global balance_thread, balance_stop
    balance_stop.clear()
    
    stand_coords = [[[-15, 95], [-15, 95], [5, 90], [5, 90]]]
    
    def _loop():
        while not balance_stop.is_set():
            try:
                dog.set_rpy(roll=0, pitch=0, yaw=0, pid=True)
                dog.set_pose(x=0, y=0, z=80)
                for coord in stand_coords:
                    if balance_stop.is_set():
                        break
                    dog.set_legs(coord)
                    angles = dog.pose2legs_angle()
                    dog.legs.servo_move(angles, speed=50)
                    time.sleep(0.05)
            except:
                time.sleep(0.1)
    
    balance_thread = threading.Thread(target=_loop, daemon=True)
    balance_thread.start()
    print("[OK] Balance PID started")

def stop_balance():
    global balance_stop
    balance_stop.set()

# ── Patrol (from example 3_patrol.py — EXACT copy) ──
def start_patrol():
    """Patrol with obstacle avoidance — exact copy of example 3."""
    global patrol_thread, patrol_stop
    stop_all()
    patrol_stop.clear()
    
    DANGER_DISTANCE = 15
    stand = dog.legs_angle_calculation([[0, 80], [0, 80], [30, 75], [30, 75]])
    
    def _patrol():
        from pidog.preset_actions import bark
        dog.do_action('stand', speed=80)
        dog.wait_all_done()
        time.sleep(0.5)
        
        while not patrol_stop.is_set():
            try:
                distance = round(dog.read_distance(), 2)
                if distance > 0 and distance < DANGER_DISTANCE:
                    # DANGER — stop and bark
                    dog.body_stop()
                    head_yaw = dog.head_current_angles[0]
                    dog.rgb_strip.set_mode('bark', 'red', bps=2)
                    dog.tail_move([[0]], speed=80)
                    dog.legs_move([stand], speed=70)
                    dog.wait_all_done()
                    time.sleep(0.5)
                    bark(dog, [head_yaw, 0, 0])
                    # Wait until safe
                    while distance < DANGER_DISTANCE and not patrol_stop.is_set():
                        distance = round(dog.read_distance(), 2)
                        time.sleep(0.1)
                    # Turn away
                    dog.do_action('turn_left', step_count=3, speed=98)
                    dog.wait_all_done()
                else:
                    # SAFE — walk forward
                    dog.rgb_strip.set_mode('breath', 'white', bps=0.5)
                    dog.do_action('forward', step_count=2, speed=98)
                    dog.do_action('wag_tail', step_count=3, speed=99)
                time.sleep(0.01)
            except Exception as e:
                print(f"[PATROL ERR] {e}")
                time.sleep(0.5)
    
    patrol_thread = threading.Thread(target=_patrol, daemon=True)
    patrol_thread.start()
    print("[OK] Patrol started")

def stop_patrol():
    patrol_stop.set()
    dog.body_stop()

# ── Show Choreography ──
SHOWS = {
    "boston_dynamics": [
        # Phase 1: Wake up
        ("action_flow", "stretch"),
        ("action_flow", "stand"),
        ("rgb", "breath", "cyan"),
        ("speak", "pant"),
        ("sleep", 1),
        # Phase 2: Walk with confidence
        ("action_flow", "forward"),
        ("action_flow", "forward"),
        ("action_flow", "forward"),
        ("rgb", "breath", "green"),
        # Phase 3: Turn and scan
        ("action_flow", "turn left"),
        ("action_flow", "turn right"),
        ("action_flow", "turn right"),
        ("action_flow", "turn left"),
        # Phase 4: Show tricks
        ("action_flow", "bark"),
        ("rgb", "bark", "pink"),
        ("action_flow", "handshake"),
        ("speak", "woohoo"),
        ("action_flow", "high five"),
        # Phase 5: Emotions
        ("action_flow", "think"),
        ("action_flow", "surprise"),
        ("rgb", "flash", "red"),
        ("speak", "angry"),
        ("action_flow", "bark harder"),
        # Phase 6: Power moves
        ("action_flow", "push up"),
        ("rgb", "breath", "blue"),
        ("action_flow", "twist body"),
        # Phase 7: Finale
        ("action_flow", "howling"),
        ("action_flow", "wag tail"),
        ("rgb", "breath", "cyan"),
        ("action_flow", "pant"),
    ],
    "performer": [
        ("action_flow", "stand"),
        ("action_flow", "bark"),
        ("rgb", "breath", "pink"),
        ("action_flow", "wag tail"),
        ("action_flow", "handshake"),
        ("speak", "woohoo"),
        ("action_flow", "high five"),
        ("action_flow", "scratch"),
        ("action_flow", "lick hand"),
        ("rgb", "flash", "green"),
        ("action_flow", "twist body"),
        ("action_flow", "howling"),
        ("action_flow", "pant"),
    ],
    "guard": [
        ("action_flow", "stand"),
        ("rgb", "breath", "red"),
        ("action_flow", "shake head"),
        ("do_action", "forward", 3, 98),
        ("action_flow", "bark harder"),
        ("speak", "growl_1"),
        ("do_action", "turn_left", 2, 98),
        ("do_action", "turn_right", 2, 98),
        ("action_flow", "bark harder"),
        ("speak", "angry"),
        ("rgb", "flash", "red"),
        ("action_flow", "bark"),
        ("action_flow", "stand"),
    ],
    "playful": [
        ("action_flow", "stand"),
        ("action_flow", "wag tail"),
        ("rgb", "breath", "green"),
        ("action_flow", "scratch"),
        ("speak", "woohoo"),
        ("action_flow", "lick hand"),
        ("action_flow", "feet shake"),
        ("rgb", "breath", "pink"),
        ("action_flow", "twist body"),
        ("action_flow", "bark"),
        ("action_flow", "pant"),
    ],
    "greeting": [
        ("action_flow", "stand"),
        ("action_flow", "bark"),
        ("rgb", "breath", "pink"),
        ("action_flow", "wag tail"),
        ("action_flow", "nod"),
        ("action_flow", "handshake"),
        ("speak", "woohoo"),
        ("action_flow", "pant"),
    ],
}

def run_show(name):
    """Run a choreographed show using ActionFlow."""
    global show_thread, show_stop
    stop_all()
    show_stop.clear()
    
    steps = SHOWS.get(name, SHOWS["boston_dynamics"])
    
    def _run():
        for step in steps:
            if show_stop.is_set():
                break
            try:
                cmd = step[0]
                if cmd == "action_flow":
                    action_flow.run(step[1])
                elif cmd == "do_action":
                    dog.do_action(step[1], step_count=step[2], speed=step[3])
                    dog.wait_all_done()
                elif cmd == "speak":
                    dog.speak(step[1], volume=80)
                elif cmd == "rgb":
                    dog.rgb_strip.set_mode(step[1], step[2], bps=1)
                elif cmd == "sleep":
                    time.sleep(step[1])
            except Exception as e:
                print(f"[SHOW STEP ERR] {step}: {e}")
        print(f"[OK] Show '{name}' finished")
    
    show_thread = threading.Thread(target=_run, daemon=True)
    show_thread.start()

def stop_all():
    """Stop everything safely."""
    show_stop.set()
    patrol_stop.set()
    balance_stop.set()
    try:
        dog.body_stop()
        dog.do_action('stand', speed=50)
        dog.rgb_strip.set_mode('breath', 'cyan', bps=0.5)
    except:
        pass

# ── HTTP Handler ──
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence logs
    
    def _respond(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        if self.path == '/status':
            dist = -1
            try:
                dist = round(dog.read_distance(), 2)
            except:
                pass
            self._respond(200, {
                "status": "ok",
                "version": "10.0",
                "name": "PiDog Server (100% SunFounder)",
                "distance_cm": dist,
                "battery": "check_i2c",
                "sounds": sorted(os.listdir(SOUNDS_DIR)) if os.path.isdir(SOUNDS_DIR) else [],
                "shows": list(SHOWS.keys()),
                "action_flow_actions": list(ActionFlow.OPERATIONS.keys()),
                "do_actions": [
                    "stand", "sit", "lie", "lie_with_hands_out",
                    "forward", "backward", "turn_left", "turn_right",
                    "trot", "stretch", "push_up", "doze_off",
                    "shake_head", "tilting_head", "wag_tail",
                    "head_up_down", "half_sit", "nod_lethargy", "head_bark"
                ],
            })
        elif self.path == '/distance':
            try:
                d = round(dog.read_distance(), 2)
                self._respond(200, {"distance_cm": d})
            except Exception as e:
                self._respond(500, {"error": str(e)})
        else:
            self._respond(404, {"error": "not found"})
    
    def do_POST(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}
        except:
            body = {}
        
        path = self.path
        
        # ActionFlow actions (the good stuff)
        if path == '/action_flow':
            action = body.get('action', 'stand')
            if action in ActionFlow.OPERATIONS:
                threading.Thread(target=action_flow.run, args=(action,), daemon=True).start()
                self._respond(200, {"ok": True, "action_flow": action})
            else:
                self._respond(400, {"error": f"Unknown action: {action}", "available": list(ActionFlow.OPERATIONS.keys())})
        
        # do_action (low level — from example 2)
        elif path == '/do_action':
            name = body.get('name', 'stand')
            steps = body.get('step_count', 1)
            speed = body.get('speed', 50)
            def _do():
                dog.do_action(name, step_count=steps, speed=speed)
                dog.wait_all_done()
            threading.Thread(target=_do, daemon=True).start()
            self._respond(200, {"ok": True, "do_action": name, "steps": steps, "speed": speed})
        
        # Speak (sound file)
        elif path == '/speak':
            sound = body.get('sound', 'single_bark_1')
            volume = body.get('volume', 80)
            threading.Thread(target=dog.speak, args=(sound,), kwargs={"volume": volume}, daemon=True).start()
            self._respond(200, {"ok": True, "speak": sound})
        
        # RGB LEDs
        elif path == '/rgb':
            mode = body.get('mode', 'breath')
            color = body.get('color', 'cyan')
            bps = body.get('bps', 1)
            dog.rgb_strip.set_mode(mode, color, bps=bps)
            self._respond(200, {"ok": True, "rgb": {"mode": mode, "color": color}})
        
        # Head move
        elif path == '/head':
            yaw = body.get('yaw', 0)
            roll = body.get('roll', 0)
            pitch = body.get('pitch', 0)
            speed = body.get('speed', 80)
            dog.head_move_raw([[yaw, roll, pitch]], immediately=True, speed=speed)
            self._respond(200, {"ok": True, "head": {"yaw": yaw, "roll": roll, "pitch": pitch}})
        
        # Tail move
        elif path == '/tail':
            angle = body.get('angle', 0)
            speed = body.get('speed', 80)
            dog.tail_move([[angle]], speed=speed)
            self._respond(200, {"ok": True, "tail": angle})
        
        # Show (choreography)
        elif path == '/show':
            name = body.get('name', 'boston_dynamics')
            run_show(name)
            self._respond(200, {"ok": True, "show": name})
        
        # Patrol (example 3 exact)
        elif path == '/patrol':
            start_patrol()
            self._respond(200, {"ok": True, "patrol": "started"})
        
        # Balance (example 10 — IMU PID)
        elif path == '/balance':
            start_balance()
            self._respond(200, {"ok": True, "balance": "started"})
        
        # Stop everything
        elif path == '/stop':
            stop_all()
            self._respond(200, {"ok": True, "stopped": True})
        
        else:
            self._respond(404, {"error": "not found"})

# ── Shutdown ──
def shutdown(sig, frame):
    print("\n[SHUTDOWN] Cleaning up...")
    stop_all()
    try:
        dog.close()
    except:
        pass
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

# ── Main ──
if __name__ == '__main__':
    print("=" * 50)
    print("  PiDog Server v10.0 — 100% SunFounder API")
    print("=" * 50)
    init_dog()
    server = HTTPServer(('0.0.0.0', 5001), Handler)
    print(f"[OK] Listening on http://0.0.0.0:5001")
    print(f"[OK] Shows: {list(SHOWS.keys())}")
    print(f"[OK] ActionFlow: {list(ActionFlow.OPERATIONS.keys())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)
