import math
import pytest
from juniper_chimes.chimes import (
    EDOEngine,
    build_descending_circle_of_fifths_progression,
    compute_tone_rhythms,
    compute_tone_rhythms_rh,
    edo24_to_freq_432,
    generate_diatonic_7th_chords_24,
    generate_drones_for_chord,
    generate_parallel_family_block_24,
    get_fixed_do_solfege_24,
    get_parallel_mode_pitches_24,
    identify_7th_chord_24,
)


# ==============================================================================
# 24-EDO MUSIC THEORY & ENGINE TESTS
# ==============================================================================

def test_edo24_to_freq_432():
    # Step 138 is A4 = 432.0 Hz
    assert math.isclose(edo24_to_freq_432(138), 432.0, rel_tol=1e-6)
    # Step 162 is A5 (24 steps / 1 octave higher) = 864.0 Hz
    assert math.isclose(edo24_to_freq_432(162), 864.0, rel_tol=1e-6)
    # Step 114 is A3 (24 steps / 1 octave lower) = 216.0 Hz
    assert math.isclose(edo24_to_freq_432(114), 216.0, rel_tol=1e-6)


def test_get_fixed_do_solfege_24():
    assert get_fixed_do_solfege_24(0, drone_pc=0) == "Do"
    assert get_fixed_do_solfege_24(1, drone_pc=0) == "Do+"
    assert get_fixed_do_solfege_24(2, drone_pc=0) == "Ra"
    assert get_fixed_do_solfege_24(23, drone_pc=0) == "Ti+"
    # Key-relative drone shift (drone_pc = 2)
    assert get_fixed_do_solfege_24(2, drone_pc=2) == "Do"


def test_identify_7th_chord_24():
    # C Major 7th (Root 120 / C4, intervals: +8, +14, +22)
    c_maj7_steps = [120, 128, 134, 142]
    assert identify_7th_chord_24(c_maj7_steps) == "C Maj7"

    # C Minor 7th (Root 120 / C4, intervals: +6, +14, +20)
    c_m7_steps = [120, 126, 134, 140]
    assert identify_7th_chord_24(c_m7_steps) == "C m7"

    # Unmapped interval fallback
    custom_steps = [120, 123, 130, 137]
    assert identify_7th_chord_24(custom_steps) == "C 7th Custom (24-EDO)"


def test_get_parallel_mode_pitches_24():
    # C Ionian (Mode 1 of Major family)
    pitches = get_parallel_mode_pitches_24("Major", mode_degree=1, tonic_step=120)
    assert len(pitches) == 7
    assert pitches == [120, 124, 128, 130, 134, 138, 142]


def test_generate_diatonic_7th_chords_24():
    scale_pitches = [120, 124, 128, 130, 134, 138, 142]
    meta = {"key": "C Major"}
    chords = generate_diatonic_7th_chords_24(
        scale_pitches, meta, tonic_step=120, perceived_drone_pc=0
    )

    # Standard progression contains 7 diatonic chords
    assert len(chords) == 7
    first_chord = chords[0]
    assert first_chord["duration"] == 60
    assert len(first_chord["steps"]) == 4
    assert len(first_chord["notes"]) == 4
    assert first_chord["chord_name"].startswith("C")


def test_generate_parallel_family_block_24():
    # Major family has 7 modes; each mode yields 7 diatonic chords = 49 total chords
    block = generate_parallel_family_block_24("Major", tonic_step=120, perceived_drone_pc=0)
    assert len(block) == 49


def test_build_descending_circle_of_fifths_progression():
    families = ["Major", "Harmonic Minor"]
    progression = build_descending_circle_of_fifths_progression(families)
    # Total passes = 84, each family block has 49 chords
    assert len(progression) == 84 * 49


def test_generate_drones_for_chord():
    chord_data = {
        "steps": [120, 128, 134, 142],
        "meta": {"tonic_step": 120}
    }
    drones = generate_drones_for_chord(chord_data, perceived_drone_pc=0)

    assert drones["key_drone_low"]["note"] == "C0"
    assert drones["key_drone_high"]["note"] == "C1"
    assert drones["chord_drone"]["note"] == "C2"
    assert math.isclose(drones["key_drone_low"]["frequency"], edo24_to_freq_432(24), rel_tol=1e-6)


def test_compute_tone_rhythms():
    # Tick 0: All ticks modulo 3, 4, 5 are active
    lh_0 = compute_tone_rhythms(0, is_7th_allowed=True)
    assert lh_0[0]["active"] is True   # Root (tick % 3 == 0)
    assert lh_0[1]["active"] is True   # 3rd  (tick % 4 == 0)
    assert lh_0[2]["active"] is True   # 5th  (tick % 5 == 0)
    assert lh_0[3]["active"] is True   # 7th

    # Tick 1: Root, 3rd, 5th inactive
    lh_1 = compute_tone_rhythms(1, is_7th_allowed=False)
    assert lh_1[0]["active"] is False
    assert lh_1[3]["active"] is False

    # Check phase-shifted RH rhythms
    rh_0 = compute_tone_rhythms_rh(0, is_7th_allowed=True)
    assert rh_0[0]["active"] is True   # (0 + 30) % 3 == 0


# ==============================================================================
# PARAMETERIZED EDO ENGINE TESTS
# ==============================================================================

class TestEDOEngine:
    def test_init_and_properties_31_edo(self):
        engine = EDOEngine(edo_steps=31, a4_freq=432.0)
        assert engine.edo_steps == 31
        assert engine.a4_freq == 432.0
        assert len(engine.major_scale) == 7
        assert engine.fifth_step == 18

    def test_note_naming_12_edo(self):
        engine = EDOEngine(edo_steps=12)
        assert engine.get_note_name(60) == "C4"
        assert engine.get_note_name(69) == "A4"

    def test_note_naming_24_edo(self):
        engine = EDOEngine(edo_steps=24)
        assert engine.get_note_name(120) == "C4"

    def test_frequency_conversion(self):
        engine = EDOEngine(edo_steps=31, a4_freq=432.0)
        assert math.isclose(engine.edo_to_freq(engine.a4_step), 432.0, rel_tol=1e-6)
        assert math.isclose(engine.edo_to_freq(engine.a4_step + 31), 864.0, rel_tol=1e-6)

    def test_identify_7th_chord_31_edo(self):
        engine = EDOEngine(edo_steps=31)
        root = 5 * 31  # C5 step base
        maj7_steps = [root, root + engine.M3, root + engine.P5, root + engine.M7]
        chord_name = engine.identify_7th_chord(maj7_steps)
        assert "Maj7" in chord_name

    def test_generate_diatonic_chords_31_edo(self):
        engine = EDOEngine(edo_steps=31)
        pitches = engine.get_parallel_mode_pitches("Major", mode_degree=1, tonic_step=155)
        chords = engine.generate_diatonic_7th_chords(
            pitches, meta={"key": "C Major"}, tonic_step=155, perceived_drone_pc=0
        )
        assert len(chords) == 7
        assert len(chords[0]["steps"]) == 4
