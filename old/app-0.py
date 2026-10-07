#! /usr/bin/env python3

import asyncio
import http.server
import json
import math
import random
import socketserver
import threading
import time
import websockets

# ==========================================
# CONFIGURATION & TUNING
# ==========================================
HTTP_PORT = 8001
WS_PORT = 65430
BPM = 60                       # 1 tick per second
TICK_DURATION = 60.0 / BPM
A4_FREQ = 432.0                # Master Reference Pitch

# ==========================================
# BJORKLUND EUCLIDEAN RHYTHM ALGORITHM
# ==========================================
def bjorklund(steps: int, pulses: int) -> list[int]:
    if pulses <= 0:
        return [0] * steps
    if pulses >= steps:
        return [1] * steps

    pattern = [[1] for _ in range(pulses)]
    remainder = [[0] for _ in range(steps - pulses)]

    while len(remainder) > 1:
        num_patterns = len(pattern)
        num_remainders = len(remainder)
        
        count = min(num_patterns, num_remainders)
        for i in range(count):
            pattern[i].extend(remainder.pop(0))
            
        if num_remainders > num_patterns:
            remainder = remainder

    pattern.extend(remainder)
    return [item for sublist in pattern for item in sublist]

# ==========================================
# COPRIME EUCLIDEAN GENERATOR & PROGRESSION
# ==========================================
def gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a

def get_coprime_pulses(steps: int) -> list[int]:
    result = [k for k in range(1, steps) if gcd(k, steps) == 1]
    if len(result) == 1:
        return result
    assert result[0] == 1
    return result[1:]

class EuclideanProgression:
    def __init__(self, step_cycles=[16, 12, 13, 15], repeats_per_rhythm=7):
        self.step_cycles = step_cycles
        self.repeats_per_rhythm = repeats_per_rhythm

        self.sequence = []
        for n in self.step_cycles:
            coprimes = get_coprime_pulses(n)
            for k in coprimes:
                pattern = bjorklund(n, k)
                self.sequence.append({
                    "steps": n,
                    "pulses": k,
                    "pattern": pattern
                })

        self.seq_idx = 0
        self.current_repeat = 0
        self.step_in_pattern = 0

    def tick(self) -> tuple[bool, int, int, int]:
        curr = self.sequence[self.seq_idx]
        pattern = curr["pattern"]

        hit = bool(pattern[self.step_in_pattern])
        step_idx = self.step_in_pattern

        self.step_in_pattern += 1
        if self.step_in_pattern >= curr["steps"]:
            self.step_in_pattern = 0
            self.current_repeat += 1

            if self.current_repeat >= self.repeats_per_rhythm:
                self.current_repeat = 0
                self.seq_idx = (self.seq_idx + 1) % len(self.sequence)
                next_rhythm = self.sequence[self.seq_idx]
                print(f"\n[RHYTHM EVOLVED] E({next_rhythm['pulses']}, {next_rhythm['steps']}) "
                      f"| Repeating {self.repeats_per_rhythm}x\n")

        return hit, step_idx, curr["pulses"], curr["steps"]

# ==========================================
# HARMONICALLY ACCURATE DIATONIC SOLFEGE
# ==========================================
MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]

EXACT_SOLFEGE = {
    (1,  0): "Do",
    (2, -1): "Ra", (2, 0): "Re", (2, 1): "Ri",
    (3, -2): "Rri", (3, -1): "Me", (3, 0): "Mi",
    (4, -1): "Fe", (4, 0): "Fa", (4, 1): "Fi",
    (5, -1): "Se", (5, 0): "So", (5, 1): "Si",
    (6, -2): "Leh", (6, -1): "Le", (6, 0): "La",
    (7, -2): "Tas", (7, -1): "Te", (7, 0): "Ti"
}

def get_exact_modal_solfege(parent_name: str, mode_degree: int) -> list[str]:
    parent_pcs = PARENT_SCALES[parent_name]
    num_notes = len(parent_pcs)
    mode_offset = parent_pcs[mode_degree - 1]

    solfege_spelling = []
    
    for i in range(num_notes):
        degree = i + 1
        parent_idx = (i + mode_degree - 1) % num_notes
        actual_semitones = (parent_pcs[parent_idx] - mode_offset) % 12
        expected_semitones = MAJOR_INTERVALS[i]
        
        alteration = actual_semitones - expected_semitones
        if alteration > 6: alteration -= 12
        if alteration < -6: alteration += 12

        s_syllable = EXACT_SOLFEGE.get((degree, alteration), f"Deg{degree}({alteration})")
        solfege_spelling.append(s_syllable)

    return solfege_spelling

# ==========================================
# SCALE & HARMONIC GENERATOR
# ==========================================
NOTE_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

PARENT_SCALES = {
    "Major": [0, 2, 4, 5, 7, 9, 11],
    "Harmonic Minor": [0, 2, 3, 5, 7, 8, 11],
    "Melodic Minor": [0, 2, 3, 5, 7, 9, 11],
    "Harmonic Major": [0, 2, 4, 5, 7, 8, 11],
    "Double Harmonic Major": [0, 1, 4, 5, 7, 8, 11],
    "Neapolitan Major": [0, 1, 3, 5, 7, 9, 11],
    "Neapolitan Minor": [0, 1, 3, 5, 7, 8, 11],
}

MODE_ORDERING = {
    "Major": [4, 1, 5, 2, 6, 3, 7],
    "Harmonic Minor": [6, 3, 7, 1, 4, 5, 2],
    "Melodic Minor": [3, 4, 1, 5, 2, 6, 7],
    "Harmonic Major": [2, 1, 5, 4, 3, 7, 6],
    "Double Harmonic Major": [4, 1, 5, 2, 6, 3, 7],
    "Neapolitan Major": [4, 7, 1, 5, 2, 6, 3],
    "Neapolitan Minor": [4, 7, 1, 5, 2, 3, 6],
}

MODE_NAMES = {
    "Major": ["Ionian", "Dorian", "Phrygian", "Lydian", "Mixolydian", "Aeolian", "Locrian"],
    "Harmonic Minor": ["Harmonic Minor", "Locrian 6", "Ionian #5", "Dorian #4", "Phrygian Dominant", "Lydian #2", "Super Locrian bb7"],
    "Melodic Minor": ["Melodic Minor", "Dorian b2", "Lydian Augmented", "Lydian Dominant", "Mixolydian b6", "Half-Diminished", "Altered Scale"],
    "Harmonic Major": ["Harmonic Major", "Dorian b5", "Phrygian b4", "Lydian b3", "Mixolydian b2", "Lydian Augmented #2", "Locrian bb7"],
    "Double Harmonic Major": ["Double Harmonic Major", "Lydian #2 #6", "Ultra Phrygian", "Hungarian Minor", "Harmonic Minor b5", "Ionian #2 #5", "Locrian bb3 bb7"],
    "Neapolitan Major": ["Neapolitan Major", "Lydian #6", "Major Augmented #5", "Lydian Dominant b6", "Major Locrian", "Half-Diminished b4", "Altered Dominant bb3"],
    "Neapolitan Minor": ["Neapolitan Minor", "Lydian #6 #3", "Major #5", "Hungarian Gypsy", "Locrian Major", "Ionian #2", "Ultra Locrian"]
}

# 1 - 4 - 5 - 6 - 3 - 2 - 7 Chord Progression Order
CHORD_PROGRESSION_ORDER = [0, 3, 4, 5, 2, 1, 6]

def get_parallel_mode_pitches(parent_name: str, mode_degree: int, tonic_midi: int) -> list[int]:
    scale = PARENT_SCALES[parent_name]
    num_notes = len(scale)
    mode_offset = scale[mode_degree - 1]
    mode_indices = [(i + mode_degree - 1) % num_notes for i in range(num_notes)]
    
    mode_pitches = []
    for idx in mode_indices:
        interval = (scale[idx] - mode_offset) % 12
        mode_pitches.append(tonic_midi + interval)
        
    return mode_pitches

def generate_diatonic_7th_chords(scale_pitches: list[int], mode_solfege: list[str], meta: dict) -> list[dict]:
    chords = []
    num_notes = len(scale_pitches)

    for i in CHORD_PROGRESSION_ORDER:
        chord_midis = [
            scale_pitches[i % num_notes],
            scale_pitches[(i + 2) % num_notes],
            scale_pitches[(i + 4) % num_notes],
            scale_pitches[(i + 6) % num_notes]
        ]

        chord_solfege = [
            mode_solfege[i % num_notes],
            mode_solfege[(i + 2) % num_notes],
            mode_solfege[(i + 4) % num_notes],
            mode_solfege[(i + 6) % num_notes]
        ]

        root_pc = chord_midis[0] % 12
        root_midi = 60 + root_pc

        formatted_midis = [root_midi]
        prev_midi = root_midi

        for midi_val in chord_midis[1:]:
            pc = midi_val % 12
            interval = (pc - root_pc) % 12
            if interval == 0:
                interval = 12
            candidate = root_midi + interval
            
            while candidate <= prev_midi:
                candidate += 12
                
            formatted_midis.append(candidate)
            prev_midi = candidate

        if formatted_midis[-1] >= 72:
            formatted_midis = [m - 12 for m in formatted_midis]

        formatted_notes = []
        for m in formatted_midis:
            name = NOTE_NAMES[m % 12]
            octave = (m // 12) - 1
            formatted_notes.append(f"{name}{octave}")

        chords.append({
            "duration": 60,
            "notes": formatted_notes,
            "solfege": chord_solfege,
            "meta": meta
        })
    return chords

def generate_parallel_family_block(family_name: str, tonic_midi: int) -> list[dict]:
    block = []
    tonic_name = NOTE_NAMES[tonic_midi % 12]
    
    for mode_deg in MODE_ORDERING[family_name]:
        pitches = get_parallel_mode_pitches(family_name, mode_deg, tonic_midi)
        mode_label = MODE_NAMES[family_name][mode_deg - 1]
        
        mode_solfege = get_exact_modal_solfege(family_name, mode_deg)
        scale_solfege_str = " - ".join(mode_solfege)
        
        meta = {
            "key": f"{tonic_name} Parallel {family_name}",
            "mode": f"Mode {mode_deg}: {tonic_name} {mode_label}",
            "tonic_name": tonic_name,
            "scale_solfege": scale_solfege_str
        }
        block.extend(generate_diatonic_7th_chords(pitches, mode_solfege, meta))
    return block

def build_parallel_chromatic_progression(families: list[str]) -> list[dict]:
    progression = []
    current_tonic_midi = 60  # Start on C4

    for cycle in range(12):
        for family in families:
            progression.extend(generate_parallel_family_block(family, current_tonic_midi))
            
        current_tonic_midi -= 1

    print(f"[STARTUP] Parallel chromatic progression generated: {len(progression)} total chords across 12 tonics.")
    return progression

# ==========================================
# WEBSOCKET STATE BROADCASTER
# ==========================================
CONNECTED_CLIENTS = set()

class MasterClock:
    def __init__(self, progression, moduli=(3, 4, 5)):
        self.progression = progression
        self.moduli = moduli
        self.master_tick = 0
        self.euc_engine = EuclideanProgression(step_cycles=[16, 12, 13, 15], repeats_per_rhythm=7)
        self.current_chord_idx = 0
        self.ticks_in_chord = 0

    def get_sub_root_doubler(self, note_str: str) -> str:
        name = note_str[:-1]
        octave = int(note_str[-1])
        return f"{name}{max(1, octave - 1)}"

    def get_tonic_drones(self, root_name: str) -> tuple[str, str]:
        """Returns octave 0 (infrasonic boundary) and octave 1 (audible sub) notes."""
        return f"{root_name}0", f"{root_name}1"

    async def run(self):
        while True:
            self.master_tick += 1
            self.ticks_in_chord += 1

            chord_data = self.progression[self.current_chord_idx]
            k_ticks = chord_data["duration"]
            chord_notes = chord_data["notes"]
            chord_solfege = chord_data["solfege"]
            meta_info = chord_data["meta"]

            if self.ticks_in_chord > k_ticks:
                self.current_chord_idx = (self.current_chord_idx + 1) % len(self.progression)
                self.ticks_in_chord = 1
                chord_data = self.progression[self.current_chord_idx]
                k_ticks = chord_data["duration"]
                chord_notes = chord_data["notes"]
                chord_solfege = chord_data["solfege"]
                meta_info = chord_data["meta"]

            triad_trigs = [self.master_tick % m == 0 for m in self.moduli]
            positions = [self.master_tick % m for m in self.moduli]
            
            v4_trig, v4_step, pulses, total_steps = self.euc_engine.tick()

            sub_root_note = self.get_sub_root_doubler(chord_notes[0])
            tonic_0, tonic_1 = self.get_tonic_drones(meta_info["tonic_name"])

            state = {
                "server_time": time.time(),
                "tick": self.master_tick,
                "chord": chord_notes,
                "chord_solfege": chord_solfege,
                "scale_solfege": meta_info["scale_solfege"],
                "sub_root": sub_root_note,
                "drone_tonic_0": tonic_0,
                "drone_tonic_1": tonic_1,
                "key": meta_info["key"],
                "mode": meta_info["mode"],
                "triad_trigs": triad_trigs,
                "v4_trig": v4_trig,
                "positions": positions,
                "v4_step": v4_step,
                "v4_info": f"E({pulses},{total_steps})",
                "a4_freq": A4_FREQ
            }

            if CONNECTED_CLIENTS:
                payload = json.dumps(state)
                await asyncio.gather(*[client.send(payload) for client in CONNECTED_CLIENTS])

            await asyncio.sleep(TICK_DURATION)

async def ws_handler(websocket):
    CONNECTED_CLIENTS.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        CONNECTED_CLIENTS.remove(websocket)

# ==========================================
# INLINE HTML WEBPAGE WITH WEB AUDIO API SYNTH
# ==========================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CRT Compound Clock Engine</title>
    <style>
        body { background: #121212; color: #00ffcc; font-family: monospace; text-align: center; padding: 20px; }
        button { background: #00ffcc; color: #121212; border: none; padding: 15px 30px; font-size: 1.2rem; font-weight: bold; cursor: pointer; border-radius: 5px; }
        #status { margin-top: 20px; font-size: 1.1rem; }
        .display-box { border: 1px solid #00ffcc; padding: 15px; margin: 20px auto; max-width: 500px; text-align: left; }
        .highlight { color: #ff007f; font-weight: bold; }
        .solfege-text { color: #ffe600; font-weight: bold; }
        .sub-info { color: #00aaff; font-weight: bold; }
    </style>
</head>
<body>
    <h1>CRT Clock Sync Node</h1>
    <button id="start-btn">ENABLE AUDIO SYNC</button>
    <div id="status">Audio Engine Standing By...</div>

    <div class="display-box">
        <div>Tick: <span id="lbl-tick">0</span></div>
        <div>Active Key: <span id="lbl-key" class="highlight">--</span></div>
        <div>Mode Info: <span id="lbl-mode" class="highlight">--</span></div>
        <div>Scale Solfège (Fixed Do): <span id="lbl-scale-solf" class="solfege-text">--</span></div>
        <div>Active Chord: <span id="lbl-chord">--</span></div>
        <div>Chord Solfège: <span id="lbl-chord-solf" class="solfege-text">--</span></div>
        <div>Sub-Root Drone: <span id="lbl-sub" class="sub-info">--</span></div>
        <div>Infrasonic Tonic (O0): <span id="lbl-drone0" class="sub-info">--</span></div>
        <div>Audible Sub Tonic (O1): <span id="lbl-drone1" class="sub-info">--</span></div>
        <div>Mod Dials: <span id="lbl-dials">--</span></div>
        <div>Euclidean Step: <span id="lbl-euc">--</span></div>
    </div>

    <script>
        const NOTE_SEMITONES = {
            'C': -9, 'C#': -8, 'Db': -8, 'D': -7, 'D#': -6, 'Eb': -6,
            'E': -5, 'F': -4, 'F#': -3, 'Gb': -3, 'G': -2, 'G#': -1,
            'Ab': -1, 'A': 0, 'A#': 1, 'Bb': 1, 'B': 2
        };

        let audioCtx = null;
        let ws = null;
        
        let droneOsc0 = null; // Infrasonic Tonic Drone (Octave 0)
        let droneGain0 = null;
        let droneOsc1 = null; // Sub Tonic Drone (Octave 1)
        let droneGain1 = null;
        
        let subRootOsc = null; // Active Chord Root Doubler Drone
        let subRootGain = null;

        function noteToFreq(noteStr, refA4) {
            let name = noteStr.slice(0, -1);
            let octave = parseInt(noteStr.slice(-1));
            let semitones = NOTE_SEMITONES[name] + (octave - 4) * 12;
            return refA4 * Math.pow(2.0, semitones / 12.0);
        }

        function initDrones(refA4) {
            // Master Infrasonic Tonic Drone (Octave 0 ~16-20 Hz)
            droneOsc0 = audioCtx.createOscillator();
            droneGain0 = audioCtx.createGain();
            droneOsc0.type = 'sine';
            droneOsc0.frequency.setValueAtTime(noteToFreq("C0", refA4), audioCtx.currentTime);
            droneGain0.gain.setValueAtTime(0.30, audioCtx.currentTime);
            droneOsc0.connect(droneGain0);
            droneGain0.connect(audioCtx.destination);
            droneOsc0.start();

            // Master Sub-Tonic Drone (Octave 1 ~32-40 Hz)
            droneOsc1 = audioCtx.createOscillator();
            droneGain1 = audioCtx.createGain();
            droneOsc1.type = 'sine';
            droneOsc1.frequency.setValueAtTime(noteToFreq("C1", refA4), audioCtx.currentTime);
            droneGain1.gain.setValueAtTime(0.20, audioCtx.currentTime);
            droneOsc1.connect(droneGain1);
            droneGain1.connect(audioCtx.destination);
            droneOsc1.start();

            // Sustained Sub-Root Doubler Drone
            subRootOsc = audioCtx.createOscillator();
            subRootGain = audioCtx.createGain();
            subRootOsc.type = 'sine';
            subRootOsc.frequency.setValueAtTime(noteToFreq("C2", refA4), audioCtx.currentTime);
            subRootGain.gain.setValueAtTime(0.25, audioCtx.currentTime);
            subRootOsc.connect(subRootGain);
            subRootGain.connect(audioCtx.destination);
            subRootOsc.start();
        }

        function updateDroneFreqs(t0, t1, targetSubRootNote, refA4) {
            if (droneOsc0) {
                let freq0 = noteToFreq(t0, refA4);
                droneOsc0.frequency.setTargetAtTime(freq0, audioCtx.currentTime, 0.25);
            }
            if (droneOsc1) {
                let freq1 = noteToFreq(t1, refA4);
                droneOsc1.frequency.setTargetAtTime(freq1, audioCtx.currentTime, 0.25);
            }
            if (subRootOsc) {
                let targetSubRootFreq = noteToFreq(targetSubRootNote, refA4);
                subRootOsc.frequency.setTargetAtTime(targetSubRootFreq, audioCtx.currentTime, 0.15);
            }
        }

        function playTone(freq, duration, releaseTime = 2.5, volume = 0.4) {
            if (!audioCtx) return;
            let osc1 = audioCtx.createOscillator();
            let osc2 = audioCtx.createOscillator();
            let gain = audioCtx.createGain();

            osc1.type = 'sine';
            osc1.frequency.setValueAtTime(freq, audioCtx.currentTime);
            
            osc2.type = 'sine';
            osc2.frequency.setValueAtTime(freq * 2.0, audioCtx.currentTime);

            gain.gain.setValueAtTime(volume * 0.5, audioCtx.currentTime);
            
            let totalTime = audioCtx.currentTime + releaseTime;
            gain.gain.exponentialRampToValueAtTime(0.0001, totalTime);

            osc1.connect(gain);
            osc2.connect(gain);
            gain.connect(audioCtx.destination);

            osc1.start();
            osc2.start();
            
            osc1.stop(totalTime);
            osc2.stop(totalTime);
        }

        document.getElementById('start-btn').addEventListener('click', () => {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            document.getElementById('start-btn').style.display = 'none';
            document.getElementById('status').innerText = 'Syncing with Server...';

            initDrones(432.0);

            let wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            let wsUrl = wsProtocol + '//' + window.location.hostname + ':65430';
            ws = new WebSocket(wsUrl);

            ws.onmessage = (event) => {
                let data = JSON.parse(event.data);
                document.getElementById('lbl-tick').innerText = data.tick;
                document.getElementById('lbl-key').innerText = data.key;
                document.getElementById('lbl-mode').innerText = data.mode;
                document.getElementById('lbl-scale-solf').innerText = data.scale_solfege;
                document.getElementById('lbl-chord').innerText = JSON.stringify(data.chord);
                document.getElementById('lbl-chord-solf').innerText = JSON.stringify(data.chord_solfege);
                document.getElementById('lbl-sub').innerText = data.sub_root;
                document.getElementById('lbl-drone0').innerText = data.drone_tonic_0;
                document.getElementById('lbl-drone1').innerText = data.drone_tonic_1;
                document.getElementById('lbl-dials').innerText = JSON.stringify(data.positions);
                document.getElementById('lbl-euc').innerText = 
                    data.v4_info + ' Step ' + data.v4_step + (data.v4_trig ? ' [HIT]' : ' [REST]');
                document.getElementById('status').innerText = 'CONNECTED & SYNCHRONIZED';

                updateDroneFreqs(data.drone_tonic_0, data.drone_tonic_1, data.sub_root, data.a4_freq);

                data.triad_trigs.forEach((trig, idx) => {
                    if (trig) {
                        let freq = noteToFreq(data.chord[idx], data.a4_freq);
                        playTone(freq, 1.0, 3.5, 0.35);
                    }
                });

                if (data.v4_trig) {
                    let freq = noteToFreq(data.chord[3], data.a4_freq);
                    playTone(freq, 0.5, 2.0, 0.25);
                }
            };
        });
    </script>
</body>
</html>
"""

class HTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode('utf-8'))

def start_http_server():
    with socketserver.TCPServer(("", HTTP_PORT), HTTPHandler) as httpd:
        print(f"[HTTP SERVER] Hosting Web Player on http://0.0.0.0:{HTTP_PORT}")
        httpd.serve_forever()

# ==========================================
# MAIN ENTRY POINT
# ==========================================
async def main():
    ALL_FAMILIES = [
        "Major", "Harmonic Minor", "Melodic Minor",
        "Harmonic Major", "Double Harmonic Major",
        "Neapolitan Major", "Neapolitan Minor"
    ]
    progression = build_parallel_chromatic_progression(ALL_FAMILIES)
    clock = MasterClock(progression)

    threading.Thread(target=start_http_server, daemon=True).start()

    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        print(f"[WS SERVER] Broadcasting time sync on ws://0.0.0.0:{WS_PORT}")
        await clock.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer terminated.")
