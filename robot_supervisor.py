#!/usr/bin/env python3
"""
Robot Supervisor v3.0 — Tokio AI
Entity camera + Gemini Vision supervises PiDog & PiCar-X.
Anti-collision, anti-edge, keeps robots in frame.
"""

import os, sys, json, time, base64, logging, signal, requests

ENTITY_URL = "http://localhost:5000"
PIDOG_URL = "http://192.168.8.210:5001"
PICAR_URL = "http://192.168.8.107:5002"
GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

SCAN_INTERVAL = 5  # seconds between vision checks
STOP_DIST = 15     # cm ultrasonic emergency

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SUP] %(message)s')
log = logging.getLogger("sup")

running = True
cycle = 0
dog_step = 0
car_step = 0

# PiDog show (endpoint, params)
DOG_SHOW = [
    ("do_action", {"name": "stand", "steps": 1}),
    ("do_action", {"name": "forward", "steps": 3, "speed": 60}),
    ("preset", {"name": "bark"}),
    ("do_action", {"name": "wag_tail", "steps": 5}),
    ("do_action", {"name": "turn_left", "steps": 2, "speed": 60}),
    ("preset", {"name": "hand_shake"}),
    ("do_action", {"name": "turn_right", "steps": 2, "speed": 60}),
    ("preset", {"name": "howling"}),
    ("do_action", {"name": "backward", "steps": 3, "speed": 60}),
    ("preset", {"name": "body_twisting"}),
    ("do_action", {"name": "stretch", "steps": 1}),
    ("preset", {"name": "high_five"}),
    ("do_action", {"name": "push_up", "steps": 2}),
    ("preset", {"name": "attack"}),
    ("speak", {"name": "woohoo"}),
    ("do_action", {"name": "sit", "steps": 1}),
    ("do_action", {"name": "stand", "steps": 1}),
    ("preset", {"name": "pant"}),
    ("do_action", {"name": "shake_head", "steps": 3}),
    ("do_action", {"name": "trot", "steps": 3, "speed": 80}),
]

# PiCar show (endpoint, params)
CAR_SHOW = [
    ("move", {"direction": "forward", "speed": 30, "duration": 1.5}),
    ("camera", {"pan": -30, "tilt": 0}),
    ("camera", {"pan": 30, "tilt": 0}),
    ("camera", {"pan": 0, "tilt": 0}),
    ("move", {"direction": "left", "speed": 30, "duration": 1}),
    ("move", {"direction": "right", "speed": 30, "duration": 1}),
    ("move", {"direction": "backward", "speed": 30, "duration": 1.5}),
    ("camera", {"pan": -30, "tilt": -15}),
    ("camera", {"pan": 30, "tilt": -15}),
    ("camera", {"pan": 0, "tilt": 0}),
    ("move", {"direction": "forward", "speed": 25, "duration": 1}),
    ("move", {"direction": "backward", "speed": 25, "duration": 1}),
]


def signal_handler(sig, frame):
    global running
    running = False
    estop("both")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def snap():
    try:
        r = requests.get(f"{ENTITY_URL}/snapshot", timeout=5)
        return r.content if r.status_code == 200 else None
    except:
        return None


def see(img):
    """Ask Gemini what it sees — minimal prompt, no thinking"""
    if not GEMINI_API_KEY or not img:
        return None
    b64 = base64.b64encode(img).decode()
    payload = {
        "contents": [{"parts": [
            {"text": "Look at this table with robots. Answer these 5 questions with yes or no:\n1. dog_visible (quadruped robot dog)?\n2. car_visible (wheeled robot car)?\n3. dog_edge (dog near table edge)?\n4. car_edge (car near table edge)?\n5. too_close (robots within 10cm of each other)?\nFormat: dog=yes car=yes dog_edge=no car_edge=no close=no"},
            {"inline_data": {"mime_type": "image/jpeg", "data": b64}}
        ]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 1024,
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }
    try:
        r = requests.post(GEMINI_URL, json=payload, timeout=15)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][-1]["text"].strip().lower()
            log.info(f"👁️ Gemini: {text}")
            result = {}
            for item in text.replace("\n", " ").split():
                if "=" in item:
                    k, v = item.split("=", 1)
                    result[k.strip()] = v.strip() == "yes"
            return result
        elif r.status_code == 429:
            log.warning("⚡ Gemini rate limit — skipping vision")
        else:
            log.error(f"Gemini {r.status_code}")
    except Exception as e:
        log.error(f"Gemini: {e}")
    return None


def distances():
    d = {"dog": -1, "car": -1}
    try:
        r = requests.get(f"{PIDOG_URL}/status", timeout=3)
        if r.ok: d["dog"] = r.json().get("data", {}).get("distance_cm", -1)
    except: pass
    try:
        r = requests.get(f"{PICAR_URL}/sensors", timeout=3)
        if r.ok: d["car"] = r.json().get("ultrasonic_cm", -1)
    except: pass
    return d


def dog(ep, p):
    try:
        r = requests.post(f"{PIDOG_URL}/{ep}", json=p, timeout=8)
        log.info(f"🐕 /{ep} {p} -> {r.status_code}")
        return r.ok
    except: return False


def car(ep, p):
    try:
        r = requests.post(f"{PICAR_URL}/{ep}", json=p, timeout=8)
        log.info(f"🤖 /{ep} {p} -> {r.status_code}")
        return r.ok
    except: return False


def estop(who="both"):
    log.warning(f"🛑 STOP {who}")
    if who in ("both", "dog"):
        try: requests.post(f"{PIDOG_URL}/stop", timeout=2)
        except: pass
    if who in ("both", "car"):
        try: requests.post(f"{PICAR_URL}/stop", timeout=2)
        except: pass


def safety(vision, dist):
    """Apply safety rules. Returns True if had to intervene."""
    hit = False

    # Ultrasonic first (fastest)
    if 0 < dist["dog"] < STOP_DIST:
        log.warning(f"🔴 Dog ultrasonic {dist['dog']}cm!")
        estop("dog"); time.sleep(0.5)
        dog("do_action", {"name": "backward", "steps": 2, "speed": 60})
        hit = True
    if 0 < dist["car"] < STOP_DIST:
        log.warning(f"🔴 Car ultrasonic {dist['car']}cm!")
        estop("car"); time.sleep(0.5)
        car("move", {"direction": "backward", "speed": 30, "duration": 1})
        hit = True

    if not vision:
        return hit

    # Vision safety
    if vision.get("close"):
        log.warning("🔴 TOO CLOSE — separating!")
        estop("both"); time.sleep(1)
        dog("do_action", {"name": "backward", "steps": 3, "speed": 60})
        time.sleep(2)
        car("move", {"direction": "backward", "speed": 30, "duration": 1.5})
        hit = True

    if vision.get("dog_edge"):
        log.warning("🔴 Dog at EDGE!")
        estop("dog"); time.sleep(0.5)
        dog("do_action", {"name": "backward", "steps": 3, "speed": 60})
        hit = True

    if vision.get("car_edge"):
        log.warning("🔴 Car at EDGE!")
        estop("car"); time.sleep(0.5)
        car("move", {"direction": "backward", "speed": 30, "duration": 1.5})
        hit = True

    if vision.get("dog") == False:
        log.warning("⚠️ Dog OUT OF FRAME!")
        estop("dog")
        hit = True

    if vision.get("car") == False:
        log.warning("⚠️ Car OUT OF FRAME!")
        estop("car")
        hit = True

    return hit


def choreo():
    global dog_step, car_step
    ep, p = DOG_SHOW[dog_step % len(DOG_SHOW)]
    dog(ep, p)
    dog_step += 1
    time.sleep(1.5)
    ep, p = CAR_SHOW[car_step % len(CAR_SHOW)]
    car(ep, p)
    car_step += 1


def main():
    global cycle
    log.info("=" * 50)
    log.info("🤖 Robot Supervisor v3.0")
    log.info(f"   PiDog: {PIDOG_URL}")
    log.info(f"   PiCar: {PICAR_URL}")
    log.info(f"   Vision: Gemini 2.5 Flash (no-think)")
    log.info("=" * 50)

    if not GEMINI_API_KEY:
        log.error("❌ No GOOGLE_API_KEY"); sys.exit(1)

    dog("do_action", {"name": "stand", "steps": 1})
    time.sleep(2)
    car("camera", {"pan": 0, "tilt": 0})
    time.sleep(1)
    log.info("🚀 GO!")

    while running:
        cycle += 1
        log.info(f"\n--- Cycle {cycle} ---")

        img = snap()
        dist = distances()
        log.info(f"📏 dog={dist['dog']}cm car={dist['car']}cm")

        vision = see(img)
        stopped = safety(vision, dist)

        if not stopped:
            choreo()
        else:
            log.info("⏸️ Safety pause")
            time.sleep(3)

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
