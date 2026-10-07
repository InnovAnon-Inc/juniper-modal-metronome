#!/usr/bin/env python3
import asyncio
import http.server
import json
import math
import os
import signal
import socketserver
import sys
import threading
import time
import websockets

from juniper_chimes.chimes import (
    ALL_FAMILIES,
    A4_FREQ,
    CHORD_DURATION_TICKS,
    EDO_STEPS,
    build_descending_circle_of_fifths_progression,
    compute_tone_rhythms,
    compute_tone_rhythms_rh,
    edo24_to_freq_432,
    generate_drones_for_chord,
    get_fixed_do_solfege_24,
    EDOEngine,
)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
HTTP_PORT = 5004
WS_PORT = 65432
POLYGONS_WS_URL = "ws://127.0.0.1:65403"

BPM = 60                       # 1 tick per second
TICK_DURATION = 60.0 / BPM
STATE_FILE = "clock_state.json"

CONNECTED_CLIENTS = set()

# ==============================================================================
# MASTER CLOCK & BROADCAST ENGINE
# ==============================================================================
# Select tuning system: 12, 24, 31, 53, etc.
CURRENT_EDO = 31

class MasterClock:
    def __init__(self):
        self.engine = EDOEngine(edo_steps=CURRENT_EDO, a4_freq=432.0)
        self.inner_family_order = ALL_FAMILIES.copy()
        self.outer_family_order = ALL_FAMILIES.copy()
        self.rebuild_progressions()

    def build_progression(self, families, octave_offset=0):
        progression = []
        current_tonic_step = 5 * self.engine.edo_steps
        total_passes = 84

        for idx in range(total_passes):
            family = families[idx % len(families)]
            active_pc = current_tonic_step % self.engine.edo_steps

            # Generate parallel block for family
            for mode_deg in [4, 1, 5, 2, 6, 3, 7]:  # Lydian down to Locrian
                pitches = self.engine.get_parallel_mode_pitches(family, mode_deg, current_tonic_step)
                meta = {
                    "key": f"Tonic {current_tonic_step % self.engine.edo_steps} {family}",
                    "mode": f"Mode {mode_deg}",
                    "tonic_step": current_tonic_step
                }
                progression.extend(self.engine.generate_diatonic_7th_chords(
                    pitches, meta, current_tonic_step, perceived_drone_pc=active_pc, octave_offset=octave_offset
                ))

            # Step down circle of 5ths in N-EDO
            current_tonic_step = (current_tonic_step - self.engine.fifth_step) % (self.engine.edo_steps * 10)

        return progression


#class MasterClock:
#    def __init__(self):
#        self.inner_family_order = ALL_FAMILIES.copy()
#        self.outer_family_order = ALL_FAMILIES.copy()
#        
#        self.polygon_state = {
#            "N": 12,
#            "step_index": 0,
#            "hits": {
#                "left_hand_7th": False,
#                "right_hand_7th": False,
#                "neg_hit": False
#            }
#        }
#        
#        self.rebuild_progressions()

    def rebuild_progressions(self):
        self.inner_prog = build_descending_circle_of_fifths_progression(
            self.inner_family_order,
            octave_offset=0
        )
        self.outer_prog = build_descending_circle_of_fifths_progression(
            self.outer_family_order,
            octave_offset=2
        )

    def update_polygon_state(self, state: dict):
        if isinstance(state, dict):
            self.polygon_state = state

    def save_state(self):
        data = {
            "master_tick": getattr(self, "master_tick", int(time.time())),
            "inner_family_order": self.inner_family_order,
            "outer_family_order": self.outer_family_order
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
            print(f"[STATE] Saved state at tick {data['master_tick']}.")
        except Exception as e:
            print(f"[STATE] Failed to save state: {e}")

    async def run(self):
        while True:
            now = time.time()
            self.master_tick = int(now)
            elapsed_seconds = self.master_tick

            total_inner = len(self.inner_prog)
            total_outer = len(self.outer_prog)

            inner_idx = (elapsed_seconds // CHORD_DURATION_TICKS) % total_inner
            inner_chord_data = self.inner_prog[inner_idx]

            outer_idx = (elapsed_seconds // (CHORD_DURATION_TICKS * total_inner)) % total_outer
            outer_chord_data = self.outer_prog[outer_idx]

            minute_tick = elapsed_seconds % CHORD_DURATION_TICKS

            inner_freqs = [edo24_to_freq_432(s) for s in inner_chord_data["steps"]]
            outer_freqs = [edo24_to_freq_432(s) for s in outer_chord_data["steps"]]

            hits = self.polygon_state.get("hits", {})
            pos_hit = hits.get("left_hand_7th", False)
            neg_hit = hits.get("neg_hit", False)

            # Left Hand 7th = Positive Polygon
            lh_is_7th = pos_hit
            # Right Hand 7th = Positive Polygon MINUS Negative Polygon
            rh_is_7th = pos_hit and not neg_hit

            lh_rhythms = compute_tone_rhythms(minute_tick, lh_is_7th)
            rh_rhythms = compute_tone_rhythms_rh(minute_tick, rh_is_7th)

            # Master Pitch Anchor: Set Do to Left Hand's active tonic pitch class
            lh_key_pc = inner_chord_data["meta"]["tonic_step"] % EDO_STEPS

            # Left Hand Solfège
            lh_scale_pitches = inner_chord_data["meta"].get("scale_pitches", [])
            lh_scale_solfege = " - ".join([get_fixed_do_solfege_24(p, drone_pc=lh_key_pc) for p in lh_scale_pitches]) if lh_scale_pitches else inner_chord_data["meta"]["scale_solfege"]
            lh_chord_solfege = [get_fixed_do_solfege_24(s, drone_pc=lh_key_pc) for s in inner_chord_data["steps"]]
            lh_drones = generate_drones_for_chord(inner_chord_data, perceived_drone_pc=lh_key_pc)

            # Right Hand Solfège (Fixed to Left Hand's active tonic)
            rh_scale_pitches = outer_chord_data["meta"].get("scale_pitches", [])
            rh_scale_solfege = " - ".join([get_fixed_do_solfege_24(p, drone_pc=lh_key_pc) for p in rh_scale_pitches]) if rh_scale_pitches else outer_chord_data["meta"]["scale_solfege"]
            rh_chord_solfege = [get_fixed_do_solfege_24(s, drone_pc=lh_key_pc) for s in outer_chord_data["steps"]]
            rh_drones = generate_drones_for_chord(outer_chord_data, perceived_drone_pc=lh_key_pc)

            state = {
                "server_time": now,
                "tick": self.master_tick,
                "minute_tick": minute_tick,
                "edo_system": "24-EDO",
                "a4_freq": A4_FREQ,

                "metronome": {
                    "bpm": BPM,
                    "tick_duration_s": TICK_DURATION,
                    "is_second_pulse": True
                },
                "permissible_triggers": {
                    "left_hand_7th_allowed": lh_is_7th,
                    "right_hand_7th_allowed": rh_is_7th,
                    "neg_hit_trigger": neg_hit
                },

                "polygon_sync": self.polygon_state,

                # Left Hand / Inner Loop Data
                "left_hand": {
                    "chord_name": inner_chord_data["chord_name"],
                    "notes": inner_chord_data["notes"],
                    "solfege": lh_chord_solfege,
                    "frequencies": inner_freqs,
                    "tone_rhythms": lh_rhythms,
                    "active_tone_mask": [r["active"] for r in lh_rhythms],
                    "drones": lh_drones,
                    "key": inner_chord_data["meta"]["key"],
                    "mode": inner_chord_data["meta"]["mode"],
                    "scale_solfege": lh_scale_solfege,
                    "scale_notes": inner_chord_data["meta"]["scale_notes"]
                },

                # Right Hand / Outer Loop Data
                "right_hand": {
                    "chord_name": outer_chord_data["chord_name"],
                    "notes": outer_chord_data["notes"],
                    "solfege": rh_chord_solfege,
                    "frequencies": outer_freqs,
                    "tone_rhythms": rh_rhythms,
                    "active_tone_mask": [r["active"] for r in rh_rhythms],
                    "drones": rh_drones,
                    "key": outer_chord_data["meta"]["key"],
                    "mode": outer_chord_data["meta"]["mode"],
                    "scale_solfege": rh_scale_solfege,
                    "scale_notes": outer_chord_data["meta"]["scale_notes"]
                }
            }

            if CONNECTED_CLIENTS:
                payload = json.dumps(state)
                await asyncio.gather(*[client.send(payload) for client in CONNECTED_CLIENTS], return_exceptions=True)

            next_tick_time = math.floor(now) + 1.0
            sleep_time = max(0.001, next_tick_time - time.time())
            await asyncio.sleep(sleep_time)

class MasterClock:
    def __init__(self):
        self.engine = EDOEngine(edo_steps=CURRENT_EDO, a4_freq=432.0)
        self.inner_family_order = ALL_FAMILIES.copy()
        self.outer_family_order = ALL_FAMILIES.copy()
        
        # Initialize polygon_state dictionary
        self.polygon_state = {
            "N": 12,
            "step_index": 0,
            "hits": {
                "left_hand_7th": False,
                "right_hand_7th": False,
                "neg_hit": False
            }
        }
        
        self.rebuild_progressions()

    def rebuild_progressions(self):
        self.inner_prog = self.build_progression(
            self.inner_family_order,
            octave_offset=0
        )
        self.outer_prog = self.build_progression(
            self.outer_family_order,
            octave_offset=2
        )

    def update_polygon_state(self, state: dict):
        if isinstance(state, dict):
            self.polygon_state = state

    def save_state(self):
        data = {
            "master_tick": getattr(self, "master_tick", int(time.time())),
            "inner_family_order": self.inner_family_order,
            "outer_family_order": self.outer_family_order
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
            print(f"[STATE] Saved state at tick {data['master_tick']}.")
        except Exception as e:
            print(f"[STATE] Failed to save state: {e}")

    def build_progression(self, families, octave_offset=0):
        progression = []
        current_tonic_step = 5 * self.engine.edo_steps
        total_passes = 84

        for idx in range(total_passes):
            family = families[idx % len(families)]
            active_pc = current_tonic_step % self.engine.edo_steps

            for mode_deg in [4, 1, 5, 2, 6, 3, 7]:  # Lydian down to Locrian
                pitches = self.engine.get_parallel_mode_pitches(family, mode_deg, current_tonic_step)
                meta = {
                    "key": f"Tonic {current_tonic_step % self.engine.edo_steps} {family}",
                    "mode": f"Mode {mode_deg}",
                    "tonic_step": current_tonic_step
                }
                progression.extend(self.engine.generate_diatonic_7th_chords(
                    pitches, meta, current_tonic_step, perceived_drone_pc=active_pc, octave_offset=octave_offset
                ))

            current_tonic_step = (current_tonic_step - self.engine.fifth_step) % (self.engine.edo_steps * 10)

        return progression

    async def run(self):
        while True:
            now = time.time()
            self.master_tick = int(now)
            elapsed_seconds = self.master_tick

            total_inner = len(self.inner_prog)
            total_outer = len(self.outer_prog)

            inner_idx = (elapsed_seconds // CHORD_DURATION_TICKS) % total_inner
            inner_chord_data = self.inner_prog[inner_idx]

            outer_idx = (elapsed_seconds // (CHORD_DURATION_TICKS * total_inner)) % total_outer
            outer_chord_data = self.outer_prog[outer_idx]

            minute_tick = elapsed_seconds % CHORD_DURATION_TICKS

            inner_freqs = [self.engine.edo_to_freq(s) for s in inner_chord_data["steps"]]
            outer_freqs = [self.engine.edo_to_freq(s) for s in outer_chord_data["steps"]]

            hits = self.polygon_state.get("hits", {})
            pos_hit = hits.get("left_hand_7th", False)
            neg_hit = hits.get("neg_hit", False)

            lh_is_7th = pos_hit
            rh_is_7th = pos_hit and not neg_hit

            lh_rhythms = compute_tone_rhythms(minute_tick, lh_is_7th)
            rh_rhythms = compute_tone_rhythms_rh(minute_tick, rh_is_7th)

            lh_key_pc = inner_chord_data["meta"]["tonic_step"] % self.engine.edo_steps

            lh_chord_solfege = [self.engine.get_solfege(s, drone_pc=lh_key_pc) for s in inner_chord_data["steps"]]
            rh_chord_solfege = [self.engine.get_solfege(s, drone_pc=lh_key_pc) for s in outer_chord_data["steps"]]

            state = {
                "server_time": now,
                "tick": self.master_tick,
                "minute_tick": minute_tick,
                "edo_system": f"{self.engine.edo_steps}-EDO",
                "a4_freq": self.engine.a4_freq,

                "metronome": {
                    "bpm": BPM,
                    "tick_duration_s": TICK_DURATION,
                    "is_second_pulse": True
                },
                "permissible_triggers": {
                    "left_hand_7th_allowed": lh_is_7th,
                    "right_hand_7th_allowed": rh_is_7th,
                    "neg_hit_trigger": neg_hit
                },

                "polygon_sync": self.polygon_state,

                "left_hand": {
                    "chord_name": inner_chord_data["chord_name"],
                    "notes": inner_chord_data["notes"],
                    "solfege": lh_chord_solfege,
                    "frequencies": inner_freqs,
                    "tone_rhythms": lh_rhythms,
                    "active_tone_mask": [r["active"] for r in lh_rhythms],
                    "key": inner_chord_data["meta"]["key"],
                    "mode": inner_chord_data["meta"]["mode"],
                },

                "right_hand": {
                    "chord_name": outer_chord_data["chord_name"],
                    "notes": outer_chord_data["notes"],
                    "solfege": rh_chord_solfege,
                    "frequencies": outer_freqs,
                    "tone_rhythms": rh_rhythms,
                    "active_tone_mask": [r["active"] for r in rh_rhythms],
                    "key": outer_chord_data["meta"]["key"],
                    "mode": outer_chord_data["meta"]["mode"],
                }
            }

            if CONNECTED_CLIENTS:
                payload = json.dumps(state)
                await asyncio.gather(*[client.send(payload) for client in CONNECTED_CLIENTS], return_exceptions=True)

            next_tick_time = math.floor(now) + 1.0
            sleep_time = max(0.001, next_tick_time - time.time())
            await asyncio.sleep(sleep_time)

async def listen_to_polygons_v2(clock: MasterClock):
    while True:
        try:
            print(f"[POLYGON CLIENT] Connecting to polygons-v2 at {POLYGONS_WS_URL}...")
            async with websockets.connect(POLYGONS_WS_URL) as ws:
                print("[POLYGON CLIENT] Connected to polygons-v2 server successfully.")
                async for message in ws:
                    try:
                        data = json.loads(message)
                        clock.update_polygon_state(data)
                    except json.JSONDecodeError:
                        pass
        except (websockets.exceptions.ConnectionClosedError, OSError) as e:
            print(f"[POLYGON CLIENT] Connection lost: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3.0)

async def ws_handler(websocket):
    CONNECTED_CLIENTS.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        CONNECTED_CLIENTS.remove(websocket)

class HTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            template_path = os.path.join('templates', 'index.html')
            if os.path.exists(template_path):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                with open(template_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
        super().do_GET()

def start_http_server():
    os.makedirs('templates', exist_ok=True)
    with socketserver.TCPServer(("", HTTP_PORT), HTTPHandler) as httpd:
        print(f"[HTTP SERVER] Chimes server web interface running at http://0.0.0.0:{HTTP_PORT}")
        httpd.serve_forever()

async def main():
    clock = MasterClock()

    def handle_exit(signum, frame):
        print("\n[SERVER] Shutting down chimes server...")
        clock.save_state()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    threading.Thread(target=start_http_server, daemon=True).start()
    asyncio.create_task(listen_to_polygons_v2(clock))

    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        print(f"[WS SERVER] Broadcasting 24-EDO time sync & chords on ws://0.0.0.0:{WS_PORT}")
        await clock.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
