#!/usr/bin/env python3
"""PiDog Safety Proxy v3.0 - 100% SunFounder Official API
Based on official examples: 1_wake_up, 2_function_demonstration,
3_patrol, 4_response, 6_be_picked_up, 7_face_track, 10_balance
"""
import os, sys, json, time, threading, signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from multiprocessing import Process, Queue

def pidog_worker(cmd_queue, result_queue):
    """Isolated process that owns PiDog hardware"""
    os.environ['SUDO_USER'] = 'mrmoz'
    os.system('pinctrl set 12 op dh')  # Enable speaker GPIO
    sys.path.insert(0, '/home/mrmoz/pidog')
    from pidog import Pidog
    from pidog import preset_actions as pa

    dog = Pidog()
    time.sleep(0.5)

    # Camera init (non-fatal)
    vilib_ok = False
    try:
        from vilib import Vilib
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        vilib_ok = True
    except Exception as e:
        print(f"[WARN] Camera: {e}")

    # All official presets
    PRESETS = {
        'bark': lambda: pa.bark(dog, [0,0,0], pitch_comp=-40, volume=80),
        'howling': lambda: pa.howling(dog, volume=80),
        'hand_shake': lambda: pa.hand_shake(dog),
        'high_five': lambda: pa.high_five(dog),
        'scratch': lambda: pa.scratch(dog),
        'lick_hand': lambda: pa.lick_hand(dog),
        'attack': lambda: pa.attack_posture(dog),
        'body_twisting': lambda: pa.body_twisting(dog),
        'pant': lambda: pa.pant(dog, [0,0,0], pitch_comp=-40, volume=80),
        'alert': lambda: pa.alert(dog),
        'stretch': lambda: pa.stretch(dog),
        'push_up': lambda: pa.push_up(dog),
        'nod': lambda: pa.nod(dog),
        'think': lambda: pa.think(dog),
        'recall': lambda: pa.recall(dog),
        'surprise': lambda: pa.surprise(dog),
        'fluster': lambda: pa.fluster(dog),
        'waiting': lambda: pa.waiting(dog),
        'feet_shake': lambda: pa.feet_shake(dog),
        'relax_neck': lambda: pa.relax_neck(dog),
        'sit_2_stand': lambda: pa.sit_2_stand(dog),
        'bark_action': lambda: pa.bark_action(dog, [0,0,0]),
        'shake_head': lambda: pa.shake_head(dog, [0,0,0]),
    }

    # Official actions (from example 2)
    ACTIONS = {
        'stand': (0, 50), 'sit': (-30, 50), 'lie': (0, 20),
        'lie_with_hands_out': (0, 20), 'trot': (0, 95),
        'forward': (0, 98), 'backward': (0, 98),
        'turn_left': (0, 98), 'turn_right': (0, 98),
        'doze_off': (-30, 90), 'stretch': (20, 20),
        'push_up': (-30, 50), 'shake_head': (None, 90),
        'tilting_head': (None, 60), 'wag_tail': (None, 100),
    }
    STANDUP = ['trot','forward','backward','turn_left','turn_right']

    # Sounds
    SOUNDS = sorted([n.split('.')[0] for n in os.listdir('/home/mrmoz/pidog/sounds')]) if os.path.isdir('/home/mrmoz/pidog/sounds') else []

    last_action = 'stand'
    last_pitch = 0
    patrol_flag = False
    interactive_flag = False

    def safe_battery():
        try:
            return round(dog.get_battery_voltage(), 2)
        except:
            return 0.0

    def safe_imu():
        try:
            return list(dog.accData), list(dog.gyroData)
        except:
            return [0,0,0], [0,0,0]

    print(f"[WORKER] Ready. IMU:{'imu' in dog.thread_list} Cam:{vilib_ok} Sounds:{len(SOUNDS)}")

    while True:
        try:
            cmd = cmd_queue.get(timeout=0.1)
        except:
            continue

        action = cmd.get('action', '')
        params = cmd.get('params', {})
        res = {'ok': True, 'action': action}

        try:
            if action == 'status':
                acc, gyro = safe_imu()
                batt = safe_battery()
                res['data'] = {
                    'version': '3.0', 'distance_cm': round(dog.read_distance() or -1, 1),
                    'touch': dog.dual_touch.read(), 'battery_voltage': batt,
                    'battery_percent': max(0, min(100, int((batt-6)/(8.4-6)*100))) if batt > 0 else 0,
                    'imu': {'acc': acc, 'gyro': gyro},
                    'imu_available': 'imu' in dog.thread_list,
                    'camera_available': vilib_ok,
                    'sounds': SOUNDS, 'actions': list(ACTIONS.keys()),
                    'presets': list(PRESETS.keys()), 'threads': dog.thread_list,
                }

            elif action == 'sensors':
                acc, _ = safe_imu()
                res['data'] = {
                    'distance_cm': round(dog.read_distance() or -1, 1),
                    'touch': dog.dual_touch.read(),
                    'battery_voltage': safe_battery(), 'imu_acc': acc,
                }

            elif action == 'do_action':
                name = params.get('name', 'stand')
                steps = params.get('steps', 10)
                spd = params.get('speed')
                if name not in ACTIONS:
                    res = {'ok': False, 'error': f'Unknown: {name}. Available: {list(ACTIONS.keys())}'}
                else:
                    pitch, default_spd = ACTIONS[name]
                    if spd is None: spd = default_spd
                    if name in STANDUP and last_action not in STANDUP:
                        dog.do_action('stand', speed=60); dog.wait_legs_done()
                    if last_action == 'push_up' and name != 'push_up':
                        dog.do_action('lie', speed=60); dog.wait_legs_done()
                    if pitch is not None: last_pitch = pitch
                    dog.head_move_raw([[0,0,last_pitch]], immediately=False, speed=60)
                    dog.do_action(name, step_count=steps, speed=spd, pitch_comp=last_pitch)
                    last_action = name
                    res['msg'] = f'{name} x{steps} @{spd}'

            elif action == 'preset':
                name = params.get('name', 'bark')
                if name in PRESETS:
                    PRESETS[name]()
                    res['msg'] = f'preset {name}'
                else:
                    res = {'ok': False, 'error': f'Unknown: {name}. Available: {list(PRESETS.keys())}'}

            elif action == 'speak':
                dog.speak(params.get('name','single_bark_1'), volume=params.get('volume',80))
                res['msg'] = f"speak {params.get('name','single_bark_1')}"

            elif action == 'head':
                dog.head_move([[params.get('yaw',0), params.get('roll',0), params.get('pitch',0)]],
                              pitch_comp=-40, immediately=True, speed=params.get('speed',80))
                res['msg'] = 'head moved'

            elif action == 'tail':
                dog.tail_move([[params.get('angle',0)]], speed=params.get('speed',80))
                res['msg'] = 'tail moved'

            elif action == 'rgb':
                dog.rgb_strip.set_mode(params.get('mode','breath'), params.get('color','blue'),
                                       bps=params.get('bps',1))
                res['msg'] = 'rgb set'

            elif action == 'wake_up':
                dog.do_action('stretch', speed=20); dog.wait_all_done()
                dog.do_action('stand', speed=50); dog.wait_all_done()
                dog.do_action('wag_tail', step_count=10, speed=100)
                dog.speak('single_bark_1', volume=80)
                res['msg'] = 'awake!'

            elif action == 'stop':
                patrol_flag = False; interactive_flag = False
                dog.body_stop()
                dog.rgb_strip.set_mode('breath', 'black', bps=0.5)
                res['msg'] = 'stopped'

            elif action == 'patrol':
                dur = params.get('duration', 30)
                patrol_flag = True
                dog.do_action('stand', speed=80); dog.wait_all_done(); time.sleep(0.3)
                stand_a = dog.legs_angle_calculation([[0,80],[0,80],[30,75],[30,75]])
                t0 = time.time()
                while patrol_flag and (time.time()-t0) < dur:
                    d = dog.read_distance()
                    if d and 0 < d < 15:
                        dog.body_stop()
                        dog.rgb_strip.set_mode('bark','red',bps=2)
                        dog.tail_move([[0]],speed=80); dog.legs_move([stand_a],speed=70)
                        dog.wait_all_done(); time.sleep(0.5)
                        pa.bark(dog,[0,0,0])
                        while patrol_flag and d and d < 15:
                            d = dog.read_distance(); time.sleep(0.1)
                    else:
                        dog.rgb_strip.set_mode('breath','white',bps=0.5)
                        dog.do_action('forward',step_count=2,speed=98)
                        dog.do_action('shake_head',step_count=1,speed=80)
                        dog.do_action('wag_tail',step_count=5,speed=99)
                    time.sleep(0.01)
                patrol_flag = False; dog.body_stop()
                res['msg'] = f'patrol done {int(time.time()-t0)}s'

            elif action == 'stop_patrol':
                patrol_flag = False; dog.body_stop()
                res['msg'] = 'patrol stopped'

            elif action == 'interactive':
                dur = params.get('duration', 60)
                interactive_flag = True
                dog.do_action('stand', speed=50); dog.wait_all_done()
                t0 = time.time()
                while interactive_flag and (time.time()-t0) < dur:
                    touch = dog.dual_touch.read()
                    d = dog.read_distance()
                    if touch != 'N':
                        dog.rgb_strip.set_mode('breath','green',bps=2)
                        dog.do_action('wag_tail',step_count=5,speed=100)
                        dog.speak('pant',volume=80); time.sleep(1)
                    elif d and 0 < d < 15:
                        dog.rgb_strip.set_mode('bark','red',bps=2)
                        pa.bark(dog,[0,0,0]); time.sleep(1)
                    else:
                        dog.rgb_strip.set_mode('breath','blue',bps=0.5)
                    time.sleep(0.1)
                interactive_flag = False
                res['msg'] = f'interactive done {int(time.time()-t0)}s'

            elif action == 'stop_interactive':
                interactive_flag = False
                res['msg'] = 'stopped'

            elif action == 'snapshot':
                if vilib_ok:
                    from vilib import Vilib as V
                    V.take_photo('pidog_snapshot','/tmp'); time.sleep(0.5)
                    res['msg'] = 'photo taken'; res['path'] = '/tmp/pidog_snapshot.jpg'
                else:
                    res = {'ok': False, 'error': 'Camera not available'}

            elif action == 'check_picked_up':
                if 'imu' in dog.thread_list:
                    ax = dog.accData[0]
                    res['data'] = {'ax': ax, 'is_picked_up': ax > -13000}
                else:
                    res = {'ok': False, 'error': 'IMU not available'}

            elif action == 'sound_direction':
                if hasattr(dog, 'ears'):
                    det = dog.ears.isdetected()
                    res['data'] = {'detected': det, 'direction': dog.ears.read() if det else -1}
                else:
                    res = {'ok': False, 'error': 'No ears'}

            elif action in ('sounds', 'actions'):
                res['data'] = {'actions': list(ACTIONS.keys()), 'presets': list(PRESETS.keys()), 'sounds': SOUNDS}

            elif action == 'kill':
                patrol_flag = False; interactive_flag = False
                dog.body_stop(); dog.legs.servo_move([0]*8, speed=0)
                dog.rgb_strip.set_mode('off','black')
                res['msg'] = 'EMERGENCY STOP'

            else:
                res = {'ok': False, 'error': f'Unknown action: {action}'}

        except Exception as e:
            res = {'ok': False, 'error': str(e)}

        result_queue.put(res)

# HTTP Server
cmd_q, res_q = Queue(), Queue()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path.strip('/')
        if p in ('status','sensors','sounds','actions'):
            self._cmd({'action': p})
        elif p == 'health':
            self._ok({'ok': True, 'version': '3.0'})
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(n)) if n else {}
        self._cmd({'action': self.path.strip('/'), 'params': body})
    def _cmd(self, c):
        cmd_q.put(c)
        try: r = res_q.get(timeout=60)
        except: r = {'ok': False, 'error': 'timeout'}
        self._ok(r)
    def _ok(self, r):
        self.send_response(200 if r.get('ok') else 500)
        self.send_header('Content-Type','application/json')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        self.wfile.write(json.dumps(r).encode())

def main():
    w = Process(target=pidog_worker, args=(cmd_q, res_q), daemon=True)
    w.start(); time.sleep(3)
    srv = HTTPServer(('0.0.0.0', 5001), H)
    print(f"[PROXY] PiDog v3.0 on :5001 (worker:{w.pid})")
    def stop(s,f): srv.shutdown(); w.terminate(); w.join(3); sys.exit(0)
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    srv.serve_forever()

if __name__ == '__main__':
    main()
