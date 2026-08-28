#!/usr/bin/env python3

import asyncio
import http.server
import json
import math
import socketserver
import threading
import time
import websockets

# ==========================================
# CONFIGURATION & TUNING
# ==========================================
HTTP_PORT = 8000
WS_PORT = 65432
BPM = 60                       # 1 tick per second
TICK_DURATION = 60.0 / BPM
CHORD_DURATION_TICKS = 60      # Real-time minute (60s) per inner chord change
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

    pattern.extend(remainder)
    return [item for sublist in pattern for item in sublist]

def gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a

def get_coprime_pulses(steps: int) -> list[int]:
    result = [k for k in range(1, steps) if gcd(k, steps) == 1]
    if len(result) == 1:
        return result
    return result[1:]

class EuclideanProgression:
    def __init__(self, step_cycles=list(range(3, 33)), repeats_per_rhythm=7, invert_pattern=False):
        self.step_cycles = step_cycles
        self.repeats_per_rhythm = repeats_per_rhythm
        self.invert_pattern = invert_pattern
        self.sequence = []
        for n in self.step_cycles:
            coprimes = get_coprime_pulses(n)
            for k in coprimes:
                pattern = bjorklund(n, k)
                if self.invert_pattern:
                    pattern = pattern[::-1]
                self.sequence.append({
                    "steps": n,
                    "pulses": k,
                    "pattern": pattern
                })
        self.seq_idx = 0
        self.current_repeat = 0
        self.step_in_pattern = 0

    def tick(self, offset_ticks: int = 0) -> tuple[bool, int, int, int]:
        curr = self.sequence[self.seq_idx]
        pattern = curr["pattern"]

        eval_idx = (self.step_in_pattern + offset_ticks) % len(pattern)
        hit = bool(pattern[eval_idx])
        step_idx = self.step_in_pattern

        self.step_in_pattern += 1
        if self.step_in_pattern >= curr["steps"]:
            self.step_in_pattern = 0
            self.current_repeat += 1
            if self.current_repeat >= self.repeats_per_rhythm:
                self.current_repeat = 0
                self.seq_idx = (self.seq_idx + 1) % len(self.sequence)

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

CHORD_PROGRESSION_ORDER = [0, 3, 4, 5, 2, 1, 6]

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

def generate_diatonic_7th_chords(scale_pitches: list[int], mode_solfege: list[str], meta: dict, octave_offset: int = 0) -> list[dict]:
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
        root_midi = (60 + (octave_offset * 12)) + root_pc

        formatted_midis = [root_midi]
        prev_midi = root_midi

        for midi_val in chord_midis[1:]:
            pc = midi_val % 12
            interval = (pc - root_pc) % 12
            if interval == 0: interval = 12
            candidate = root_midi + interval

            while candidate <= prev_midi:
                candidate += 12

            formatted_midis.append(candidate)
            prev_midi = candidate

        formatted_notes = []
        for m in formatted_midis:
            name = NOTE_NAMES[m % 12]
            octave = (m // 12) - 1
            formatted_notes.append(f"{name}{octave}")

        chords.append({
            "duration": CHORD_DURATION_TICKS,
            "notes": formatted_notes,
            "solfege": chord_solfege,
            "meta": meta
        })
    return chords

def generate_parallel_family_block(family_name: str, tonic_midi: int, octave_offset: int = 0) -> list[dict]:
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
        block.extend(generate_diatonic_7th_chords(pitches, mode_solfege, meta, octave_offset=octave_offset))
    return block

def build_parallel_chromatic_progression(families: list[str], octave_offset: int = 0) -> list[dict]:
    progression = []
    current_tonic_midi = 60

    for cycle in range(12):
        for family in families:
            progression.extend(generate_parallel_family_block(family, current_tonic_midi, octave_offset=octave_offset))
        current_tonic_midi -= 1

    return progression

# ==========================================
# WEBSOCKET STATE BROADCASTER
# ==========================================
CONNECTED_CLIENTS = set()

class MasterClock:
    def __init__(self, inner_prog, outer_prog, moduli=(3, 4, 5)):
        self.inner_prog = inner_prog
        self.outer_prog = outer_prog
        self.moduli = moduli
        self.master_tick = 0
        
        self.inner_euc_engine = EuclideanProgression(step_cycles=list(range(3, 33)), repeats_per_rhythm=7, invert_pattern=False)
        self.outer_euc_engine = EuclideanProgression(step_cycles=list(range(3, 33)), repeats_per_rhythm=7, invert_pattern=True)
        
        self.start_time = time.time()

    def get_sub_root_doubler(self, note_str: str) -> str:
        name = note_str[:-1]
        octave = int(note_str[-1])
        return f"{name}{max(1, octave - 1)}"

    def get_tonic_drones(self, root_name: str) -> tuple[str, str]:
        return f"{root_name}0", f"{root_name}1"

    async def run(self):
        while True:
            self.master_tick += 1
            now = time.time()
            elapsed_seconds = int(now - self.start_time)

            total_inner = len(self.inner_prog)
            total_outer = len(self.outer_prog)

            # INNER LOOP: Steps every 60 seconds (1 minute per chord)
            inner_idx = (elapsed_seconds // CHORD_DURATION_TICKS) % total_inner
            inner_chord_data = self.inner_prog[inner_idx]

            # OUTER LOOP: Steps once per FULL ITERATION of the inner loop progression
            outer_idx = (elapsed_seconds // (CHORD_DURATION_TICKS * total_inner)) % total_outer
            outer_chord_data = self.outer_prog[outer_idx]

            minute_tick = elapsed_seconds % CHORD_DURATION_TICKS

            inner_triad_trigs = [self.master_tick % m == 0 for m in self.moduli]
            outer_triad_trigs = [(self.master_tick + 30) % m == 0 for m in self.moduli]

            positions = [self.master_tick % m for m in self.moduli]

            v4_trig_inner, v4_step_inner, pulses_in, total_steps_in = self.inner_euc_engine.tick(offset_ticks=0)
            v4_trig_outer, v4_step_outer, pulses_out, total_steps_out = self.outer_euc_engine.tick(offset_ticks=30)

            sub_root_note = self.get_sub_root_doubler(inner_chord_data["notes"][0])
            tonic_0, tonic_1 = self.get_tonic_drones(inner_chord_data["meta"]["tonic_name"])

            state = {
                "server_time": now,
                "tick": self.master_tick,
                "minute_tick": minute_tick,

                # Inner Main Loop
                "chord": inner_chord_data["notes"],
                "chord_solfege": inner_chord_data["solfege"],
                "key": inner_chord_data["meta"]["key"],
                "mode": inner_chord_data["meta"]["mode"],
                "scale_solfege": inner_chord_data["meta"]["scale_solfege"],

                # Outer Polytonal Loop
                "outer_chord": outer_chord_data["notes"],
                "outer_solfege": outer_chord_data["solfege"],
                "outer_key": outer_chord_data["meta"]["key"],
                "outer_mode": outer_chord_data["meta"]["mode"],

                # Acoustics & Moduli Triggers
                "sub_root": sub_root_note,
                "drone_tonic_0": tonic_0,
                "drone_tonic_1": tonic_1,
                "inner_triad_trigs": inner_triad_trigs,
                "outer_triad_trigs": outer_triad_trigs,
                "v4_trig": v4_trig_inner,
                "v4_trig_outer": v4_trig_outer,
                "positions": positions,
                "v4_step": v4_step_inner,
                "v4_info": f"E({pulses_in},{total_steps_in})",
                "a4_freq": A4_FREQ
            }

            if CONNECTED_CLIENTS:
                payload = json.dumps(state)
                await asyncio.gather(*[client.send(payload) for client in CONNECTED_CLIENTS], return_exceptions=True)

            next_tick = self.start_time + self.master_tick * TICK_DURATION
            sleep_time = max(0.001, next_tick - time.time())
            await asyncio.sleep(sleep_time)

async def ws_handler(websocket):
    CONNECTED_CLIENTS.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        CONNECTED_CLIENTS.remove(websocket)

# ==========================================
# INLINE HTML WEBPAGE WITH POLYTONAL VIEWER
# ==========================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CRT Polytonal Clock Engine</title>
    <style>
        body { background: #121212; color: #00ffcc; font-family: monospace; text-align: center; padding: 20px; }
        button { background: #00ffcc; color: #121212; border: none; padding: 15px 30px; font-size: 1.2rem; font-weight: bold; cursor: pointer; border-radius: 5px; }
        #status { margin-top: 20px; font-size: 1.1rem; }
        .display-container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; max-width: 1000px; margin: 20px auto; }
        .display-box { border: 1px solid #00ffcc; padding: 15px; flex: 1; min-width: 300px; text-align: left; background: #181818; }
        .outer-box { border-color: #ff007f; }
        .highlight { color: #ff007f; font-weight: bold; }
        .solfege-text { color: #ffe600; font-weight: bold; }
        .sub-info { color: #00aaff; font-weight: bold; }
    </style>
</head>
<body>
    <h1>CRT Polytonal Clock Engine</h1>
    <button id="start-btn">ENABLE AUDIO SYNC</button>
    <div id="status">Audio Engine Standing By...</div>

    <audio id="silent-keepalive" loop playsinline src="data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="></audio>

    <div class="display-container">
        <div class="display-box">
            <h3>INNER LOOP (60s Step)</h3>
            <div>Master Tick: <span id="lbl-tick">0</span></div>
            <div>Minute Sec: <span id="lbl-sec">0</span>s / 60s</div>
            <div>Active Key: <span id="lbl-key" class="highlight">--</span></div>
            <div>Mode Info: <span id="lbl-mode" class="highlight">--</span></div>
            <div>Scale Solfège: <span id="lbl-scale-solf" class="solfege-text">--</span></div>
            <div>Active Chord: <span id="lbl-chord">--</span></div>
            <div>Chord Solfège: <span id="lbl-chord-solf" class="solfege-text">--</span></div>
            <div>Sub-Root Drone: <span id="lbl-sub" class="sub-info">--</span></div>
            <div>Infrasonic (O0): <span id="lbl-drone0" class="sub-info">--</span></div>
            <div>Sub Tonic (O1): <span id="lbl-drone1" class="sub-info">--</span></div>
        </div>

        <div class="display-box outer-box">
            <h3 style="color:#ff007f;">OUTER LOOP (+2 Oct / Macro Cycle Step)</h3>
            <div>Outer Key: <span id="lbl-outer-key" class="highlight">--</span></div>
            <div>Outer Mode: <span id="lbl-outer-mode" class="highlight">--</span></div>
            <div>Outer Chord: <span id="lbl-outer-chord">--</span></div>
            <div>Outer Solfège: <span id="lbl-outer-solf" class="solfege-text">--</span></div>
            <br>
            <div>Mod Dials: <span id="lbl-dials">--</span></div>
            <div>Inner Euclidean: <span id="lbl-euc">--</span></div>
            <div>Outer Euclidean (+30s): <span id="lbl-outer-euc">--</span></div>
        </div>
    </div>

    <script>
        const NOTE_SEMITONES = {
            'C': -9, 'C#': -8, 'Db': -8, 'D': -7, 'D#': -6, 'Eb': -6,
            'E': -5, 'F': -4, 'F#': -3, 'Gb': -3, 'G': -2, 'G#': -1,
            'Ab': -1, 'A': 0, 'A#': 1, 'Bb': 1, 'B': 2
        };

        let audioCtx = null;
        let ws = null;
        
        let droneOsc0 = null, droneGain0 = null;
        let droneOsc1 = null, droneGain1 = null;
        let subRootOsc = null, subRootGain = null;

        function noteToFreq(noteStr, refA4) {
            let name = noteStr.slice(0, -1);
            let octave = parseInt(noteStr.slice(-1));
            let semitones = NOTE_SEMITONES[name] + (octave - 4) * 12;
            return refA4 * Math.pow(2.0, semitones / 12.0);
        }

        function initDrones(refA4) {
            let now = audioCtx.currentTime;

            droneOsc0 = audioCtx.createOscillator();
            droneGain0 = audioCtx.createGain();
            droneOsc0.type = 'sine';
            droneOsc0.frequency.setValueAtTime(noteToFreq("C0", refA4), now);
            droneGain0.gain.setValueAtTime(0.25, now);
            droneOsc0.connect(droneGain0);
            droneGain0.connect(audioCtx.destination);
            droneOsc0.start(now);

            droneOsc1 = audioCtx.createOscillator();
            droneGain1 = audioCtx.createGain();
            droneOsc1.type = 'sine';
            droneOsc1.frequency.setValueAtTime(noteToFreq("C1", refA4), now);
            droneGain1.gain.setValueAtTime(0.18, now);
            droneOsc1.connect(droneGain1);
            droneGain1.connect(audioCtx.destination);
            droneOsc1.start(now);

            subRootOsc = audioCtx.createOscillator();
            subRootGain = audioCtx.createGain();
            subRootOsc.type = 'sine';
            subRootOsc.frequency.setValueAtTime(noteToFreq("C2", refA4), now);
            subRootGain.gain.setValueAtTime(0.20, now);
            subRootOsc.connect(subRootGain);
            subRootGain.connect(audioCtx.destination);
            subRootOsc.start(now);
        }

        function updateDroneFreqs(t0, t1, targetSubRootNote, refA4) {
            let now = audioCtx.currentTime;
            if (droneOsc0) droneOsc0.frequency.setTargetAtTime(noteToFreq(t0, refA4), now, 0.25);
            if (droneOsc1) droneOsc1.frequency.setTargetAtTime(noteToFreq(t1, refA4), now, 0.25);
            if (subRootOsc) subRootOsc.frequency.setTargetAtTime(noteToFreq(targetSubRootNote, refA4), now, 0.15);
        }

//        function playTone(freq, duration, releaseTime = 2.5, volume = 0.35, oscType = 'sine') {
//            if (!audioCtx || audioCtx.state !== 'running') return;
//            let startT = audioCtx.currentTime + 0.05;
//
//            let osc1 = audioCtx.createOscillator();
//            let osc2 = audioCtx.createOscillator();
//            let gain = audioCtx.createGain();
//
//            osc1.type = oscType;
//            osc1.frequency.setValueAtTime(freq, startT);
//            
//            osc2.type = 'sine';
//            osc2.frequency.setValueAtTime(freq * 2.0, startT);
//
//            gain.gain.setValueAtTime(volume * 0.5, startT);
//            let totalTime = startT + releaseTime;
//            gain.gain.exponentialRampToValueAtTime(0.0001, totalTime);
//
//            osc1.connect(gain);
//            osc2.connect(gain);
//            gain.connect(audioCtx.destination);
//
//            osc1.start(startT);
//            osc2.start(startT);
//            osc1.stop(totalTime);
//            osc2.stop(totalTime);
//        }
function playTone(freq, duration, releaseTime = 2.5, volume = 0.35, oscType = 'sine') {
    if (!audioCtx || audioCtx.state !== 'running') return;

    // Ensure startT is never in the past relative to the current audio clock
    let now = audioCtx.currentTime;
    let startT = now + 0.01;

    let osc1 = audioCtx.createOscillator();
    let osc2 = audioCtx.createOscillator();
    let gain = audioCtx.createGain();

    osc1.type = oscType;
    osc1.frequency.setValueAtTime(freq, startT);

    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(freq * 2.0, startT);

    gain.gain.setValueAtTime(volume * 0.5, startT);
    let totalTime = startT + releaseTime;

    // Prevent exponential ramp from starting below/at zero or in the past
    gain.gain.exponentialRampToValueAtTime(0.0001, totalTime);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(audioCtx.destination);

    osc1.start(startT);
    osc2.start(startT);
    osc1.stop(totalTime);
    osc2.stop(totalTime);
}

        function setupMediaSession() {
            if ('mediaSession' in navigator) {
                navigator.mediaSession.metadata = new MediaMetadata({
                    title: "Polytonal CRT Clock",
                    artist: "Generative Audio Engine",
                    album: "CRT Modal Ambient"
                });
                navigator.mediaSession.setActionHandler('play', () => {
                    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
                });
                navigator.mediaSession.setActionHandler('pause', () => {});
            }
        }

        document.getElementById('start-btn').addEventListener('click', () => {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }

            const silentAudio = document.getElementById('silent-keepalive');
            silentAudio.play().then(() => {
                setupMediaSession();
            }).catch(e => console.log("Silent keepalive setup:", e));

            document.getElementById('start-btn').style.display = 'none';
            document.getElementById('status').innerText = 'Syncing with Server...';

            initDrones(432.0);

            let wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            let wsUrl = wsProtocol + '//' + window.location.hostname + ':65432';
            ws = new WebSocket(wsUrl);

            ws.onmessage = (event) => {
                let data = JSON.parse(event.data);
                
                document.getElementById('lbl-tick').innerText = data.tick;
                document.getElementById('lbl-sec').innerText = data.minute_tick;
                document.getElementById('lbl-key').innerText = data.key;
                document.getElementById('lbl-mode').innerText = data.mode;
                document.getElementById('lbl-scale-solf').innerText = data.scale_solfege;
                document.getElementById('lbl-chord').innerText = JSON.stringify(data.chord);
                document.getElementById('lbl-chord-solf').innerText = JSON.stringify(data.chord_solfege);
                document.getElementById('lbl-sub').innerText = data.sub_root;
                document.getElementById('lbl-drone0').innerText = data.drone_tonic_0;
                document.getElementById('lbl-drone1').innerText = data.drone_tonic_1;

                document.getElementById('lbl-outer-key').innerText = data.outer_key;
                document.getElementById('lbl-outer-mode').innerText = data.outer_mode;
                document.getElementById('lbl-outer-chord').innerText = JSON.stringify(data.outer_chord);
                document.getElementById('lbl-outer-solf').innerText = JSON.stringify(data.outer_solfege);

                document.getElementById('lbl-dials').innerText = JSON.stringify(data.positions);
                document.getElementById('lbl-euc').innerText = 
                    data.v4_info + ' Step ' + data.v4_step + (data.v4_trig ? ' [HIT]' : ' [REST]');
                document.getElementById('lbl-outer-euc').innerText = 
                    (data.v4_trig_outer ? '[OUTER HIT]' : '[OUTER REST]');
                document.getElementById('status').innerText = 'CONNECTED & SYNCHRONIZED';

                updateDroneFreqs(data.drone_tonic_0, data.drone_tonic_1, data.sub_root, data.a4_freq);

                // Lower/Inner Voices
                data.inner_triad_trigs.forEach((trig, idx) => {
                    if (trig) {
                        let innerFreq = noteToFreq(data.chord[idx], data.a4_freq);
                        playTone(innerFreq, 1.0, 3.5, 0.35, 'sine');
                    }
                });

                // Upper/Outer Voices
                data.outer_triad_trigs.forEach((trig, idx) => {
                    if (trig) {
                        let outerFreq = noteToFreq(data.outer_chord[idx], data.a4_freq);
                        playTone(outerFreq, 1.0, 3.0, 0.15, 'triangle');
                    }
                });

                // Inner Euclidean Trigger
                if (data.v4_trig) {
                    let freq = noteToFreq(data.chord[3], data.a4_freq);
                    playTone(freq, 0.5, 2.0, 0.25, 'sine');
                }

                // Outer Euclidean Trigger
                if (data.v4_trig_outer) {
                    let outerFreq = noteToFreq(data.outer_chord[3], data.a4_freq);
                    playTone(outerFreq, 0.5, 2.0, 0.15, 'triangle');
                }
            };
        });

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible' && audioCtx) {
                if (audioCtx.state === 'suspended') {
                    audioCtx.resume();
                }
            }
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
    
    inner_prog = build_parallel_chromatic_progression(ALL_FAMILIES, octave_offset=0)
    outer_prog = build_parallel_chromatic_progression(ALL_FAMILIES, octave_offset=2)
    
    clock = MasterClock(inner_prog, outer_prog)

    threading.Thread(target=start_http_server, daemon=True).start()

    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        print(f"[WS SERVER] Broadcasting time sync on ws://0.0.0.0:{WS_PORT}")
        await clock.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer terminated.")
