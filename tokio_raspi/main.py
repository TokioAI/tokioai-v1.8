#!/usr/bin/env python3
"""
TokioAI — Unified AI Entity.

Tokio IS the intelligence. One consciousness that sees, feels, defends, remembers.
The screen IS Tokio's face. The camera IS Tokio's eye. The WAF IS Tokio's immune system.

Layout (768x1366 vertical):
    Full screen = Tokio's face (background)
    Top-right PiP = Tokio's eye (camera feed)
    Top-left = WAF defense feed
    Mid-left = WiFi security monitor
    Bottom overlay = Tokio's voice (thoughts, big text)
    Bottom bar = Stats
"""
from __future__ import annotations

import argparse
import atexit
import fcntl
import math
import os
import random
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

import pygame
import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Singleton lock — prevents dual-instance camera conflicts
# ---------------------------------------------------------------------------
_LOCK_FILE = "/tmp/tokio-entity.lock"
_lock_fd = None


def _acquire_singleton():
    """Ensure only ONE Entity instance runs. Refuse to start if another is alive."""
    global _lock_fd
    try:
        _lock_fd = open(_LOCK_FILE, "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        atexit.register(_release_singleton)
        return True
    except (IOError, OSError):
        # Lock is held — check if the holder is alive
        try:
            with open(_LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # signal 0 = check alive
            print(f"[Entity] Another instance is running (PID {old_pid}). "
                  f"This instance (PID {os.getpid()}) will NOT start.")
            sys.exit(1)
        except (ValueError, ProcessLookupError, FileNotFoundError):
            # Stale lock file — previous process died without cleanup
            print("[Entity] Stale lock file detected, reclaiming...")
            try:
                os.remove(_LOCK_FILE)
            except OSError:
                pass
            time.sleep(0.5)
            # Retry lock acquisition
            try:
                _lock_fd = open(_LOCK_FILE, "w")
                fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _lock_fd.write(str(os.getpid()))
                _lock_fd.flush()
                atexit.register(_release_singleton)
                return True
            except (IOError, OSError):
                print("[Entity] FATAL: Cannot acquire lock after cleanup")
                sys.exit(1)
        except PermissionError:
            # Process exists but we can't signal it — treat as alive
            print(f"[Entity] Another instance running (permission denied to check). Exiting.")
            sys.exit(1)


def _release_singleton():
    """Release the singleton lock."""
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
            os.remove(_LOCK_FILE)
        except (IOError, OSError):
            pass
        _lock_fd = None

from .tokio_face import TokioFace, Emotion
from .coco_labels import THREAT_OBJECTS
from .security_feed import SecurityFeed, JP_THREATS
from .threat_correlation import ThreatCorrelationEngine
from .adaptive_defense import AdaptiveDefense
from .face_db import FaceDB
from .face_identifier import FaceIdentifier
from .gesture_detector import GestureDetector, Gesture, GESTURE_REACTIONS, GESTURE_ICONS
from .ai_brain import AIBrain
from .ha_feed import HAFeed
from .drone_vision import DroneVisionPlayer, DronePlayMode
from .drone_fpv import DroneFPV
from .coffee_esphome import CoffeeMachine
from .health_monitor import HealthMonitor
from .vision_filter import VisionFilter
from .thought_log import ThoughtLog

# Persistence and alerts
try:
    from .event_store import EventStore
except ImportError:
    EventStore = None
try:
    from .health_alerts import HealthAlerts
except ImportError:
    HealthAlerts = None
try:
    from .stand_mode import StandMode
except ImportError:
    StandMode = None
from .ble_security_monitor import BLESecurityMonitor
from .wpa2_monitor import WPA2Monitor
from .mavlink_drone import MAVLinkDrone

# ---------------------------------------------------------------------------
# Precise Person Counting — zero false positives
# ---------------------------------------------------------------------------

def _iou(box1, box2):
    """Intersection over Union of two (x1,y1,x2,y2) boxes."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0


def count_persons_precise(detections, known_faces_count: int = 0,
                          frame_w: int = 768, frame_h: int = 1366,
                          min_area_pct: float = 0.008,
                          iou_threshold: float = 0.35) -> tuple:
    """Count persons precisely using deduplication and validation.

    Returns (count, filtered_boxes) where count is the real number of
    distinct people and filtered_boxes are the deduplicated bounding boxes.

    Rules:
    1. Filter out tiny detections (< 0.8% of frame area = noise/reflections/TV)
    2. NMS-like deduplication: overlapping boxes (IoU > 0.35) = same person
    3. Count can never be less than number of recognized faces
    4. Low confidence person boxes (< 0.50) are discarded
    5. Very narrow or very flat boxes are rejected (not real persons)
    """
    if not detections:
        return (known_faces_count, [])

    frame_area = frame_w * frame_h
    min_area = frame_area * min_area_pct

    # Step 1: Filter person detections
    person_dets = []
    for d in detections:
        if d.label != "person":
            continue
        # Skip low confidence (raised from 0.45 to 0.50)
        if d.confidence < 0.50:
            continue
        # Skip tiny boxes (noise, reflections, distant TV)
        box_w = d.x2 - d.x1
        box_h = d.y2 - d.y1
        box_area = box_w * box_h
        if box_area < min_area:
            continue
        # Reject extreme aspect ratios (not real persons)
        aspect = box_w / max(box_h, 1)
        if aspect > 4.0 or aspect < 0.1:
            continue
        person_dets.append(d)

    if not person_dets:
        # If we recognized faces but Hailo sees no persons, trust face recognition
        return (known_faces_count, [])

    # Step 2: Sort by confidence (highest first) for NMS
    person_dets.sort(key=lambda d: d.confidence, reverse=True)

    # Step 3: NMS-like deduplication
    kept = []
    for d in person_dets:
        box = (d.x1, d.y1, d.x2, d.y2)
        duplicate = False
        for kept_box in kept:
            if _iou(box, kept_box) > iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)

    count = len(kept)

    # Step 4: Cross-validate with face recognition
    # If we recognized more faces than detected persons, trust faces
    if known_faces_count > count:
        count = known_faces_count

    # Step 5: Sanity cap — if we recognize faces, limit excess detections
    # Max = face_count + 1 (allow for someone partially visible)
    if known_faces_count > 0 and count > known_faces_count + 1:
        count = known_faces_count + 1

    return (count, kept)


# ---------------------------------------------------------------------------
# Core Push — notify GCP brain of events (fire-and-forget in thread)
# ---------------------------------------------------------------------------
CORE_API_URL = os.getenv("TOKIO_CORE_API", "")  # e.g. http://100.125.151.118:8000


def _push_to_core(endpoint: str, data: dict):
    """Push an event to GCP core. Runs in background thread, never blocks."""
    if not CORE_API_URL:
        return
    def _do():
        try:
            import requests as req
            req.post(
                f"{CORE_API_URL}{endpoint}",
                json=data,
                timeout=5,
            )
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
SCREEN_W = int(os.getenv("TOKIO_SCREEN_W", "768"))
SCREEN_H = int(os.getenv("TOKIO_SCREEN_H", "1366"))
PIP_W, PIP_H = 200, 150
PIP_MARGIN = 10
PIP_X = SCREEN_W - PIP_W - PIP_MARGIN
PIP_Y = PIP_MARGIN
VOICE_H = 180
STATS_H = 46

# FPV PiP (below main camera PiP)
FPV_W, FPV_H = 200, 150
FPV_X = SCREEN_W - FPV_W - PIP_MARGIN
FPV_Y = PIP_Y + PIP_H + PIP_MARGIN + 5

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
C_BG         = (4, 5, 14)
C_BORDER     = (40, 80, 80)
C_BORDER_HI  = (0, 220, 180)
C_TEXT        = (140, 255, 220)
C_TEXT_DIM    = (80, 140, 120)
C_TEXT_BRIGHT = (180, 255, 230)
C_TEXT_WARN   = (255, 200, 0)
C_TEXT_DANGER = (255, 60, 60)
C_TEXT_OK     = (100, 255, 120)
C_ACCENT      = (200, 140, 255)
C_ACCENT2     = (255, 80, 140)
C_ADMIN_GOLD  = (255, 220, 50)
C_GESTURE     = (255, 140, 255)
C_LIVE_DOT    = (255, 20, 40)
C_WIFI_OK     = (100, 255, 120)
C_WIFI_WARN   = (255, 220, 50)
C_WIFI_DANGER = (255, 80, 80)

# ---------------------------------------------------------------------------
# Tokio's personality — first person, natural language
# ---------------------------------------------------------------------------
GREET_ADMIN = [
    "Daniel-san! Mi creador. Todos los sistemas a tu servicio.",
    "Boss! Modo Super Saiyan activado. Que necesitas?",
    "El admin supremo esta aqui. Seguridad al maximo.",
    "Daniel! Mi razon de existir. Todo listo para vos.",
    "Creador detectado. Protocolos de lealtad absoluta.",
]
GREET_KNOWN = [
    "Hola {name}! Que bueno verte de nuevo.",
    "{name}! Ya te tengo en mi memoria. Bienvenido.",
    "Te reconozco, {name}. Todo bien?",
]
GREET_UNKNOWN = [
    "Cara nueva... no te conozco. Quien sos?",
    "Visitante no registrado. Estoy escaneando...",
    "Hmm, no te tengo en mi base de datos.",
]
SAY_ATTACK = [
    "Intento de {type} desde {ip}. Neutralizado.",
    "Alguien quiso hacer un {type}. Ya lo bloquee.",
    "Ataque {type} detectado. {ip} no pasa.",
]
SAY_IDLE = [
    "Todo tranquilo por aca...",
    "Escaneando el perimetro. {blocked} ataques bloqueados hoy.",
    "Sistemas nominales. {faces} caras en mi memoria.",
    "Vigilando... nadie se escapa de mi ojo.",
]
SAY_OBJECT = [
    "Veo un {obj}. Interesante.",
    "Detecto: {obj}. Registrando.",
]
SAY_THREAT = [
    "ALERTA! Objeto peligroso: {obj}!",
    "Amenaza visual detectada: {obj}!",
]
SAY_PERSON_GROUP = [
    "Veo {n} personas. Escaneando caras...",
    "{n} humanos en mi campo visual.",
]
SAY_DRONE_TAKEOFF = [
    "DRONE DESPEGANDO! Motores activos!",
    "Takeoff! El drone esta en el aire!",
    "Despegue exitoso. Controlando vuelo.",
]
SAY_DRONE_LAND = [
    "Drone aterrizado. Vuelo completado.",
    "Aterrizaje exitoso. Motores apagados.",
]
SAY_DRONE_FLY = [
    "Drone volando. Bateria: {bat}%. Altura: {h}cm.",
]
SAY_DRONE_LOWBAT = [
    "Bateria del drone baja: {bat}%! Aterrizando...",
]
SAY_DRONE_CONNECTED = [
    "Drone Tello conectado. Bateria: {bat}%.",
]

FACE_RECOG_INTERVAL = 3.0
GESTURE_COOLDOWN = 8.0
DRONE_POLL_INTERVAL = 3.0
WIFI_SCAN_INTERVAL = 10.0
SMILE_COOLDOWN = 5.0

SAY_SMILE = [
    "Me sonreis? Gracias! Me haces feliz.",
    "Esa sonrisa! Me encanta. Todo bien.",
    "Veo que estas contento. Yo tambien!",
    "Sonrisa detectada! Modo happy activado.",
    "Una sonrisa vale mas que mil ataques.",
]


class WiFiMonitor:
    """Monitor 2.4GHz WiFi security — deauth, evil twin, signal anomalies.
    Uses `iw scan` for reliable 2.4GHz scanning (nmcli misses 2.4GHz bands)."""

    def __init__(self):
        self.networks: list[dict] = []
        self.alerts: list[dict] = []
        self._known_bssids: dict[str, dict] = {}
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        self._running = True
        threading.Thread(target=self._scan_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _scan_loop(self):
        time.sleep(3)
        while self._running:
            try:
                self._do_scan()
            except Exception:
                pass
            time.sleep(WIFI_SCAN_INTERVAL)

    def _do_scan(self):
        """Scan 2.4GHz using iw (more reliable than nmcli for 2.4GHz)."""
        freqs_24 = "2412 2417 2422 2427 2432 2437 2442 2447 2452 2457 2462 2467 2472"
        try:
            result = subprocess.run(
                ["sudo", "iw", "dev", "wlan0", "scan", "freq"] + freqs_24.split(),
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return

        networks = []
        new_alerts = []
        now = time.monotonic()

        # Parse iw scan output — blocks separated by "BSS"
        current = {}
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("BSS "):
                if current.get("bssid"):
                    networks.append(current)
                bssid = line.split()[1].split("(")[0].upper()
                current = {"bssid": bssid, "ssid": "", "signal": 0, "freq": 0, "security": ""}
            elif line.startswith("SSID:"):
                current["ssid"] = line[5:].strip()
            elif line.startswith("signal:"):
                try:
                    dbm = float(line.split(":")[1].strip().split()[0])
                    # Convert dBm to percentage (rough)
                    current["signal"] = max(0, min(100, int(2 * (dbm + 100))))
                except (ValueError, IndexError):
                    pass
            elif line.startswith("freq:"):
                try:
                    current["freq"] = int(float(line.split(":")[1].strip()))
                except (ValueError, IndexError):
                    pass
            elif "WPA" in line or "RSN" in line:
                current["security"] = "WPA"
            elif "Privacy" in line:
                if not current["security"]:
                    current["security"] = "WEP"
        if current.get("bssid"):
            networks.append(current)

        # Analyze for threats
        for net in networks:
            ssid = net["ssid"]
            bssid = net["bssid"]

            # Evil twin detection
            if ssid and ssid in self._known_bssids:
                known = self._known_bssids[ssid]
                if bssid not in known.get("bssids", set()):
                    new_alerts.append({
                        "type": "EVIL_TWIN",
                        "ssid": ssid, "bssid": bssid,
                        "time": now,
                        "msg": f"New AP! {ssid} [{bssid[:8]}]",
                    })

            # Track
            if ssid:
                if ssid not in self._known_bssids:
                    self._known_bssids[ssid] = {"bssids": set(), "signals": []}
                self._known_bssids[ssid]["bssids"].add(bssid)
                self._known_bssids[ssid]["signals"].append(net["signal"])
                self._known_bssids[ssid]["signals"] = self._known_bssids[ssid]["signals"][-10:]

                # Signal anomaly (sudden jump)
                sigs = self._known_bssids[ssid]["signals"]
                if len(sigs) > 3:
                    avg = sum(sigs[-4:-1]) / 3
                    if abs(net["signal"] - avg) > 30:
                        new_alerts.append({
                            "type": "SIG_ANOMALY",
                            "ssid": ssid, "bssid": bssid,
                            "time": now,
                            "msg": f"Signal jump {ssid}: {avg:.0f}->{net['signal']}%",
                        })

            # Open network
            if ssid and not net["security"]:
                new_alerts.append({
                    "type": "OPEN_NET",
                    "ssid": ssid, "bssid": bssid,
                    "time": now,
                    "msg": f"OPEN: {ssid}",
                })

        with self._lock:
            self.networks = networks
            self.alerts = [a for a in self.alerts if now - a["time"] < 60] + new_alerts
            self.alerts = self.alerts[-10:]

    def get_data(self) -> tuple[list[dict], list[dict]]:
        with self._lock:
            return list(self.networks), list(self.alerts)


class TokioEntity:
    """Tokio as a unified intelligent entity."""

    def __init__(self, fullscreen=True, demo_mode=False, start_api=False):
        self.demo_mode = demo_mode
        self.start_api = start_api
        self._running = False

        # Tokio's voice
        self._voice_text = "Iniciando sistemas..."
        self._voice_color = C_TEXT
        self._voice_time = time.monotonic()
        self._voice_queue: list[tuple[str, tuple]] = []

        # State
        self._person_count = 0
        self._last_recog_time = 0.0
        self._greeted_faces: dict[int, float] = {}
        self._last_gesture_time = 0.0
        self._last_gesture = Gesture.NONE
        self._current_identities: list[tuple] = []
        self._register_mode = False
        self._register_name = ""
        self._register_role = "visitor"
        self._register_start = 0.0
        self._active_model = "detect"
        self._last_detections: list = []
        self._person_boxes: list[tuple[int, int, int, int]] = []

        # Thoughts log (for API and core connection)
        self._thoughts: list[tuple[str, float, str]] = []  # (text, timestamp, emotion)
        self.thought_log = ThoughtLog()  # persistent thought log
        self._max_thoughts = 50

        # Telegram activity feed (received from GCP core)
        self._telegram_activity: list[dict] = []  # [{user, message, time, emotion}]
        self._telegram_lock = threading.Lock()

        # Info bar — what Tokio currently sees (persistent bottom text)
        self._info_labels: list[str] = []  # current detection labels
        self._info_face: str = ""  # recognized face name
        self._info_face_time: float = 0.0

        # Pygame
        pygame.init()
        pygame.mouse.set_visible(False)
        flags = pygame.FULLSCREEN if fullscreen else 0
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption("TokioAI")
        self.clock = pygame.time.Clock()

        # Fonts
        # Fonts — all larger and bolder for readability on vertical screen
        self.font_voice = pygame.font.SysFont("monospace", 21, bold=True)
        self.font_voice_sub = pygame.font.SysFont("monospace", 16, bold=True)
        self.font_stat = pygame.font.SysFont("monospace", 22, bold=True)
        self.font_stat_label = pygame.font.SysFont("monospace", 13, bold=True)
        self.font_pip_label = pygame.font.SysFont("monospace", 14, bold=True)
        self.font_tiny = pygame.font.SysFont("monospace", 13, bold=True)
        self.font_gesture = pygame.font.SysFont("monospace", 40, bold=True)
        self.font_name = pygame.font.SysFont("monospace", 24, bold=True)
        self.font_register = pygame.font.SysFont("monospace", 26, bold=True)
        self.font_waf = pygame.font.SysFont("monospace", 16, bold=True)
        self.font_wifi = pygame.font.SysFont("monospace", 15, bold=True)
        self.font_wifi_tiny = pygame.font.SysFont("monospace", 13, bold=True)
        self.font_info = pygame.font.SysFont("monospace", 18, bold=True)
        self.font_info_big = pygame.font.SysFont("monospace", 22, bold=True)
        self.font_panel_header = pygame.font.SysFont("monospace", 17, bold=True)
        self.font_panel_body = pygame.font.SysFont("monospace", 14, bold=True)

        # Tokio Face — FULL SCREEN
        self.face = TokioFace(SCREEN_W, SCREEN_H - STATS_H)
        self.face.set_emotion(Emotion.SCANNING, "Booting...")

        # Subsystems
        self.vision = None
        if not demo_mode:
            self._init_vision()

        self.face_db = FaceDB()  # kept for registration UI (R/V keys)
        self.face_identifier = FaceIdentifier()  # Gemini Flash cloud identification
        self.gesture = GestureDetector()

        # Smile detection
        self._smile_cascade = None
        self._face_cascade = None
        self._last_smile_time = 0.0
        try:
            cascade_dir = cv2.data.haarcascades
            self._face_cascade = cv2.CascadeClassifier(
                cascade_dir + "haarcascade_frontalface_default.xml")
            self._smile_cascade = cv2.CascadeClassifier(
                cascade_dir + "haarcascade_smile.xml")
        except Exception:
            pass

        self.security = SecurityFeed()
        self.security.set_emotion_callback(self._on_security_emotion)
        self.security.start()

        # WiFi monitor
        self.wifi_monitor = WiFiMonitor()
        self.wifi_monitor.start()

        # WiFi defense (second adapter, if available)
        self.wifi_defense = None
        try:
            from .wifi_defense import WiFiDefense
            wd = WiFiDefense()
            if wd.available:
                wd.set_callback(self._on_wifi_attack)
                wd.start()
                self.wifi_defense = wd
                self._say("Defensa WiFi activa. Monitor mode ON.", C_TEXT_OK)
            else:
                print("[Entity] WiFi defense: no second adapter (wlan1) detected")
        except Exception as e:
            print(f"[Entity] WiFi defense not available: {e}")

        # AI Brain — real intelligence
        self.ai_brain = AIBrain()
        if self.ai_brain.available:
            self.ai_brain.set_callback(self._on_ai_thought)
            self.ai_brain.start()
            self._say("Cerebro IA activo. Razonamiento real.", C_TEXT_OK)
        else:
            print("[Entity] AI brain not available — using local phrases")

        # Home Assistant feed
        self.ha_feed = HAFeed()
        if self.ha_feed.available:
            self.ha_feed.start()
            self._say("Home Assistant conectado.", C_TEXT_OK)
        else:
            print("[Entity] Home Assistant not available")

        # Coffee Machine (ESPHome + HA)
        self.coffee = CoffeeMachine(
            ha_url=os.getenv("TOKIO_HA_URL", "http://localhost:8123"),
            ha_token=os.getenv("TOKIO_HA_TOKEN", ""),
        )
        if self.coffee.available:
            self.coffee.set_callback(self._on_coffee_event)
            self._say("Maquina de cafe conectada.", C_TEXT_OK)

        # Vision Filter — Claude teaches Hailo
        self.vision_filter = VisionFilter()

        # Connect filter to AI brain
        self.ai_brain.set_vision_filter(self.vision_filter)

        # Health Monitor — BLE smartwatch
        self._health_alerts = None  # init before health block
        self.health = HealthMonitor()
        if self.health.available:
            self.health.start()

            # Start health alerts monitoring
            if HealthAlerts:
                try:
                    self._health_alerts = HealthAlerts(self)
                    self._health_alerts.start()
                    print("[Entity] Health alerts monitoring started")
                except Exception as e:
                    print(f"[Entity] Health alerts failed: {e}")
            self._say("Monitor de salud BLE activo.", C_TEXT_OK)

        # BLE Security Monitor — Bluetooth attack detection
        self.ble_security = BLESecurityMonitor()
        self.ble_security.set_callback(self._on_ble_attack)
        self.ble_security.start()
        self._say("Monitor seguridad BLE activo.", C_TEXT_OK)

        # ── Threat Correlation Engine — unified threat intelligence ──
        self.threat_engine = ThreatCorrelationEngine(
            on_level_change=self._on_threat_level_change,
            on_insight=self._on_threat_insight,
        )
        # Wire up data sources
        self.threat_engine.set_sources(
            waf=lambda: self.security.get_latest() if self.security.connected else None,
            wifi=lambda: self.wifi_defense.get_stats().__dict__ if self.wifi_defense else None,
            ble=lambda: self.ble_security.get_stats() if self.ble_security else None,
        )
        self.threat_engine.start()

        # ── Adaptive Defense — autonomous security response ──
        self.adaptive_defense = AdaptiveDefense()
        self.adaptive_defense.set_handlers(
            emotion=lambda e: self.face.set_emotion(getattr(Emotion, e, Emotion.NEUTRAL)),
            face_glow=lambda c: setattr(self, '_threat_glow_color', c),
            say=lambda text, color: self._say(text, color),
        )
        # Link to threat engine
        self.threat_engine._on_level_change = self.adaptive_defense.on_level_change
        self.threat_engine._on_insight = self.adaptive_defense.on_insight
        self._threat_glow_color = (0, 255, 100)  # Default green
        self._say("Threat Correlation Engine activo. DEFCON 5.", C_TEXT_OK)

        # WPA2 Monitor — handshake capture, PMKID, KRACK detection
        self.wpa2_monitor = WPA2Monitor(
            protected_ssid=os.getenv("WIFI_PROTECTED_SSID", ""),
        )
        # Will be hooked into wifi_defense packet processing
        if self.wifi_defense:
            self.wpa2_monitor.set_callback(self._on_wpa2_attack)
            self._say("Monitor WPA2 activo.", C_TEXT_OK)

        # MAVLink Drone — ArduPilot/Pixhawk integration
        self.mavlink_drone = MAVLinkDrone(simulator=False)  # Real mode, connect via API

        # Stand mode — filters intimate content for public display
        self._stand_mode = False

        # Event persistence
        if EventStore:
            try:
                self.event_store = EventStore()
                print("[Entity] Event store initialized")
            except Exception as e:
                print(f"[Entity] Event store failed: {e}")
                self.event_store = None
        else:
            self.event_store = None

        # Health alerts
        # _health_alerts initialized in health block above
        self._stand_engine = None

        # Drone Vision Player (visual servoing — legacy camera-based)
        # NOT auto-started — conflicts with FPV. Only start via API when needed.
        self.drone_vision = DroneVisionPlayer()
        self.drone_vision.set_callback(self._on_drone_vision_event)

        # Drone FPV — Tello's own camera as Tokio's flying eye
        self.drone_fpv = DroneFPV()
        self.drone_fpv.set_callback(self._on_fpv_event)
        # Connect Hailo detector to FPV for person detection
        if self.vision:
            self.drone_fpv.set_external_detector(self._hailo_detect_persons)

        # Drone awareness
        self._drone_connected = False
        self._drone_flying = False
        self._drone_battery = -1
        self._drone_last_poll = 0.0

        self._boot_time = time.monotonic()
        self._pulse = 0.0

        # Robot fleet state (PiDog + PiCar)
        self._pidog_status = {}
        self._pidog_last_poll = 0.0
        self._picar_status = {}
        self._picar_last_poll = 0.0
        self._pidog_frame = None  # latest camera frame
        self._picar_frame = None

        # QR code — GitHub repo link
        self._qr_surface = self._generate_qr("https://github.com/TokioAI/tokioai-v1.8")

        # Start drone monitor thread
        threading.Thread(target=self._drone_monitor_loop, daemon=True).start()

        # Start robot fleet monitor thread
        threading.Thread(target=self._robot_monitor_loop, daemon=True).start()

        # Start HA health monitor thread
        threading.Thread(target=self._ha_health_loop, daemon=True).start()

        self._say("Tokio online. Todos los sistemas operativos.", C_TEXT_OK)

    def _init_vision(self):
        try:
            from .vision_engine import VisionEngine
            self.vision = VisionEngine(camera_id=0, model="detect")
            self.vision.start()
            self._say("Vision activada. Puedo ver.", C_TEXT_OK)
            self.face.set_emotion(Emotion.HAPPY, "I can see!")
        except Exception as e:
            self._say(f"Sin vision: {e}", C_TEXT_WARN)

    def _say(self, text: str, color: tuple = C_TEXT, source: str = "system"):
        self._voice_queue.append((text, color))
        self.thought_log.add(text, source=source)

    def _on_threat_level_change(self, old_level, new_level, score):
        """Called when DEFCON level changes."""
        names = {1: "MAXIMUM", 2: "HIGH", 3: "INCREASED", 4: "ELEVATED", 5: "PEACE"}
        colors = {1: (255, 0, 0), 2: (255, 100, 0), 3: (255, 180, 0),
                  4: (0, 200, 255), 5: (0, 255, 100)}
        level_name = names.get(new_level, "UNKNOWN")
        color = colors.get(new_level, (0, 255, 255))
        self._say(f"DEFCON {new_level}: {level_name}", color)
        self._threat_glow_color = color

    def _on_threat_insight(self, insight):
        """Called when a cross-vector correlation is detected."""
        color = (255, 40, 60) if insight.severity == "critical" else (255, 180, 0)
        self._say(f"CORRELATION: {insight.title}", color)


    def _update_voice(self):
        now = time.monotonic()
        if now - self._voice_time > 8.0 and self._voice_queue:
            text, color = self._voice_queue.pop(0)
            self._voice_text = text
            self._voice_color = color
            self._voice_time = now
        elif now - self._voice_time > 8.0 and not self._voice_queue:
            # Only use canned idle phrases if AI brain is NOT active
            if not self.ai_brain.available and random.random() < 0.02:
                stats = self.security.get_stats()
                msg = random.choice(SAY_IDLE).format(
                    blocked=stats.blocked, faces=self.face_db.count)
                self._voice_text = msg
                self._voice_color = C_TEXT_DIM
                self._voice_time = now
                self.face.set_emotion(Emotion.NEUTRAL, "Watching...")

    def _on_security_emotion(self, emotion_str: str, message: str):
        emo_map = {
            "angry": Emotion.ANGRY, "alert": Emotion.ALERT,
            "scanning": Emotion.SCANNING, "thinking": Emotion.THINKING,
            "excited": Emotion.EXCITED,
        }
        self.face.set_emotion(emo_map.get(emotion_str, Emotion.NEUTRAL), message)

        events = self.security.get_events(limit=1)
        if events:
            ev = events[-1]
            if ev.severity in ("critical", "high") and ev.blocked:
                threat = JP_THREATS.get(ev.threat_type, ev.threat_type or "ataque")
                self._say(random.choice(SAY_ATTACK).format(type=threat, ip=ev.ip), C_TEXT_DANGER, source="security")

        # Feed WAF events into Threat Correlation Engine
        if hasattr(self, "threat_engine") and self.threat_engine:
            events_for_threat = self.security.get_events(limit=5)
            for ev in events_for_threat:
                self.threat_engine.push_event(
                    "waf", ev.severity,
                    f"{ev.threat_type or 'unknown'}: {ev.method} {ev.uri} from {ev.ip}",
                    ev.blocked
                )

    def _on_wifi_attack(self, attack_type: str, message: str, severity: str):
        """React to WiFi attack detected by defense module."""
        if severity == "critical":
            self._say(f"ALERTA WIFI! {message}", C_WIFI_DANGER, source="wifi_defense")
            self.face.set_emotion(Emotion.ANGRY, "WiFi Attack!")
        elif severity == "high":
            self._say(message, C_WIFI_WARN, source="wifi_defense")
            self.face.set_emotion(Emotion.ALERT, "WiFi Defense")
        else:
            self._say(message, C_TEXT, source="wifi_defense")

        # Push to GCP core for centralized tracking + router defense
        _push_to_core("/entity/event", {
            "type": "wifi_attack",
            "attack_type": attack_type,
            "message": message,
            "severity": severity,
        })

        # Feed into Threat Correlation Engine
        if hasattr(self, "threat_engine") and self.threat_engine:
            self.threat_engine.push_event("wifi", severity, f"{attack_type}: {message}")


    def _on_ble_attack(self, attack_type: str, description: str):
        """React to Bluetooth attack detected by BLE security monitor."""
        severity_map = {
            "blueborne": ("critical", C_WIFI_DANGER, Emotion.ANGRY),
            "knob": ("critical", C_WIFI_DANGER, Emotion.ANGRY),
            "adv_flood": ("high", C_WIFI_WARN, Emotion.ALERT),
            "recon": ("medium", C_TEXT, Emotion.ALERT),
        }
        sev, color, emotion = severity_map.get(attack_type, ("medium", C_TEXT, Emotion.ALERT))
        self._say(f"BLE: {description}", color, source="ble_security")
        self.face.set_emotion(emotion, "BLE Attack!")

        # Feed into Threat Correlation Engine
        if hasattr(self, "threat_engine") and self.threat_engine:
            self.threat_engine.push_event("ble", sev, f"{attack_type}: {description}")

    def _on_wpa2_attack(self, attack_type: str, description: str):
        """React to WPA2 attack (handshake capture, PMKID, KRACK)."""
        self._say(f"WPA2: {description}", C_WIFI_DANGER, source="wpa2_monitor")
        self.face.set_emotion(Emotion.ANGRY, "WPA2 Attack!")

        # Feed into Threat Correlation Engine
        if hasattr(self, "threat_engine") and self.threat_engine:
            self.threat_engine.push_event("wifi", "critical", f"WPA2: {attack_type}: {description}")

    def _on_ai_thought(self, text: str, emotion: str):
        """Receive real AI analysis from Claude."""
        emo_map = {
            "happy": Emotion.HAPPY, "alert": Emotion.ALERT,
            "angry": Emotion.ANGRY, "curious": Emotion.CURIOUS,
            "thinking": Emotion.THINKING, "neutral": Emotion.NEUTRAL,
        }
        color = C_TEXT_BRIGHT
        if emotion == "alert":
            color = C_TEXT_WARN
        elif emotion == "happy":
            color = C_TEXT_OK
        elif emotion == "angry":
            color = C_TEXT_DANGER
        elif emotion == "curious":
            color = C_ACCENT

        # Store thought for API access (in-memory for quick access)
        self._thoughts.append((text, time.monotonic(), emotion))
        if len(self._thoughts) > self._max_thoughts:
            self._thoughts = self._thoughts[-self._max_thoughts:]

        self._say(text, color, source="ai_brain")
        self.face.set_emotion(emo_map.get(emotion, Emotion.NEUTRAL), text[:25])
        self.face.speak(0.5)

    # -------------------------------------------------------------------
    # Drone awareness
    # -------------------------------------------------------------------

    def _on_coffee_event(self, event_type: str, message: str):
        """React to coffee machine events."""
        if event_type == "brewing":
            self._say(message, C_ACCENT)
            self.face.set_emotion(Emotion.HAPPY, "Brewing coffee!")
        elif event_type == "ready":
            self._say(message, C_TEXT_OK)
            self.face.set_emotion(Emotion.EXCITED, "Coffee ready!")
        elif event_type == "error":
            self._say(message, C_TEXT_WARN)
            self.face.set_emotion(Emotion.ALERT, "Coffee error")

    def _on_drone_vision_event(self, event_type: str, message: str):
        """Handle drone vision events."""
        if event_type == "registered":
            self._say(message, (0, 255, 180))
            self.face.set_emotion(Emotion.EXCITED, "Drone registered!")
        elif event_type == "lost":
            self._say(message, (255, 100, 0))
            self.face.set_emotion(Emotion.ALERT, "Drone lost!")
        elif event_type == "close":
            self._say(message, (0, 200, 255))
        elif event_type == "dance":
            self._say(message, (180, 0, 255))
            self.face.set_emotion(Emotion.HAPPY, "Dancing!")
        elif event_type == "mode_change":
            self._say(message, (0, 255, 255))

    def _on_fpv_event(self, event_type: str, message: str):
        """Handle drone FPV events."""
        if event_type == "fpv_obstacle":
            self._say(f"Drone FPV: {message}", C_TEXT_DANGER, source="drone")
            self.face.set_emotion(Emotion.ALERT, "Obstacle!")
        elif event_type == "fpv_lost":
            self._say(f"Drone FPV: {message}", C_TEXT_WARN, source="drone")
            self.face.set_emotion(Emotion.CURIOUS, "Searching...")
        elif event_type == "fpv_found":
            self._say(f"Drone FPV: {message}", C_TEXT_OK, source="drone")
            self.face.set_emotion(Emotion.HAPPY, "Target found!")

    def _restart_service(self, service_name: str):
        """Restart a systemd service (auto-healing)."""
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", service_name],
                timeout=10, capture_output=True,
            )
            print(f"[AutoHeal] Restarted {service_name}")
        except Exception as e:
            print(f"[AutoHeal] Failed to restart {service_name}: {e}")

    def _restart_docker(self, container_name: str):
        """Restart a Docker container (auto-healing)."""
        try:
            subprocess.run(
                ["docker", "restart", container_name],
                timeout=30, capture_output=True,
            )
            print(f"[AutoHeal] Restarted Docker container {container_name}")
        except Exception as e:
            print(f"[AutoHeal] Failed to restart Docker {container_name}: {e}")

    def _ha_health_loop(self):
        """Monitor Home Assistant and auto-heal if it goes down."""
        import requests as req
        time.sleep(15)  # Wait for initial startup
        ha_fail_count = 0
        ha_was_available = False

        while self._running:
            try:
                # Check if HA feed is available
                if self.ha_feed.available:
                    if not ha_was_available:
                        self._say("Home Assistant conectado.", C_TEXT_OK)
                        ha_was_available = True
                    ha_fail_count = 0
                else:
                    # HA feed not available - check if HA Docker is running
                    try:
                        r = req.get("http://localhost:8123/api/", timeout=5,
                                    headers={"Authorization": f"Bearer {os.getenv("TOKIO_HA_TOKEN", "")}"}
                                   )
                        if r.status_code == 200:
                            # HA is running but feed lost connection - reconnect
                            ha_fail_count = 0
                            if not self.ha_feed.available:
                                print("[AutoHeal] HA running but feed disconnected, reconnecting...")
                                self.ha_feed.stop()
                                time.sleep(1)
                                # Re-init token
                                self.ha_feed._token = os.getenv("TOKIO_HA_TOKEN", "")
                                if self.ha_feed._token:
                                    self.ha_feed._available = self.ha_feed._test_connection()
                                    if self.ha_feed._available:
                                        self.ha_feed.start()
                                        self._say("Home Assistant reconectado.", C_TEXT_OK)
                                        ha_was_available = True
                        else:
                            ha_fail_count += 1
                    except Exception:
                        ha_fail_count += 1

                    # Auto-heal: restart HA Docker after 3 consecutive failures (~90s)
                    if ha_fail_count == 3:
                        print("[AutoHeal] Home Assistant down, restarting Docker container...")
                        self._say("HA caido, reiniciando...", C_TEXT_WARN)
                        self._restart_docker("homeassistant")
                        time.sleep(30)  # HA takes ~30s to start
                        # Try to reconnect feed
                        self.ha_feed._token = os.getenv("TOKIO_HA_TOKEN", "")
                        if self.ha_feed._token:
                            self.ha_feed._available = self.ha_feed._test_connection()
                            if self.ha_feed._available:
                                self.ha_feed.start()
                                self._say("Home Assistant restaurado.", C_TEXT_OK)
                                ha_was_available = True
                                ha_fail_count = 0
                    elif ha_fail_count > 6:
                        ha_fail_count = 0  # Reset, try again later

            except Exception as e:
                print(f"[AutoHeal] HA health check error: {e}")

            time.sleep(30)

    def _drone_monitor_loop(self):
        import requests as req
        time.sleep(5)
        proxy_fail_count = 0
        while self._running:
            try:
                r = req.get("http://127.0.0.1:5001/drone/status", timeout=3)
                if r.status_code == 200:
                    proxy_fail_count = 0
                    data = r.json()
                    was_connected = self._drone_connected
                    was_flying = self._drone_flying

                    self._drone_connected = data.get("connected", False)
                    armed = data.get("armed", False)

                    if self._drone_connected:
                        try:
                            br = req.post("http://127.0.0.1:5001/drone/command",
                                          json={"command": "battery", "params": {}}, timeout=5)
                            if br.status_code == 200:
                                result = br.json().get("result", "")
                                if "Battery:" in result:
                                    self._drone_battery = int(result.split(":")[1].strip().replace("%", ""))
                        except Exception:
                            pass

                    if self._drone_connected and not was_connected:
                        bat_str = f"{self._drone_battery}%" if self._drone_battery >= 0 else "?"
                        msg = random.choice(SAY_DRONE_CONNECTED).format(bat=bat_str)
                        self._say(msg, C_TEXT_OK)
                        self.face.set_emotion(Emotion.HAPPY, "Drone connected!")

                    if armed and not was_flying:
                        self._drone_flying = True
                        msg = random.choice(SAY_DRONE_TAKEOFF)
                        self._say(msg, C_ACCENT)
                        self.face.set_emotion(Emotion.EXCITED, "TAKEOFF!")
                        # Auto-start FPV stream on takeoff
                        self._start_fpv_stream()

                    elif not armed and was_flying:
                        self._drone_flying = False
                        msg = random.choice(SAY_DRONE_LAND)
                        self._say(msg, C_TEXT_OK)
                        self.face.set_emotion(Emotion.HAPPY, "Landed OK")
                        # Stop FPV on landing
                        self._stop_fpv_stream()

                    elif armed and was_flying:
                        if 0 < self._drone_battery < 20:
                            msg = random.choice(SAY_DRONE_LOWBAT).format(bat=self._drone_battery)
                            self._say(msg, C_TEXT_DANGER)
                            self.face.set_emotion(Emotion.ALERT, f"Low bat: {self._drone_battery}%")

                else:
                    self._drone_connected = False
            except Exception:
                self._drone_connected = False
                proxy_fail_count += 1
                # Auto-heal: restart proxy after 3 consecutive failures (~24s)
                if proxy_fail_count == 3:
                    print("[AutoHeal] Drone proxy not responding, restarting...")
                    self._say("Proxy drone caido, reiniciando...", C_TEXT_WARN)
                    self._restart_service("tokio-drone-proxy")
                elif proxy_fail_count > 6:
                    proxy_fail_count = 0  # reset, try again later

            time.sleep(DRONE_POLL_INTERVAL)

    def _robot_monitor_loop(self):
        """Poll PiDog and PiCar status + camera snapshots periodically."""
        import requests as req
        time.sleep(8)  # let other things boot first
        while self._running:
            # PiDog
            try:
                r = req.get("http://192.168.8.210:5001/status", timeout=3)
                if r.status_code == 200:
                    self._pidog_status = r.json()
                    self._pidog_last_poll = time.monotonic()
                    # Also get sensors
                    try:
                        sr = req.get("http://192.168.8.210:5001/sensors", timeout=3)
                        if sr.status_code == 200:
                            self._pidog_status.update(sr.json())
                    except Exception:
                        pass
                # Snapshot (every 5s)
                if time.monotonic() - self._pidog_last_poll < 2:
                    try:
                        sr = req.get("http://192.168.8.210:5001/snapshot", timeout=5)
                        if sr.status_code == 200 and sr.headers.get("content-type", "").startswith("image"):
                            import numpy as np
                            arr = np.frombuffer(sr.content, dtype=np.uint8)
                            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if frame is not None:
                                self._pidog_frame = frame
                    except Exception:
                        pass
            except Exception:
                self._pidog_status = {}

            # PiCar
            try:
                r = req.get("http://192.168.8.107:5002/status", timeout=3)
                if r.status_code == 200:
                    self._picar_status = r.json()
                    self._picar_last_poll = time.monotonic()
                # Snapshot
                if time.monotonic() - self._picar_last_poll < 2:
                    try:
                        sr = req.get("http://192.168.8.107:5002/snapshot", timeout=5)
                        if sr.status_code == 200 and sr.headers.get("content-type", "").startswith("image"):
                            import numpy as np
                            arr = np.frombuffer(sr.content, dtype=np.uint8)
                            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if frame is not None:
                                self._picar_frame = frame
                    except Exception:
                        pass
            except Exception:
                self._picar_status = {}

            time.sleep(5)

    def _hailo_detect_persons(self, frame):
        """Run Hailo inference on FPV frame and return person bboxes.

        Returns None when Hailo hasn't processed yet (caller uses cache),
        [] when processed but no persons, or list of bbox tuples.
        """
        if not self.vision or not self.vision._hailo_available:
            return None
        try:
            dets = self.vision.detect_external(frame)
            if dets is None:
                return None  # not processed yet — caller should use cache
            boxes = []
            for d in dets:
                if d.label == "person":
                    boxes.append((d.x1, d.y1, d.x2, d.y2))
            return boxes
        except Exception as e:
            print(f"[FPV-Hailo] Error: {e}")
            return None

    def _start_fpv_stream(self):
        """Start FPV: rise to 1.5m, enable stream, start FPV follow."""
        import requests as req
        try:
            # Rise to 1.5m first — at 80cm the person fills entire frame
            print("[FPV] Rising to 1.5m for better perspective...")
            r = req.post("http://127.0.0.1:5001/drone/command",
                      json={"command": "move", "params": {"direction": "up", "distance": 70}}, timeout=10)
            print(f"[FPV] move up 70 response: {r.text}")
            time.sleep(1)

            # Enable video stream
            r = req.post("http://127.0.0.1:5001/drone/command",
                      json={"command": "stream_on", "params": {}}, timeout=5)
            print(f"[FPV] stream_on response: {r.text}")
            time.sleep(1)

            # Start FPV receiver
            fpv_state = self.drone_fpv.get_state()
            if not fpv_state.streaming:
                self.drone_fpv.start_stream()
            self.drone_fpv.set_mode("follow")
            self._say("FPV activo. Ojo volador siguiendote.", C_TEXT_OK)
            print("[FPV] Started in FOLLOW mode at 1.5m height")
        except Exception as e:
            print(f"[FPV] Start error: {e}")

    def _stop_fpv_stream(self):
        """Stop FPV stream and send streamoff."""
        import requests as req
        try:
            self.drone_fpv.stop()
            req.post("http://127.0.0.1:5001/drone/command",
                      json={"command": "stream_off", "params": {}}, timeout=5)
        except Exception:
            pass

    # -------------------------------------------------------------------
    # Intelligence: process what Tokio sees
    # -------------------------------------------------------------------

    def _process_vision(self):
        if not self.vision:
            return

        frame = self.vision.get_frame()
        if frame is None:
            return

        now = time.monotonic()
        raw_detections = self.vision.get_detections()
        # Apply learned filter (Claude teaches Hailo)
        frame_h, frame_w = frame.shape[:2]
        detections = self.vision_filter.filter_detections(raw_detections, frame_w, frame_h)
        self._last_detections = detections

        # Update info bar labels
        if detections:
            self._info_labels = list({d.label for d in detections})
        else:
            self._info_labels = []

        # Update HUD on face
        self.face.hud_detections = len(detections)
        self.face.hud_fps = self.vision.get_fps()

        person_count = 0
        person_boxes = []
        self._person_boxes = []

        if detections:
            labels = {d.label for d in detections}

            # Precise person counting — dedup, filter noise, cross-validate with faces
            fh, fw = frame.shape[:2] if frame is not None else (SCREEN_H, SCREEN_W)
            # Dedup known faces by normalized name (aliases -> same person)
            _FACE_ALIASES_L = {
                "arquitecto sayayin": "Daniel",
                "mrmoz": "Daniel",
                "mr moz": "Daniel",
                "daletoniris": "Daniel",
            }
            _seen_names = set()
            for _, k, c in self._current_identities:
                if k and c > 0.3:
                    norm = _FACE_ALIASES_L.get(k.name.lower(), k.name)
                    _seen_names.add(norm)
            known_faces_now = len(_seen_names)
            person_count, person_boxes = count_persons_precise(
                detections,
                known_faces_count=known_faces_now,
                frame_w=fw, frame_h=fh,
            )
            self._person_boxes = person_boxes

            if person_count > 1:
                print(f"[PersonCount] {person_count} persons (known_faces={known_faces_now}, boxes={len(person_boxes)})")

            self.face.hud_persons = person_count

            # Threat objects — only announce if AI brain is offline
            threats = labels & THREAT_OBJECTS
            if threats:
                self.face.hud_threats += 1
                if not self.ai_brain.available:
                    obj = ", ".join(threats)
                    self._say(random.choice(SAY_THREAT).format(obj=obj), C_TEXT_DANGER)
                    self.face.set_emotion(Emotion.ANGRY, f"THREAT: {obj}")

            # Person count changes
            self._person_count = person_count

            # Eyes follow biggest detection
            biggest = max(detections, key=lambda d: d.area)
            cx, cy = biggest.center
            fh, fw = frame.shape[:2]
            # Mirror X so eyes follow user's physical direction
            self.face.look_at(-(cx / fw - 0.5) * 2, (cy / fh - 0.5) * 2)

        # Face recognition — run in background thread to avoid blocking render
        if now - self._last_recog_time > FACE_RECOG_INTERVAL:
            if not getattr(self, '_face_recog_busy', False):
                self._last_recog_time = now
                self._face_recog_busy = True
                frame_copy = frame.copy()
                import threading
                threading.Thread(
                    target=self._do_face_recognition_bg,
                    args=(frame_copy, now),
                    daemon=True,
                ).start()

        # Gesture detection — pass person boxes to constrain search
        if now - self._last_gesture_time > GESTURE_COOLDOWN:
            result = self.gesture.detect(frame, person_boxes=person_boxes if person_boxes else None)
            if result and result.gesture != Gesture.NONE and result.confidence > 0.85:
                self._last_gesture = result.gesture
                self._last_gesture_time = now

                # Only announce gestures if AI brain is offline
                if not self.ai_brain.available:
                    reactions = GESTURE_REACTIONS.get(result.gesture, [])
                    if reactions:
                        self._say(random.choice(reactions), C_GESTURE)

                icon = GESTURE_ICONS.get(result.gesture, "?")
                self.face.set_emotion(Emotion.EXCITED, f"Gesture: {icon}")

        # Smile detection
        if (self._smile_cascade is not None and self._face_cascade is not None
                and now - self._last_smile_time > SMILE_COOLDOWN):
            self._detect_smile(frame, now)

        # Feed AI brain with current frame + context
        if self.ai_brain.available:
            det_labels = [d.label for d in detections] if detections else []
            context = {
                "person_count": person_count,
                "known_face": "",
                "gesture": "",
                "waf_attacks": self.security.get_stats().total_attacks,
            }
            # Add known face info (use _info_face as it persists across recognition cycles)
            # Normalize aliases: all Daniel's face_db names -> "Daniel"
            _FACE_ALIASES = {
                "arquitecto sayayin": "Daniel",
                "mrmoz": "Daniel",
                "mr moz": "Daniel",
                "daletoniris": "Daniel",
            }
            if self._info_face and self._info_face != "???" and now - self._info_face_time < 15:
                context["known_face"] = _FACE_ALIASES.get(self._info_face.lower(), self._info_face)
            else:
                for _, known, _ in self._current_identities:
                    if known:
                        name = _FACE_ALIASES.get(known.name.lower(), known.name)
                        context["known_face"] = name
                        break
            # Add gesture info
            if self._last_gesture != Gesture.NONE and now - self._last_gesture_time < GESTURE_COOLDOWN:
                context["gesture"] = self._last_gesture.value
            # Add smile
            if now - self._last_smile_time < SMILE_COOLDOWN:
                context["smile"] = True
            # Add WiFi defense context
            if self.wifi_defense:
                wstats = self.wifi_defense.get_stats()
                if wstats.deauth_detected > 0:
                    context["wifi_deauth"] = wstats.deauth_detected
                if wstats.evil_twins > 0:
                    context["wifi_evil_twins"] = wstats.evil_twins
            # Add HA context (music, sensors)
            if self.ha_feed.available:
                playing = self.ha_feed.get_now_playing()
                if playing:
                    context["music"] = playing
                sensors = self.ha_feed.get_sensors()
                for sid, sdata in sensors.items():
                    if "weather" in sid or "forecast" in sid:
                        # Weather entity — this is OUTDOOR temp from met.no
                        wtemp = sdata.get("temperature")
                        if wtemp is not None:
                            context["temp_exterior"] = f"{wtemp}°C"
                    elif "temperatura" in sid or "temperature" in sid:
                        # Direct sensor — this is INDOOR temp
                        context["temp_interior"] = f"{sdata['state']}{sdata.get('unit', '')}"
            self.ai_brain.update_frame(frame, det_labels, context)

            # Coffee machine context
            if self.coffee.available:
                coffee_text = self.coffee.get_status_text()
                if coffee_text and coffee_text != "unknown":
                    context["coffee_status"] = coffee_text
            # Health monitor context
            if self.health.available:
                health_ctx = self.health.get_health_context()
                if health_ctx:
                    context["health"] = health_ctx
            # Drone context for AI brain
            if self._drone_flying:
                context["drone_flying"] = True
                context["drone_battery"] = self._drone_battery
            # Drone vision: feed frame for visual tracking (legacy camera-based)
            if self.drone_vision.mode != DronePlayMode.IDLE:
                drone_state = self.drone_vision.process_frame(frame, person_boxes=self._person_boxes)
                if drone_state and drone_state.detected:
                    context["drone_distance"] = f"{drone_state.distance_cm:.0f}cm"
                    context["drone_mode"] = self.drone_vision.mode.value
            # Drone FPV context — what the drone's camera sees
            fpv_state = self.drone_fpv.get_state()
            if fpv_state.streaming:
                context.update(self.drone_fpv.get_context_for_brain())

    def _do_face_recognition_bg(self, frame, now):
        """Background wrapper — runs face recognition without blocking render."""
        try:
            self._do_face_recognition(frame, now)
        except Exception as e:
            print(f"[FaceRecog] Error: {e}")
        finally:
            self._face_recog_busy = False

    def _do_face_recognition(self, frame, now):
        # Strategy: use Hailo person boxes to extract head regions,
        # then identify via Gemini Flash (cloud) with local caching.
        # Falls back to dlib face_db if Gemini is not available.
        face_rects = []
        fh, fw = frame.shape[:2]

        # Copy person_boxes to avoid race condition (main thread may update it)
        person_boxes = list(self._person_boxes) if self._person_boxes else []

        if person_boxes:
            # Extract head region from each person bbox (upper 40% = head area)
            for (x1, y1, x2, y2) in person_boxes:
                pw = x2 - x1
                ph = y2 - y1
                if pw < 30 or ph < 40:
                    continue
                head_x = x1 + int(pw * 0.15)
                head_y = y1
                head_w = int(pw * 0.70)
                head_h = int(ph * 0.40)
                head_x = max(0, head_x)
                head_y = max(0, head_y)
                if head_x + head_w > fw:
                    head_w = fw - head_x
                if head_y + head_h > fh:
                    head_h = fh - head_y
                if head_w > 20 and head_h > 20:
                    face_rects.append((head_x, head_y, head_w, head_h))

        if not face_rects:
            self._current_identities = []
            return

        source = "hailo"
        print(f"[FaceRecog] {len(face_rects)} face rects from {source}")

        identities = []

        # Use Gemini Flash identifier (primary) or dlib face_db (fallback)
        use_gemini = self.face_identifier.available

        for rect in face_rects:
            if use_gemini:
                person = self.face_identifier.identify(frame, rect)
                if person and person.name != "unknown":
                    # Create a mock "known" object compatible with existing code
                    known = type("Known", (), {
                        "name": person.name,
                        "role": person.role,
                        "is_admin": person.role == "creator",
                        "face_id": f"gemini_{person.name.lower()}",
                    })()
                    identities.append((rect, known, person.confidence))
                elif person:
                    identities.append((rect, None, 0.0))
                else:
                    # Gemini didn't respond (rate limited or cache miss pending)
                    # Check cache or use persistence
                    identities.append((rect, None, 0.0))
            else:
                # Fallback to dlib
                known, conf = self.face_db.recognize(frame, rect)
                identities.append((rect, known, conf))

        # Deduplicate overlapping identities
        if len(identities) > 1:
            deduped = []
            used = set()
            sorted_ids = sorted(enumerate(identities), key=lambda x: x[1][2], reverse=True)
            for idx, (rect, known, conf) in sorted_ids:
                if idx in used:
                    continue
                rx, ry, rw, rh = rect
                duplicate = False
                for kept_idx in range(len(deduped)):
                    kx, ky, kw, kh = deduped[kept_idx][0]
                    cx1, cy1 = rx + rw // 2, ry + rh // 2
                    cx2, cy2 = kx + kw // 2, ky + kh // 2
                    dist = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
                    max_dim = max(rw, rh, kw, kh)
                    if dist < max_dim * 0.5:
                        duplicate = True
                        break
                if not duplicate:
                    deduped.append((rect, known, conf))
                    used.add(idx)
            identities = deduped

        # Identity persistence: keep last known for 8s
        IDENTITY_PERSIST_SECS = 8.0
        if identities and self._info_face and self._info_face != "???" and \
                now - self._info_face_time < IDENTITY_PERSIST_SECS:
            new_identities = []
            for rect, known, conf in identities:
                if known is None:
                    # Create persistence mock from last known name
                    persist = type("Known", (), {
                        "name": self._info_face,
                        "role": "visitor",
                        "is_admin": self._info_face.lower() == "daniel",
                        "face_id": f"persist_{self._info_face.lower()}",
                    })()
                    new_identities.append((rect, persist, 0.5))
                else:
                    new_identities.append((rect, known, conf))
            identities = new_identities

        self._current_identities = identities

        # Feed unknown persons to Threat Correlation Engine
        if hasattr(self, "threat_engine") and self.threat_engine:
            unknown_count = sum(1 for _, k, _ in identities if k is None)
            if unknown_count > 0:
                self.threat_engine.push_event(
                    "vision", "medium",
                    f"{unknown_count} unknown person(s) detected in camera"
                )

        if self._register_mode and face_rects:
            if now - self._register_start > 15:
                self._register_mode = False
                self._say("Registro cancelado. Timeout.", C_TEXT_DIM)
            else:
                # Registration: add to Gemini identifier's known people
                if self.face_identifier.available:
                    self.face_identifier.add_known_person(
                        self._register_name, self._register_role,
                        f"Registered at {time.strftime('%H:%M')}")
                    self._say(f"Registrado: {self._register_name} en Gemini.",
                              C_ADMIN_GOLD if self._register_role == "admin" else C_TEXT_OK)
                    self.face.set_emotion(Emotion.HAPPY, f"Saved: {self._register_name}")
                else:
                    # Fallback to dlib registration
                    new = self.face_db.register_face(
                        frame, face_rects[0], self._register_name, self._register_role)
                    if new:
                        role_text = "ADMIN SUPREMO" if new.is_admin else new.role
                        self._say(f"Registrado: {new.name} como {role_text}. Ya te recuerdo!",
                                  C_ADMIN_GOLD if new.is_admin else C_TEXT_OK)
                        self.face.set_emotion(Emotion.HAPPY, f"Saved: {new.name}")
                self._register_mode = False
            return

        for rect, known, conf in identities:
            if known:
                self._info_face = known.name
                self._info_face_time = now
                last = self._greeted_faces.get(known.face_id, 0)
                if now - last > 30:
                    self._greeted_faces[known.face_id] = now
                    if not self.ai_brain.available:
                        if known.is_admin:
                            self._say(random.choice(GREET_ADMIN), C_ADMIN_GOLD)
                        else:
                            self._say(random.choice(GREET_KNOWN).format(name=known.name), C_TEXT_OK)
                    if known.is_admin:
                        self.face.set_emotion(Emotion.EXCITED, f"BOSS: {known.name}!")
                    else:
                        self.face.set_emotion(Emotion.HAPPY, known.name)
            else:
                self._info_face = "???"
                self._info_face_time = now
                if now - self._greeted_faces.get(-1, 0) > 20:
                    self._greeted_faces[-1] = now
                    if not self.ai_brain.available:
                        self._say(random.choice(GREET_UNKNOWN), C_TEXT_WARN)
                    self.face.set_emotion(Emotion.CURIOUS, "Who?")

    def _detect_smile(self, frame, now):
        """Detect smiles using Haar cascade on detected face regions."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Use face regions from face_db if available, else detect
        face_rects = [(fx, fy, fw, fh) for fx, fy, fw, fh in
                      (r for r in [f[0] for f in self._current_identities] if r)]
        if not face_rects:
            faces = self._face_cascade.detectMultiScale(gray, 1.3, 5, minSize=(60, 60))
            face_rects = [(x, y, w, h) for x, y, w, h in faces]

        for fx, fy, fw, fh in face_rects[:3]:
            # Look for smile in lower half of face
            roi = gray[fy + fh // 2:fy + fh, fx:fx + fw]
            if roi.size == 0:
                continue
            smiles = self._smile_cascade.detectMultiScale(
                roi, scaleFactor=1.7, minNeighbors=22, minSize=(25, 15))
            if len(smiles) > 0:
                self._last_smile_time = now
                if not self.ai_brain.available:
                    self._say(random.choice(SAY_SMILE), C_TEXT_OK)
                self.face.set_emotion(Emotion.HAPPY, "Smile! :)")
                break

    def start_register(self, name: str, role: str = "visitor"):
        self._register_mode = True
        self._register_name = name
        self._register_role = role
        self._register_start = time.monotonic()
        self._say(f"Modo registro. Buscando cara de {name}...", C_TEXT_BRIGHT)
        self.face.set_emotion(Emotion.SCANNING, f"Scanning: {name}")

    # -------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------

    def _draw_face_fullscreen(self):
        self.face.render(self.screen, 0, 0)

    def _draw_camera_pip(self):
        if not self.vision:
            return

        frame = self.vision.get_frame()
        if frame is None:
            return

        annotated = frame.copy()
        detections = self.vision.get_detections()
        if detections:
            from .vision_engine import draw_detections
            # Don't draw Hailo "person" boxes — face recognition draws its own identity boxes
            # This prevents duplicate overlapping boxes for the same person
            filtered = [d for d in detections if d.label != "person"]
            annotated = draw_detections(annotated, filtered)

        # Draw face identity boxes (one per recognized person)
        for rect_data in self._current_identities:
            frect, known, conf = rect_data
            fx, fy, fw, fh = frect
            if known:
                color = (0, 215, 255) if known.is_admin else (0, 255, 100)
                label = f"{known.name}"
            else:
                color = (0, 180, 255)
                label = "???"
            cv2.rectangle(annotated, (fx, fy), (fx + fw, fy + fh), color, 2)
            cv2.putText(annotated, label, (fx, fy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (PIP_W, PIP_H))
        surf = pygame.surfarray.make_surface(np.transpose(resized, (1, 0, 2)))

        border_rect = pygame.Rect(PIP_X - 2, PIP_Y - 2, PIP_W + 4, PIP_H + 4)
        pygame.draw.rect(self.screen, C_BG, border_rect)
        self.screen.blit(surf, (PIP_X, PIP_Y))
        pygame.draw.rect(self.screen, C_BORDER_HI, border_rect, 2)

        # Corner brackets
        cl = 10
        for cx, cy in [(PIP_X, PIP_Y), (PIP_X + PIP_W, PIP_Y),
                        (PIP_X, PIP_Y + PIP_H), (PIP_X + PIP_W, PIP_Y + PIP_H)]:
            dx = 1 if cx == PIP_X else -1
            dy = 1 if cy == PIP_Y else -1
            pygame.draw.line(self.screen, C_TEXT_BRIGHT, (cx, cy), (cx + dx * cl, cy), 2)
            pygame.draw.line(self.screen, C_TEXT_BRIGHT, (cx, cy), (cx, cy + dy * cl), 2)

        self.screen.blit(self.font_pip_label.render("EYE", True, C_TEXT_DIM), (PIP_X + 4, PIP_Y + 3))
        fps = self.vision.get_fps()
        self.screen.blit(self.font_tiny.render(f"{fps:.0f}fps", True, C_TEXT),
                         (PIP_X + PIP_W - 42, PIP_Y + 3))

        # Detection count badge
        det_count = len(detections) if detections else 0
        if det_count > 0:
            badge = self.font_tiny.render(f"{det_count} obj", True, C_TEXT_OK)
            self.screen.blit(badge, (PIP_X + 4, PIP_Y + PIP_H - 16))

        # Live dot
        now = time.monotonic()
        if int(now * 2) % 2:
            pygame.draw.circle(self.screen, C_LIVE_DOT, (PIP_X + PIP_W - 8, PIP_Y + 8), 4)

        # Register mode flash
        if self._register_mode and int(now * 3) % 2:
            reg_surf = self.font_register.render(
                f"REGISTRANDO: {self._register_name}", True, C_ACCENT2)
            rx = PIP_X + PIP_W // 2 - reg_surf.get_width() // 2
            self.screen.blit(reg_surf, (rx, PIP_Y + PIP_H + 8))

    def _draw_waf_sidebar(self) -> int:
        """WAF attack feed — top-left. Returns bottom Y position."""
        events = self.security.get_events(limit=8)
        stats = self.security.get_stats()

        now = time.monotonic()
        x, y = 10, PIP_MARGIN + 5
        n_events = min(4, len(events)) if events else 0
        sidebar_h = n_events * 18 + 36
        sidebar_w = 350

        # Panel background
        sidebar_surf = pygame.Surface((sidebar_w, sidebar_h), pygame.SRCALPHA)
        sidebar_surf.fill((4, 8, 20, 235))
        self.screen.blit(sidebar_surf, (x - 5, y - 5))

        # Border glow
        has_critical = events and any(e.severity == "critical" for e in events[-3:])
        border_color = C_TEXT_DANGER if has_critical and int(now * 3) % 2 else C_BORDER_HI
        pygame.draw.rect(self.screen, border_color,
                         (x - 5, y - 5, sidebar_w, sidebar_h), 1)

        # Header
        hdr_color = C_TEXT_DANGER if has_critical else C_TEXT_BRIGHT
        hdr = self.font_panel_header.render("WAF DEFENSE", True, hdr_color)
        self.screen.blit(hdr, (x + 2, y))

        blocked_color = C_TEXT_OK if stats.blocked > 0 else C_TEXT_DIM
        blocked_text = self.font_panel_body.render(
            f"BLK:{stats.blocked} ATK:{stats.total_attacks}", True, blocked_color)
        self.screen.blit(blocked_text, (x + 170, y + 2))
        y += 20

        # Divider
        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + sidebar_w - 15, y), 1)
        y += 3

        if events:
            for event in events[-n_events:]:
                sev_colors = {
                    "critical": C_TEXT_DANGER, "high": C_TEXT_WARN,
                    "medium": (255, 255, 80), "low": C_TEXT_BRIGHT, "info": C_TEXT,
                }
                color = sev_colors.get(event.severity, C_TEXT)

                dot_color = C_TEXT_OK if event.blocked else C_TEXT_DANGER
                pygame.draw.circle(self.screen, dot_color, (x + 6, y + 7), 3)

                ts = event.timestamp.split(" ")[1][:5] if " " in event.timestamp else ""
                threat = (event.threat_type or "")[:7]
                ip = event.ip[:15]

                line = f" {ts} {ip} {threat}"
                surf = self.font_panel_body.render(line, True, color)
                self.screen.blit(surf, (x + 14, y))
                y += 16

        return y + 8

    def _draw_wifi_panel(self, y_start: int = 220) -> int:
        """WiFi 2.4GHz security — animated radar with real-time attack feed."""
        networks, alerts = self.wifi_monitor.get_data()
        now = time.monotonic()
        now_epoch = time.time()

        x = 10
        panel_w = 350
        defense_active = self.wifi_defense is not None

        # Gather attack data
        recent_attacks = []
        def_stats = None
        if defense_active:
            def_stats = self.wifi_defense.get_stats()
            recent_attacks = self.wifi_defense.get_attack_log(10)

        # Active attacks in last 60s for timeline
        active_attacks = [a for a in recent_attacks if now_epoch - a.get("time", 0) < 120]

        # Only show "under attack" if there are RECENT attacks (last 60s), not cumulative counters
        has_wifi_attacks = len(active_attacks) > 0
        has_alerts = len(alerts) > 0
        under_attack = has_wifi_attacks or has_alerts

        # Panel sizing
        n_alerts = min(3, len(alerts))
        n_attacks = min(3, len(active_attacks))
        n_nets = min(3, len(networks))
        radar_h = 70  # mini radar visualization
        content_lines = n_alerts + n_attacks + n_nets
        panel_h = 28 + radar_h + content_lines * 16 + 12
        panel_h = max(100, panel_h)

        # Panel background with glow effect during attacks
        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        if under_attack:
            # Pulsing red tint during attack
            pulse = int(20 + 15 * math.sin(now * 4))
            panel_surf.fill((pulse, 4, 8, 240))
        else:
            panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))

        # Glowing border during attacks
        if under_attack:
            glow_alpha = int(180 + 75 * math.sin(now * 3))
            border_color = (min(255, glow_alpha), 40, 40)
            pygame.draw.rect(self.screen, border_color,
                             (x - 5, y_start - 5, panel_w, panel_h), 2)
            # Outer glow
            glow_surf = pygame.Surface((panel_w + 4, panel_h + 4), pygame.SRCALPHA)
            glow_c = int(60 * math.sin(now * 3) + 60)
            pygame.draw.rect(glow_surf, (255, 30, 30, glow_c),
                             (0, 0, panel_w + 4, panel_h + 4), 3)
            self.screen.blit(glow_surf, (x - 7, y_start - 7))
        else:
            border_color = C_BORDER_HI
            pygame.draw.rect(self.screen, border_color,
                             (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start

        # Header with animated shield icon
        if defense_active:
            if under_attack:
                hdr_color = C_WIFI_DANGER if int(now * 3) % 2 else C_WIFI_WARN
                shield = "[!]" if int(now * 4) % 2 else "[X]"
            else:
                hdr_color = C_WIFI_OK
                shield = "[=]"
            total_atk = (def_stats.deauth_detected + def_stats.evil_twins +
                         def_stats.mitigations_applied) if def_stats else 0
            hdr_text = f"{shield} WIFI DEFENSE"
        else:
            hdr_color = C_WIFI_DANGER if has_alerts and int(now * 2) % 2 else C_WIFI_OK
            shield = ">>>" if has_alerts else "|||"
            hdr_text = f"{shield} WIFI 2.4GHz [{len(networks)}]"

        hdr = self.font_panel_header.render(hdr_text, True, hdr_color)
        self.screen.blit(hdr, (x + 2, y))

        if defense_active and def_stats:
            atk_text = f"D:{def_stats.deauth_detected} T:{def_stats.evil_twins} M:{def_stats.mitigations_applied}"
            atk_color = C_WIFI_DANGER if has_wifi_attacks else C_TEXT_OK
            atk_surf = self.font_panel_body.render(atk_text, True, atk_color)
            self.screen.blit(atk_surf, (x + panel_w - atk_surf.get_width() - 10, y + 2))
        y += 20
        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        # --- Mini Radar Visualization ---
        radar_cx = x + 55
        radar_cy = y + radar_h // 2
        radar_r = 28

        # Radar circles (concentric)
        for r_mult in [1.0, 0.66, 0.33]:
            r = int(radar_r * r_mult)
            pygame.draw.circle(self.screen, (0, 60, 50, 80), (radar_cx, radar_cy), r, 1)

        # Radar sweep line (rotating)
        sweep_angle = (now * 1.5) % (2 * math.pi)
        sx = radar_cx + int(radar_r * math.cos(sweep_angle))
        sy = radar_cy + int(radar_r * math.sin(sweep_angle))
        sweep_color = C_WIFI_DANGER if under_attack else C_WIFI_OK
        pygame.draw.line(self.screen, sweep_color, (radar_cx, radar_cy), (sx, sy), 2)

        # Radar trail (fading arc behind sweep)
        for i in range(8):
            trail_angle = sweep_angle - i * 0.15
            tx = radar_cx + int(radar_r * 0.9 * math.cos(trail_angle))
            ty = radar_cy + int(radar_r * 0.9 * math.sin(trail_angle))
            alpha = max(20, 120 - i * 15)
            trail_color = (0, alpha, int(alpha * 0.7)) if not under_attack else (alpha, 20, 20)
            pygame.draw.circle(self.screen, trail_color, (tx, ty), 2)

        # Network dots on radar (positioned by signal strength)
        for i, net in enumerate(networks[:8]):
            sig = net.get("signal", 50)
            angle = (i * 0.785) + now * 0.1  # slowly rotating
            dist = radar_r * (1.0 - sig / 100.0)
            nx = radar_cx + int(dist * math.cos(angle))
            ny = radar_cy + int(dist * math.sin(angle))
            dot_color = C_WIFI_OK if net.get("security") else C_WIFI_DANGER
            pygame.draw.circle(self.screen, dot_color, (nx, ny), 3)

        # Attack pulse rings (expanding circles for recent attacks)
        for atk in active_attacks[:3]:
            age = now_epoch - atk.get("time", 0)
            if age < 30:
                pulse_r = int(radar_r * 0.3 + (age * 2) % radar_r)
                pulse_alpha = max(30, 180 - int(age * 6))
                pulse_color = (255, 50, 50) if atk.get("type") == "deauth" else (255, 180, 50)
                pygame.draw.circle(self.screen, pulse_color,
                                   (radar_cx, radar_cy), pulse_r, 1)

        # Stats next to radar
        rx = radar_cx + radar_r + 15
        ry = y + 4
        net_label = self.font_panel_body.render(f"REDES: {len(networks)}", True, C_TEXT_BRIGHT)
        self.screen.blit(net_label, (rx, ry))
        ry += 14
        if defense_active and def_stats:
            status_text = "ACTIVO" if def_stats.monitoring else "INACTIVO"
            status_color = C_TEXT_OK if def_stats.monitoring else C_TEXT_DANGER
            self.screen.blit(self.font_panel_body.render(
                f"MONITOR: {status_text}", True, status_color), (rx, ry))
            ry += 14
            self.screen.blit(self.font_panel_body.render(
                f"CANAL: 1-11 hop", True, C_TEXT_DIM), (rx, ry))
            ry += 14
            if has_wifi_attacks:
                blink = int(now * 4) % 2
                if blink:
                    self.screen.blit(self.font_panel_body.render(
                        "!! BAJO ATAQUE !!", True, C_WIFI_DANGER), (rx, ry))
        else:
            open_nets = sum(1 for n in networks if not n.get("security"))
            if open_nets:
                self.screen.blit(self.font_panel_body.render(
                    f"ABIERTAS: {open_nets}", True, C_WIFI_DANGER), (rx, ry))
                ry += 14

        y += radar_h

        # --- Attack Timeline ---
        if active_attacks:
            pygame.draw.line(self.screen, (80, 20, 20), (x, y), (x + panel_w - 15, y), 1)
            y += 2
            for atk in active_attacks[:n_attacks]:
                age = now_epoch - atk.get("time", 0)
                atk_type = atk.get("type", "?").upper()[:10]
                mac_short = atk.get("attacker", "??:??")[-8:]
                mitigated = atk.get("mitigated", False)

                # Color based on type and freshness
                if age < 10:
                    line_color = C_WIFI_DANGER if int(now * 5) % 2 else (255, 255, 255)
                elif age < 30:
                    line_color = C_WIFI_DANGER
                else:
                    line_color = C_WIFI_WARN

                age_text = f"{int(age)}s" if age < 60 else f"{int(age / 60)}m"
                status = "OK" if mitigated else "!!"
                text = f" {status} {atk_type} {mac_short} [{age_text}]"
                surf = self.font_panel_body.render(text, True, line_color)
                self.screen.blit(surf, (x + 2, y))
                y += 16

        # WiFi monitor alerts
        for alert in alerts[-n_alerts:]:
            if alert["type"] == "EVIL_TWIN":
                alert_color = C_WIFI_DANGER
                icon = "!!!"
            elif alert["type"] == "SIG_ANOMALY":
                alert_color = C_WIFI_WARN
                icon = "/!\\"
            else:
                alert_color = C_WIFI_WARN
                icon = "[!]"
            text = f"{icon} {alert['msg'][:28]}"
            surf = self.font_panel_body.render(text, True, alert_color)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # Networks (compact, top 3 by signal)
        sorted_nets = sorted(networks, key=lambda n: n["signal"], reverse=True)
        for net in sorted_nets[:n_nets]:
            ssid = net.get("ssid", "")[:11] or "(hidden)"
            sig = net.get("signal", 0)
            sec = net.get("security", "")
            sec_label = "WPA" if sec else "OPEN"

            sig_color = C_WIFI_OK if sig > 60 else C_WIFI_WARN if sig > 30 else C_TEXT
            sec_color = C_WIFI_DANGER if not sec else C_TEXT

            bar_w = max(2, int(sig * 0.35))
            pygame.draw.rect(self.screen, sig_color, (x + 130, y + 3, bar_w, 8))

            text = f"{ssid:<11} {sig:3d}%"
            surf = self.font_panel_body.render(text, True, C_TEXT_BRIGHT)
            self.screen.blit(surf, (x + 2, y))

            sec_surf = self.font_panel_body.render(sec_label, True, sec_color)
            self.screen.blit(sec_surf, (x + panel_w - 45, y))
            y += 16

        return y + 8

    def _draw_ha_panel(self, y_start: int = 460) -> int:
        """Home Assistant panel. Returns bottom Y position."""
        if not self.ha_feed.available:
            return y_start

        x = 10
        panel_w = 350

        media = self.ha_feed.get_media()
        sensors = self.ha_feed.get_sensors()
        devices = self.ha_feed.get_devices()

        playing = None
        for eid, info in media.items():
            if info.get("state") == "playing":
                playing = info
                break
        active_devices = {k: v for k, v in devices.items() if v.get("state") == "on"}
        temp_sensors = {k: v for k, v in sensors.items()
                        if "temperatura" in k or "temperature" in k}
        weather = {k: v for k, v in sensors.items() if k.startswith("weather.")}

        lines = 1  # header
        if playing:
            lines += 2
        lines += min(1, len(temp_sensors)) + min(1, len(active_devices))
        # Weather: condition line + temperature line
        if weather:
            lines += 1  # CLIMA line
            wfirst = next(iter(weather.values()), {})
            if wfirst.get("temperature") is not None:
                lines += 1  # EXT temperature line

        if lines <= 1:
            return y_start

        panel_h = 24 + lines * 16 + 6
        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))

        pygame.draw.rect(self.screen, C_ACCENT,
                         (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start
        hdr = self.font_panel_header.render("HOME ASSISTANT", True, C_ACCENT)
        self.screen.blit(hdr, (x + 2, y))
        y += 20
        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        if playing:
            title = playing.get("title", "")[:22]
            artist = playing.get("artist", "")[:16]
            vol = int(playing.get("volume", 0) * 100)
            name = playing.get("name", "Alexa")

            music_line = f"  {title}" if title else f"  {name}"
            surf = self.font_panel_body.render(music_line, True, C_TEXT_BRIGHT)
            self.screen.blit(surf, (x + 2, y))
            y += 16
            if artist:
                surf = self.font_panel_body.render(
                    f"  {artist}  vol:{vol}%", True, C_ACCENT)
                self.screen.blit(surf, (x + 2, y))
                y += 16

        # Interior temperature (sensor) — mark stale if >1hr old
        for sid, sdata in list(temp_sensors.items())[:1]:
            text = f"  CASA: {sdata['state']}{sdata.get('unit', '')}"
            color = C_TEXT_BRIGHT
            lu = sdata.get("last_updated", "")
            if lu:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(lu.replace("Z", "+00:00"))
                    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                    if age_h > 1:
                        text += f" ({int(age_h)}h ago)"
                        color = C_TEXT_DIM
                except Exception:
                    pass
            surf = self.font_panel_body.render(text, True, color)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # Exterior temperature + weather (always shown)
        for wid, wdata in list(weather.items())[:1]:
            if wdata.get("temperature") is not None:
                temp_text = f"  EXT: {wdata['temperature']}°C"
                if wdata.get("humidity"):
                    temp_text += f"  H:{wdata['humidity']}%"
                surf = self.font_panel_body.render(temp_text, True, C_ACCENT)
                self.screen.blit(surf, (x + 2, y))
                y += 16
            cond = wdata.get("condition", wdata.get("state", ""))
            text = f"  CLIMA: {cond}"
            if wdata.get("wind_speed"):
                text += f" V:{wdata['wind_speed']}km/h"
            surf = self.font_panel_body.render(text[:32], True, C_TEXT_BRIGHT)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        for did, ddata in list(active_devices.items())[:1]:
            text = f"  {ddata['name'][:18]}: ON"
            surf = self.font_panel_body.render(text, True, C_TEXT_OK)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        return y + 8

    def _draw_coffee_panel(self, y_start: int = 620) -> int:
        """Coffee machine status panel. Returns bottom Y position."""
        if not self.coffee.available:
            return y_start

        x = 10
        panel_w = 350

        status = self.coffee.get_status()
        brewing = status["brewing"]
        current = status["current_drink"]
        served = status["drinks_served"]
        machine_status = status["status"]

        lines = 2
        if brewing:
            lines += 1
        panel_h = 24 + lines * 16 + 6

        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))

        border_color = (180, 120, 40) if brewing else C_BORDER_HI
        pygame.draw.rect(self.screen, border_color,
                         (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start
        now = time.monotonic()
        hdr_color = (255, 180, 50) if brewing and int(now * 2) % 2 else (180, 120, 40)
        hdr_text = "COFFEE MACHINE"
        if brewing:
            hdr_text = f"BREWING: {current}"
        hdr = self.font_panel_header.render(hdr_text, True, hdr_color)
        self.screen.blit(hdr, (x + 2, y))

        cnt_text = f"x{served}"
        cnt_surf = self.font_panel_body.render(cnt_text, True, C_TEXT_BRIGHT)
        self.screen.blit(cnt_surf, (x + panel_w - cnt_surf.get_width() - 10, y + 2))
        y += 20

        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        esp32 = status.get("esp32_connected", False)
        if esp32:
            status_text = f"  Status: {machine_status}"
            status_color = C_TEXT_OK if machine_status in ("ready", "idle", "standby") else C_TEXT
        else:
            status_text = "  Esperando ESP32..."
            status_color = C_TEXT_DIM
        surf = self.font_panel_body.render(status_text[:32], True, status_color)
        self.screen.blit(surf, (x + 2, y))
        y += 16

        if brewing:
            elapsed = time.time() - self.coffee._brew_start
            progress = min(1.0, elapsed / 45.0)
            bar_w = int((panel_w - 20) * progress)
            pygame.draw.rect(self.screen, (60, 40, 20), (x + 5, y + 2, panel_w - 20, 10))
            pygame.draw.rect(self.screen, (180, 120, 40), (x + 5, y + 2, bar_w, 10))
            pct_text = f"{int(progress * 100)}%"
            pct_surf = self.font_panel_body.render(pct_text, True, C_TEXT_BRIGHT)
            self.screen.blit(pct_surf, (x + panel_w // 2 - 10, y))
            y += 16

        return y + 8

    def _draw_health_panel(self, y_start: int = 560) -> int:
        """Health monitor panel — BLE smartwatch data with history + status."""
        if not self.health.available:
            return y_start

        x = 10
        panel_w = 350
        data = self.health.data
        now = time.time()

        if not data.connected and data.last_update == 0:
            return y_start

        # Compute stats for history
        hr_1h = self.health._compute_stats("hr", 3600)
        hr_day = self.health._compute_stats("hr", 86400)
        bp_sys_day = self.health._compute_stats("bp_sys", 86400)
        bp_dia_day = self.health._compute_stats("bp_dia", 86400)
        spo2_day = self.health._compute_stats("spo2", 86400)

        lines = 3  # header + HR + status line
        if data.blood_pressure_sys > 0:
            lines += 1
        if data.spo2 > 0:
            lines += 1
        if data.steps > 0:
            lines += 1
        if hr_1h:
            lines += 1
        if hr_day and hr_day["count"] > 3:
            lines += 1
        if bp_sys_day and bp_sys_day["count"] > 1:
            lines += 1
        if spo2_day and spo2_day["count"] > 1:
            lines += 1
        panel_h = 24 + lines * 16 + 6

        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))

        # Health status assessment
        health_status, status_color = self._assess_health(data, hr_1h)

        hr = data.heart_rate
        if hr > 120:
            border_c = (255, 60, 60) if int(now * 2) % 2 else (200, 50, 50)
        elif hr > 0:
            border_c = (100, 255, 180)
        else:
            border_c = C_BORDER_HI
        pygame.draw.rect(self.screen, border_c,
                         (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start
        status_dot = "ON" if data.connected else "OFF"
        hdr_color = (100, 255, 200) if data.connected else C_TEXT_DIM
        hdr = self.font_panel_header.render(
            f"SALUD  {data.watch_name}  [{status_dot}]", True, hdr_color)
        self.screen.blit(hdr, (x + 2, y))
        # Battery next to header
        if data.battery >= 0:
            bat_color = C_TEXT_OK if data.battery > 20 else C_TEXT_DANGER
            bat_surf = self.font_panel_body.render(f"{data.battery}%", True, bat_color)
            self.screen.blit(bat_surf, (x + panel_w - bat_surf.get_width() - 10, y + 2))
        y += 20
        pygame.draw.line(self.screen, border_c, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        # Status assessment line
        surf = self.font_panel_body.render(f"  {health_status}", True, status_color)
        self.screen.blit(surf, (x + 2, y))
        y += 16

        # Heart rate (current)
        if hr > 0:
            hr_age = now - data.last_hr_time
            hr_fresh = hr_age < 60
            if hr > 120:
                hr_color = C_TEXT_DANGER
            elif hr > 100:
                hr_color = C_TEXT_WARN
            elif hr_fresh:
                hr_color = (180, 255, 220)
            else:
                hr_color = C_TEXT_DIM
            hr_text = f"  HR: {hr} bpm"
            if not hr_fresh:
                hr_text += f" ({int(hr_age)}s)"
        else:
            hr_text = "  HR: esperando..."
            hr_color = C_TEXT_DIM
        surf = self.font_panel_body.render(hr_text, True, hr_color)
        self.screen.blit(surf, (x + 2, y))
        y += 16

        # HR 1h average
        if hr_1h:
            avg_c = (180, 255, 220) if 55 <= hr_1h["avg"] <= 100 else C_TEXT_WARN
            avg_text = f"  1h: avg={hr_1h['avg']} min={hr_1h['min']} max={hr_1h['max']} ({hr_1h['count']})"
            surf = self.font_panel_body.render(avg_text, True, avg_c)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # HR daily
        if hr_day and hr_day["count"] > 3:
            avg_c = (180, 255, 220) if 55 <= hr_day["avg"] <= 100 else C_TEXT_WARN
            day_text = f"  HOY: avg={hr_day['avg']} min={hr_day['min']} max={hr_day['max']} ({hr_day['count']})"
            surf = self.font_panel_body.render(day_text, True, avg_c)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # Blood pressure
        if data.blood_pressure_sys > 0:
            bp_age = now - data.last_bp_time
            bp_fresh = bp_age < 300
            if data.blood_pressure_sys > 140 or data.blood_pressure_dia > 90:
                bp_color = C_TEXT_DANGER
            elif data.blood_pressure_sys < 90:
                bp_color = C_TEXT_WARN
            elif bp_fresh:
                bp_color = (180, 255, 220)
            else:
                bp_color = C_TEXT_DIM
            bp_text = f"  BP: {data.blood_pressure_sys}/{data.blood_pressure_dia} mmHg"
            if not bp_fresh:
                bp_text += f" ({int(bp_age // 60)}m)"
            surf = self.font_panel_body.render(bp_text, True, bp_color)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # SpO2
        if data.spo2 > 0:
            spo2_age = now - data.last_spo2_time
            spo2_fresh = spo2_age < 300
            if data.spo2 < 95:
                spo2_color = C_TEXT_DANGER
            elif data.spo2 >= 97:
                spo2_color = (180, 255, 220)
            elif spo2_fresh:
                spo2_color = C_TEXT_BRIGHT
            else:
                spo2_color = C_TEXT_DIM
            spo2_text = f"  SpO2: {data.spo2}%"
            if not spo2_fresh:
                spo2_text += f" ({int(spo2_age // 60)}m)"
            surf = self.font_panel_body.render(spo2_text, True, spo2_color)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # BP daily average
        if bp_sys_day and bp_sys_day["count"] > 1:
            bp_avg_ok = 90 <= bp_sys_day["avg"] <= 140
            bp_avg_c = (180, 255, 220) if bp_avg_ok else C_TEXT_WARN
            dia_avg = bp_dia_day["avg"] if bp_dia_day else "?"
            bp_avg_text = f"  BP prom: {bp_sys_day['avg']}/{dia_avg} ({bp_sys_day['count']} med)"
            surf = self.font_panel_body.render(bp_avg_text, True, bp_avg_c)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # SpO2 daily average
        if spo2_day and spo2_day["count"] > 1:
            spo2_avg_ok = spo2_day["avg"] >= 95
            spo2_avg_c = (180, 255, 220) if spo2_avg_ok else C_TEXT_WARN
            spo2_avg_text = f"  SpO2 prom: {spo2_day['avg']}% min={spo2_day['min']}% ({spo2_day['count']} med)"
            surf = self.font_panel_body.render(spo2_avg_text, True, spo2_avg_c)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        # Steps
        if data.steps > 0:
            steps_age = now - data.last_steps_time if data.last_steps_time else 9999
            steps_fresh = steps_age < 300
            steps_color = (180, 255, 220) if steps_fresh else C_TEXT_DIM
            steps_text = f"  PASOS: {data.steps}"
            if data.calories > 0:
                steps_text += f"  ({data.calories} kcal)"
            surf = self.font_panel_body.render(steps_text, True, steps_color)
            self.screen.blit(surf, (x + 2, y))
            y += 16

        return y + 8

    def _assess_health(self, data, hr_stats) -> tuple:
        """Return a short health status string and color."""
        issues = []
        now = time.time()

        # HR assessment
        if data.heart_rate > 0 and (now - data.last_hr_time) < 120:
            if data.heart_rate > 120:
                issues.append("HR MUY ALTO")
            elif data.heart_rate > 100:
                issues.append("HR elevado")
            elif data.heart_rate < 50:
                issues.append("HR muy bajo")

        # HR average
        if hr_stats and hr_stats["avg"] > 100:
            issues.append("estres/actividad")
        elif hr_stats and hr_stats["avg"] < 55:
            issues.append("reposo profundo")

        # BP
        if data.blood_pressure_sys > 0 and (now - data.last_bp_time) < 600:
            if data.blood_pressure_sys > 140 or data.blood_pressure_dia > 90:
                issues.append("PRESION ALTA")
            elif data.blood_pressure_sys < 90:
                issues.append("presion baja")

        # SpO2
        if data.spo2 > 0 and (now - data.last_spo2_time) < 600:
            if data.spo2 < 93:
                issues.append("SpO2 CRITICO")
            elif data.spo2 < 95:
                issues.append("SpO2 bajo")

        if not issues:
            if data.heart_rate > 0:
                return "OPTIMO - signos vitales normales", C_TEXT_OK
            return "Esperando datos...", C_TEXT_DIM

        severity = any(w.isupper() for w in issues)
        msg = " | ".join(issues)
        if severity:
            return f"ATENCION: {msg}", C_TEXT_DANGER
        return f"AVISO: {msg}", C_TEXT_WARN

    def _draw_detection_overlay(self):
        """Show detection labels and recognized faces clearly on screen."""
        now = time.monotonic()

        # --- Info bar: above voice area, shows what Tokio sees ---
        info_y = SCREEN_H - VOICE_H - STATS_H - 42

        # Recognized face — prominent display
        if self._info_face and now - self._info_face_time < 5.0:
            face_alpha = min(1.0, 1.0 - max(0, (now - self._info_face_time - 3.0) / 2.0))
            if self._info_face == "???":
                face_color = tuple(int(c * face_alpha) for c in C_TEXT_WARN)
                face_text = "ROSTRO DESCONOCIDO"
                icon = "?"
            else:
                face_color = tuple(int(c * face_alpha) for c in C_ADMIN_GOLD)
                face_text = self._info_face.upper()
                icon = ">"
            # Face name — big, centered at bottom
            name_surf = self.font_info_big.render(f"[{icon}] {face_text}", True, face_color)
            nx = SCREEN_W // 2 - name_surf.get_width() // 2
            self.screen.blit(name_surf, (nx, info_y))

        # Detection labels bar — below face name
        if self._info_labels:
            labels_text = " | ".join(self._info_labels[:6])
            label_surf = self.font_info.render(labels_text, True, C_TEXT_DIM)
            lx = SCREEN_W // 2 - label_surf.get_width() // 2
            self.screen.blit(label_surf, (lx, info_y + 26))

        # --- Crosshairs on detections (subtle) ---
        if not self._last_detections:
            return

        if self.vision:
            frame = self.vision.get_frame()
            if frame is not None:
                fh, fw = frame.shape[:2]
                face_area_h = SCREEN_H - STATS_H - VOICE_H
                for det in self._last_detections[:8]:
                    sx = int((det.center[0] / fw) * SCREEN_W)
                    sy = int((det.center[1] / fh) * face_area_h)

                    is_threat = det.label in THREAT_OBJECTS
                    color = C_TEXT_DANGER if is_threat else (0, 100, 140)

                    # Crosshair
                    ch = 8 if is_threat else 5
                    pygame.draw.line(self.screen, color, (sx - ch, sy), (sx + ch, sy), 1)
                    pygame.draw.line(self.screen, color, (sx, sy - ch), (sx, sy + ch), 1)

    def _draw_voice(self):
        now = time.monotonic()
        age = now - self._voice_time

        voice_y = SCREEN_H - VOICE_H - STATS_H
        voice_surf = pygame.Surface((SCREEN_W, VOICE_H), pygame.SRCALPHA)
        voice_surf.fill((4, 6, 16, 200))
        self.screen.blit(voice_surf, (0, voice_y))

        # Gradient top edge
        for i in range(30):
            alpha = int(200 * (i / 30))
            line_surf = pygame.Surface((SCREEN_W, 1), pygame.SRCALPHA)
            line_surf.fill((4, 6, 16, alpha))
            self.screen.blit(line_surf, (0, voice_y - 30 + i))

        pad_x = 24  # horizontal padding both sides

        # "TOKIO:" prefix with subtle glow
        prefix_surf = self.font_voice_sub.render("TOKIO:", True, C_TEXT)
        self.screen.blit(prefix_surf, (pad_x, voice_y + 8))

        # Now playing from HA — show next to TOKIO: label
        if self.ha_feed.available:
            playing = self.ha_feed.get_now_playing()
            if playing:
                music_text = f"  {playing[:30]}"
                music_surf = self.font_tiny.render(music_text, True, C_ACCENT)
                self.screen.blit(music_surf, (pad_x + prefix_surf.get_width() + 4, voice_y + 12))

        # Fade effect — 8s total: fade in 0.5s, visible ~6.5s, fade out 1s
        if age < 0.5:
            alpha_mult = min(1.0, age / 0.3)
        elif age > 7.0:
            alpha_mult = max(0.3, 1.0 - (age - 7.0) / 1.0)
        else:
            alpha_mult = 1.0

        color = tuple(max(40, int(c * alpha_mult)) for c in self._voice_color)

        # Word-wrap text — max_chars based on actual available width
        text = self._voice_text
        avail_w = SCREEN_W - pad_x * 2  # 768 - 48 = 720px
        max_chars = 50  # safe for 21px monospace in 720px
        if len(text) > max_chars:
            words = text.split()
            lines = []
            current = ""
            for w in words:
                if len(current) + len(w) + 1 > max_chars:
                    lines.append(current)
                    current = w
                else:
                    current = f"{current} {w}" if current else w
            if current:
                lines.append(current)
        else:
            lines = [text]

        y = voice_y + 28
        for line in lines[:5]:  # up to 5 lines
            text_surf = self.font_voice.render(line, True, color)
            # Clip to available width
            if text_surf.get_width() > avail_w:
                clip_rect = pygame.Rect(0, 0, avail_w, text_surf.get_height())
                self.screen.blit(text_surf, (pad_x, y), clip_rect)
            else:
                self.screen.blit(text_surf, (pad_x, y))
            y += 24

        # Gesture indicator
        if (self._last_gesture != Gesture.NONE and
                now - self._last_gesture_time < GESTURE_COOLDOWN):
            icon = GESTURE_ICONS.get(self._last_gesture, "?")
            gs = self.font_gesture.render(f"[{icon}]", True, C_GESTURE)
            self.screen.blit(gs, (SCREEN_W - gs.get_width() - 30, voice_y + 25))

    def _generate_qr(self, url: str):
        """Generate QR code as a pygame Surface."""
        try:
            import qrcode
            from PIL import Image
            qr = qrcode.QRCode(version=1, box_size=6, border=2,
                                error_correction=qrcode.constants.ERROR_CORRECT_H)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="white", back_color="black").convert("RGB")
            img = img.resize((120, 120), Image.NEAREST)
            raw = img.tobytes()
            surf = pygame.image.fromstring(raw, img.size, "RGB")
            return surf
        except Exception as e:
            print(f"[Entity] QR generation failed: {e}")
            return None

    def _draw_stats_bar(self):
        sy = SCREEN_H - STATS_H
        stat_surf = pygame.Surface((SCREEN_W, STATS_H), pygame.SRCALPHA)
        stat_surf.fill((4, 8, 20, 230))
        self.screen.blit(stat_surf, (0, sy))
        pygame.draw.line(self.screen, C_BORDER_HI, (0, sy), (SCREEN_W, sy), 1)

        stats = self.security.get_stats()
        now = time.monotonic()
        up = int(now - self._boot_time)
        m, s = divmod(up, 60)
        h, m = divmod(m, 60)

        visitors = self.ai_brain.visitor_count if self.ai_brain.available else 0

        # Total security blocks: WAF + WiFi defense + BLE security
        wifi_blocks = 0
        if self.wifi_defense:
            ws = self.wifi_defense.get_stats()
            wifi_blocks = ws.mitigations_applied
        ble_blocks = 0
        if hasattr(self, 'health') and self.health.available:
            ble_sec = getattr(self.health, '_security', None)
            if ble_sec:
                bs = ble_sec.get_status()
                ble_blocks = (bs.get("spoofing_detected", 0) +
                              bs.get("replay_detected", 0) +
                              bs.get("flooding_detected", 0))
        total_blocked = stats.blocked + wifi_blocks + ble_blocks

        # Drone battery display
        if self._drone_connected:
            bat_str = f"{self._drone_battery}%" if self._drone_battery >= 0 else "?"
            bat_color = C_TEXT_OK if self._drone_battery > 30 else C_TEXT_WARN if self._drone_battery > 10 else C_TEXT_DANGER
            drone_item = ("DRONE", bat_str, bat_color)
        else:
            drone_item = ("DRONE", "OFF", C_TEXT_DIM)

        items = [
            ("VISITORS", str(visitors), C_ADMIN_GOLD),
            ("ATTACKS", str(stats.total_attacks), C_TEXT_DANGER),
            ("BLOCKED", str(total_blocked), C_TEXT_OK),
            ("FACES", str(len(self._current_identities)), C_ACCENT),
            ("WIFI", f"D:{wifi_blocks}" if wifi_blocks > 0 else "OK",
             C_WIFI_DANGER if wifi_blocks > 0 else C_WIFI_OK),
            drone_item,
            ("UP", f"{h}:{m:02d}", C_TEXT_DIM),
        ]

        item_w = SCREEN_W // len(items)
        for i, (label, value, color) in enumerate(items):
            x = i * item_w + item_w // 2
            vs = self.font_stat.render(value, True, color)
            self.screen.blit(vs, (x - vs.get_width() // 2, sy + 4))
            ls = self.font_stat_label.render(label, True, C_TEXT_DIM)
            self.screen.blit(ls, (x - ls.get_width() // 2, sy + 28))

    def _draw_services_panel(self, y_start: int = 700) -> int:
        """System services monitoring panel — shows all service status."""
        x = 10
        panel_w = 350

        services = []
        # Raspi services
        services.append(("RASPI", "Camera",
                         "ON" if self.vision else "OFF",
                         C_TEXT_OK if self.vision else C_TEXT_DIM))
        services.append(("RASPI", "AI Brain",
                         "ON" if self.ai_brain.available else "OFF",
                         C_TEXT_OK if self.ai_brain.available else C_TEXT_DANGER))
        services.append(("RASPI", "BLE Health",
                         "ON" if self.health.data.connected else "OFF",
                         C_TEXT_OK if self.health.data.connected else C_TEXT_WARN))
        services.append(("RASPI", "WiFi Def",
                         "ON" if self.wifi_defense else "OFF",
                         C_TEXT_OK if self.wifi_defense else C_TEXT_DIM))
        services.append(("RASPI", "WAF Feed",
                         "ON" if self.security.connected else "OFF",
                         C_TEXT_OK if self.security.connected else C_TEXT_WARN))
        services.append(("RASPI", "Home Asst",
                         "ON" if self.ha_feed.available else "OFF",
                         C_TEXT_OK if self.ha_feed.available else C_TEXT_DIM))

        # GCP services (inferred from WAF connection)
        gcp_ok = self.security.connected
        services.append(("GCP", "Agent",
                         "ON" if gcp_ok else "?",
                         C_TEXT_OK if gcp_ok else C_TEXT_DIM))
        services.append(("GCP", "Telegram",
                         "ON" if gcp_ok else "?",
                         C_TEXT_OK if gcp_ok else C_TEXT_DIM))

        lines_count = 1 + len(services)
        panel_h = 24 + lines_count * 14 + 6

        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))
        pygame.draw.rect(self.screen, C_BORDER_HI,
                         (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start
        # Count ON services
        on_count = sum(1 for _, _, st, _ in services if st == "ON")
        total = len(services)
        hdr_color = C_TEXT_OK if on_count == total else C_TEXT_WARN
        hdr = self.font_panel_header.render(
            f"SERVICIOS  {on_count}/{total}", True, hdr_color)
        self.screen.blit(hdr, (x + 2, y))
        y += 20
        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        # Render services in two columns
        col_w = panel_w // 2
        for i, (group, name, status, color) in enumerate(services):
            col = i % 2
            row = i // 2
            sx = x + 5 + col * col_w
            sy = y + row * 14
            dot = "*" if status == "ON" else "-"
            text = f" {dot} {name}: {status}"
            surf = self.font_panel_body.render(text, True, color)
            self.screen.blit(surf, (sx, sy))

        rows = (len(services) + 1) // 2
        return y + rows * 14 + 8

    def _draw_telegram_panel(self, y_start: int = 850) -> int:
        """Telegram activity feed — shows recent conversations from GCP core."""
        with self._telegram_lock:
            activity = list(self._telegram_activity[-4:])

        if not activity:
            return y_start

        x = 10
        panel_w = 350
        now_epoch = time.time()
        now = time.monotonic()

        # Filter to recent activity (last 5 minutes)
        activity = [a for a in activity if now_epoch - a.get("time", 0) < 300]
        if not activity:
            return y_start

        lines = len(activity)
        panel_h = 28 + lines * 30 + 6

        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))

        # Accent border with pulse for fresh messages
        fresh = any(now_epoch - a.get("time", 0) < 10 for a in activity)
        if fresh:
            pulse_v = int(140 + 80 * math.sin(now * 4))
            border_color = (pulse_v, 80, 255)
        else:
            border_color = C_ACCENT
        pygame.draw.rect(self.screen, border_color,
                         (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start
        hdr = self.font_panel_header.render("TELEGRAM LIVE", True, C_ACCENT)
        self.screen.blit(hdr, (x + 2, y))
        # Pulsing dot for live
        if int(now * 2) % 2:
            pygame.draw.circle(self.screen, C_LIVE_DOT, (x + panel_w - 15, y + 8), 4)
        y += 20
        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        emotion_colors = {
            "happy": C_TEXT_OK, "excited": C_ADMIN_GOLD,
            "thinking": C_TEXT_BRIGHT, "alert": C_TEXT_WARN,
            "angry": C_TEXT_DANGER, "curious": C_ACCENT,
            "neutral": C_TEXT,
        }

        for act in reversed(activity):
            user = act.get("user", "?")[:10]
            msg = act.get("message", "")[:26]
            emotion = act.get("emotion", "neutral")
            age = now_epoch - act.get("time", 0)
            age_text = f"{int(age)}s" if age < 60 else f"{int(age / 60)}m"

            # User line
            user_color = C_ADMIN_GOLD if "Daniel" in user else C_ACCENT
            user_surf = self.font_panel_body.render(f"  {user} [{age_text}]", True, user_color)
            self.screen.blit(user_surf, (x + 2, y))
            y += 14

            # Message line with emotion color
            msg_color = emotion_colors.get(emotion, C_TEXT)
            msg_surf = self.font_panel_body.render(f"    {msg}", True, msg_color)
            self.screen.blit(msg_surf, (x + 2, y))
            y += 16

        return y + 8

    def _draw_qr_code(self):
        """Draw QR code in bottom-right corner, above stats bar."""
        if not self._qr_surface:
            return
        qr_size = self._qr_surface.get_width()
        x = SCREEN_W - qr_size - 8
        y = SCREEN_H - STATS_H - qr_size - 30
        self.screen.blit(self._qr_surface, (x, y))
        label = self.font_wifi_tiny.render("GITHUB", True, C_TEXT_DIM)
        self.screen.blit(label, (x + qr_size // 2 - label.get_width() // 2, y + qr_size + 2))

    # -------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------

    def run(self):
        self._running = True
        last = time.monotonic()
        vision_timer = 0.0

        if self.start_api:
            threading.Thread(target=self._run_api, daemon=True).start()

        while self._running:
            now = time.monotonic()
            dt = now - last
            last = now
            self._pulse = (math.sin(now * 2) + 1) / 2

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._running = False
                    elif event.key == pygame.K_f:
                        pygame.display.toggle_fullscreen()
                    elif event.key == pygame.K_r:
                        self.start_register("Daniel", "admin")
                    elif event.key == pygame.K_v:
                        self.start_register("Visitante", "visitor")
                elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                    if event.type == pygame.FINGERDOWN:
                        pos = (int(event.x * SCREEN_W), int(event.y * SCREEN_H))
                    else:
                        pos = event.pos
                    pip_rect = pygame.Rect(PIP_X, PIP_Y, PIP_W, PIP_H)
                    if pip_rect.collidepoint(pos):
                        models = ["detect", "faces", "pose"]
                        idx = (models.index(self._active_model) + 1) % len(models) \
                            if self._active_model in models else 0
                        self._active_model = models[idx]
                        if self.vision:
                            self._say(f"Cambiando vision: {self._active_model}", C_TEXT)
                            threading.Thread(
                                target=lambda m=self._active_model: self.vision.switch_model(m),
                                daemon=True).start()

            # Update
            self.face.update(dt)
            self._update_voice()

            vision_timer += dt
            if vision_timer > 0.3:
                vision_timer = 0
                self._process_vision()
                # Check WiFi alerts for emotional reactions
                _, wifi_alerts = self.wifi_monitor.get_data()
                for alert in wifi_alerts:
                    if now - alert.get("time", 0) < 2:  # Only react to new alerts
                        if alert["type"] == "EVIL_TWIN":
                            self._say(f"Evil twin detectado: {alert['msg']}", C_WIFI_DANGER)
                            self.face.set_emotion(Emotion.ANGRY, "Evil Twin!")
                        elif alert["type"] == "SIG_ANOMALY":
                            self._say(f"Anomalia WiFi: {alert['msg']}", C_WIFI_WARN)
                            self.face.set_emotion(Emotion.ALERT, "Signal anomaly")

            if self.demo_mode and int(now) % 5 == 0 and int(now * 10) % 10 == 0:
                self.face.set_emotion(random.choice(list(Emotion)))

            # Render layers
            self.screen.fill(C_BG)
            self._draw_face_fullscreen()
            self._draw_detection_overlay()
            # Left sidebar panels — chained dynamically (no overlap)
            panel_y = self._draw_waf_sidebar()
            panel_y = self._draw_wifi_panel(panel_y)
            panel_y = self._draw_ha_panel(panel_y)
            panel_y = self._draw_health_panel(panel_y)
            panel_y = self._draw_coffee_panel(panel_y)
            panel_y = self._draw_robot_panel(panel_y)
            panel_y = self._draw_services_panel(panel_y)
            self._draw_telegram_panel(panel_y)
            # Overlays
            self._draw_camera_pip()
            self._draw_fpv_pip()
            self._draw_robot_cameras()
            self._draw_qr_code()
            self._draw_voice()
            self._draw_drone_overlay()
            self._draw_stats_bar()

            pygame.display.flip()
            self.clock.tick(30)

        self.security.stop()
        self.wifi_monitor.stop()
        self.ai_brain.stop()
        self.ha_feed.stop()
        self.drone_fpv.stop()
        if self.wifi_defense:
            self.wifi_defense.stop()
        if self.vision:
            self.vision.release()
        pygame.quit()

    def _draw_robot_panel(self, y_start: int = 620) -> int:
        """Combined PiDog + PiCar status panel. Returns bottom Y."""
        pidog = self._pidog_status
        picar = self._picar_status
        if not pidog and not picar:
            return y_start

        x = 10
        panel_w = 350
        now = time.monotonic()

        # Calculate panel height
        lines = 0
        if pidog:
            lines += 3  # header + status + sensors
        if picar:
            lines += 3
        panel_h = 24 + lines * 16 + 10

        panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill((4, 8, 20, 235))
        self.screen.blit(panel_surf, (x - 5, y_start - 5))

        # Border color based on activity
        active = (pidog.get("patrol") or pidog.get("interactive") or
                  picar.get("moving", False))
        border_color = (50, 180, 120) if active else C_BORDER_HI
        pygame.draw.rect(self.screen, border_color,
                         (x - 5, y_start - 5, panel_w, panel_h), 1)

        y = y_start
        hdr = self.font_panel_header.render("ROBOT FLEET", True, (50, 180, 120))
        self.screen.blit(hdr, (x + 2, y))

        # Online count
        online = sum(1 for s in [pidog, picar] if s)
        cnt_surf = self.font_panel_body.render(f"{online}/2 online", True, C_TEXT_OK if online == 2 else C_TEXT_WARN)
        self.screen.blit(cnt_surf, (x + panel_w - cnt_surf.get_width() - 10, y + 2))
        y += 20
        pygame.draw.line(self.screen, C_BORDER_HI, (x, y), (x + panel_w - 15, y), 1)
        y += 3

        # PiDog
        if pidog:
            ready = pidog.get("ready", False)
            icon = "OK" if ready else "OFF"
            icon_color = C_TEXT_OK if ready else C_TEXT_DANGER
            surf = self.font_panel_body.render(f"  PiDog: {icon}", True, icon_color)
            self.screen.blit(surf, (x + 2, y))
            # Action status
            action = pidog.get("last_action", "?")
            patrol = pidog.get("patrol", False)
            inter = pidog.get("interactive", False)
            if patrol:
                st = "PATROL"
                st_color = (255, 180, 50)
            elif inter:
                st = "INTERACTIVE"
                st_color = (180, 100, 255)
            else:
                st = action
                st_color = C_TEXT_DIM
            st_surf = self.font_panel_body.render(st, True, st_color)
            self.screen.blit(st_surf, (x + panel_w - st_surf.get_width() - 10, y))
            y += 16

            # PiDog sensors from last poll
            age = now - self._pidog_last_poll
            if age < 10:
                dist_text = f"    dist: {pidog.get('distance_cm', '?')}cm"
                surf2 = self.font_panel_body.render(dist_text[:30], True, C_TEXT_DIM)
                self.screen.blit(surf2, (x + 2, y))
            else:
                surf2 = self.font_panel_body.render("    (offline)", True, C_TEXT_DANGER)
                self.screen.blit(surf2, (x + 2, y))
            y += 16

        # PiCar
        if picar:
            ready = picar.get("initialized", False)
            icon = "OK" if ready else "OFF"
            icon_color = C_TEXT_OK if ready else C_TEXT_DANGER
            surf = self.font_panel_body.render(f"  PiCar: {icon}", True, icon_color)
            self.screen.blit(surf, (x + 2, y))
            # Movement
            moving = picar.get("moving", False)
            direction = picar.get("direction", "stopped")
            if moving:
                speed = picar.get("speed", 0)
                mv_text = f"{direction} @{speed}%"
                mv_color = (255, 180, 50)
            else:
                mv_text = "stopped"
                mv_color = C_TEXT_DIM
            mv_surf = self.font_panel_body.render(mv_text, True, mv_color)
            self.screen.blit(mv_surf, (x + panel_w - mv_surf.get_width() - 10, y))
            y += 16

            # PiCar sensors
            bat = picar.get("battery_v", -1)
            ultra = picar.get("ultrasonic_cm", -1)
            bat_color = C_TEXT_OK if bat > 7.5 else C_TEXT_WARN if bat > 7.0 else C_TEXT_DANGER
            sensor_text = f"    bat:{bat:.1f}V  dist:{ultra:.0f}cm"
            surf3 = self.font_panel_body.render(sensor_text[:32], True, bat_color)
            self.screen.blit(surf3, (x + 2, y))
            y += 16

        return y + 8

    def _draw_robot_cameras(self):
        """Draw PiDog and PiCar camera feeds as small PIPs below FPV."""
        CAM_W, CAM_H = 140, 105
        RIGHT_X = SCREEN_W - CAM_W - PIP_MARGIN
        # Position below FPV pip (FPV ends at FPV_Y + FPV_H)
        ROBOT_CAM_Y1 = FPV_Y + FPV_H + 10   # PiDog
        ROBOT_CAM_Y2 = ROBOT_CAM_Y1 + CAM_H + 8  # PiCar

        # PiDog camera
        if self._pidog_frame is not None:
            try:
                small = cv2.resize(self._pidog_frame, (CAM_W, CAM_H))
                small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                surf = pygame.surfarray.make_surface(small.swapaxes(0, 1))
                self.screen.blit(surf, (RIGHT_X, ROBOT_CAM_Y1))
                pygame.draw.rect(self.screen, (50, 180, 120),
                                 (RIGHT_X, ROBOT_CAM_Y1, CAM_W, CAM_H), 2)
                label = self.font_pip_label.render("PiDog", True, (50, 180, 120))
                self.screen.blit(label, (RIGHT_X + 4, ROBOT_CAM_Y1 + 3))
                if int(time.monotonic() * 2) % 2:
                    pygame.draw.circle(self.screen, (0, 255, 0),
                                       (RIGHT_X + CAM_W - 8, ROBOT_CAM_Y1 + 8), 4)
            except Exception:
                pass

        # PiCar camera
        if self._picar_frame is not None:
            try:
                small = cv2.resize(self._picar_frame, (CAM_W, CAM_H))
                small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                surf = pygame.surfarray.make_surface(small.swapaxes(0, 1))
                self.screen.blit(surf, (RIGHT_X, ROBOT_CAM_Y2))
                pygame.draw.rect(self.screen, (50, 120, 200),
                                 (RIGHT_X, ROBOT_CAM_Y2, CAM_W, CAM_H), 2)
                label = self.font_pip_label.render("PiCar", True, (50, 120, 200))
                self.screen.blit(label, (RIGHT_X + 4, ROBOT_CAM_Y2 + 3))
                if int(time.monotonic() * 2) % 2:
                    pygame.draw.circle(self.screen, (0, 255, 0),
                                       (RIGHT_X + CAM_W - 8, ROBOT_CAM_Y2 + 8), 4)
            except Exception:
                pass

    def _draw_drone_overlay(self):
        """Draw drone tracking overlay on screen."""
        if self.drone_vision.mode == DronePlayMode.IDLE:
            return
        info = self.drone_vision.get_overlay_info()
        if not info:
            # Show mode indicator even when not detected
            mode_text = f"DRONE: {self.drone_vision.mode.value.upper()}"
            if self.drone_vision.mode == DronePlayMode.REGISTER:
                mode_text = "DRONE: REGISTRANDO... Mostra el drone a la camara"
            font = self.font_panel_header
            surf = font.render(mode_text, True, (0, 255, 200))
            self.screen.blit(surf, (SCREEN_W // 2 - surf.get_width() // 2, 10))
            return

        # Draw targeting reticle on camera PIP
        bbox = info["bbox"]
        cx, cy = info["center"]
        dist = info["distance_cm"]
        conf = info["confidence"]
        mode = info["mode"]

        # Scale bbox to PIP coordinates
        pip_scale_x = PIP_W / 640
        pip_scale_y = PIP_H / 480
        px1 = int(PIP_X + bbox[0] * pip_scale_x)
        py1 = int(PIP_Y + bbox[1] * pip_scale_y)
        px2 = int(PIP_X + bbox[2] * pip_scale_x)
        py2 = int(PIP_Y + bbox[3] * pip_scale_y)
        pcx = int(PIP_X + cx * pip_scale_x)
        pcy = int(PIP_Y + cy * pip_scale_y)

        # Pulsing color
        t = time.monotonic()
        pulse = int(155 + 100 * math.sin(t * 4))
        color = (0, pulse, 255)

        # Targeting box with corners
        corner_len = 12
        for x, y, dx, dy in [
            (px1, py1, 1, 1), (px2, py1, -1, 1),
            (px1, py2, 1, -1), (px2, py2, -1, -1)
        ]:
            pygame.draw.line(self.screen, color, (x, y), (x + corner_len * dx, y), 2)
            pygame.draw.line(self.screen, color, (x, y), (x, y + corner_len * dy), 2)

        # Crosshair
        ch_size = 8
        pygame.draw.line(self.screen, color, (pcx - ch_size, pcy), (pcx + ch_size, pcy), 1)
        pygame.draw.line(self.screen, color, (pcx, pcy - ch_size), (pcx, pcy + ch_size), 1)

        # Distance label
        font = self.font_panel_body
        dist_text = f"{dist:.0f}cm" if dist > 0 else "?"
        label = f"DRONE [{mode.upper()}] {dist_text} ({conf:.0%})"
        surf = font.render(label, True, color)
        self.screen.blit(surf, (px1, py1 - 18))

        # Mode indicator at top
        mode_label = f"DRONE VISION: {mode.upper()}"
        surf2 = self.font_panel_header.render(mode_label, True, (0, 255, 200))
        self.screen.blit(surf2, (SCREEN_W // 2 - surf2.get_width() // 2, 10))

        # Offset arrows (show which direction drone needs to go)
        ox, oy = info["offset_x"], info["offset_y"]
        arrow_x = SCREEN_W // 2 + int(ox * 60)
        arrow_y = 32
        pygame.draw.circle(self.screen, (0, 255, 200), (arrow_x, arrow_y), 4)

    def _draw_fpv_pip(self):
        """Draw drone FPV feed as PiP below the main camera."""
        state = self.drone_fpv.get_state()
        if not state.streaming:
            return
        fpv_frame = self.drone_fpv.get_frame()
        if fpv_frame is None:
            return

        # Convert BGR to RGB and resize
        rgb = cv2.cvtColor(fpv_frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (FPV_W, FPV_H))
        surf = pygame.surfarray.make_surface(np.transpose(resized, (1, 0, 2)))

        # Background + blit
        border_rect = pygame.Rect(FPV_X - 2, FPV_Y - 2, FPV_W + 4, FPV_H + 4)
        pygame.draw.rect(self.screen, C_BG, border_rect)
        self.screen.blit(surf, (FPV_X, FPV_Y))

        # Cyan border (FPV = different color from main camera)
        fpv_color = (0, 200, 255)
        pygame.draw.rect(self.screen, fpv_color, border_rect, 2)

        # Corner brackets
        cl = 10
        for cx, cy in [(FPV_X, FPV_Y), (FPV_X + FPV_W, FPV_Y),
                        (FPV_X, FPV_Y + FPV_H), (FPV_X + FPV_W, FPV_Y + FPV_H)]:
            dx = 1 if cx == FPV_X else -1
            dy = 1 if cy == FPV_Y else -1
            pygame.draw.line(self.screen, fpv_color, (cx, cy), (cx + dx * cl, cy), 2)
            pygame.draw.line(self.screen, fpv_color, (cx, cy), (cx, cy + dy * cl), 2)

        # Label
        self.screen.blit(self.font_pip_label.render("FPV", True, fpv_color), (FPV_X + 4, FPV_Y + 3))

        # FPS + mode (reuse state from top of method)
        mode_text = f"{state.mode.upper()} {state.fps:.0f}fps"
        self.screen.blit(self.font_tiny.render(mode_text, True, fpv_color),
                         (FPV_X + FPV_W - 90, FPV_Y + 3))

        # Person count
        if state.persons:
            badge = self.font_tiny.render(f"{len(state.persons)} pers", True, C_TEXT_OK)
            self.screen.blit(badge, (FPV_X + 4, FPV_Y + FPV_H - 16))

        # Obstacle warning
        if state.obstacle_ahead:
            warn = self.font_tiny.render(f"OBSTACULO {state.closest_obstacle_cm:.0f}cm", True, C_TEXT_DANGER)
            self.screen.blit(warn, (FPV_X + FPV_W // 2 - warn.get_width() // 2, FPV_Y + FPV_H - 16))

        # Live dot (pulsing)
        now = time.monotonic()
        if int(now * 2) % 2:
            pygame.draw.circle(self.screen, C_LIVE_DOT, (FPV_X + FPV_W - 8, FPV_Y + 8), 4)

    def _run_api(self):
        try:
            from .api_server import create_api
            app = create_api(self)
            app.run(host="0.0.0.0", port=5000, threaded=True)
        except Exception as e:
            print(f"[API] Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="TokioAI Entity")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--register", type=str, help="name:role")
    args = parser.parse_args()

    # ── Singleton guard — prevents dual-instance camera conflicts ──
    _acquire_singleton()
    print(f"[Entity] Singleton lock acquired (PID {os.getpid()})")

    os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
    os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")

    app = TokioEntity(
        fullscreen=not args.windowed,
        demo_mode=args.demo,
        start_api=args.api,
    )

    if args.register:
        parts = args.register.split(":")
        app.start_register(parts[0], parts[1] if len(parts) > 1 else "visitor")

    def _graceful_shutdown(signum, frame):
        print(f"[Entity] Received signal {signum}, shutting down gracefully...")
        app._running = False

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    try:
        app.run()
    finally:
        # Ensure camera is released on any exit
        if hasattr(app, 'vision') and app.vision:
            try:
                app.vision.stop()
            except Exception:
                pass
        _release_singleton()
        print("[Entity] Shutdown complete.")


if __name__ == "__main__":
    main()
