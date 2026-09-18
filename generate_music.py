"""
On Est Tous d'Accord - Musique de fond générée par code
==========================================================
Fabrique une petite musique instrumentale (pas de voix) directement avec du
son de synthèse : un tapis d'accords doux + une petite mélodie qui rebondit
par-dessus + un souffle de percussion légère. Comme c'est entièrement
généré par le programme (aucun échantillon existant utilisé), il n'y a
aucun risque de droit d'auteur, et ça ne demande aucune action à Tom.

Utilisation :
    from generate_music import generate_background_music
    generate_background_music(duration_sec=10, output_path="musique.wav", seed=3)
"""

import numpy as np
from scipy.io import wavfile

SR = 44100  # fréquence d'échantillonnage standard

# Quelques progressions d'accords simples et "feel good" (en fréquences, Hz)
# basées sur des accords de piano/synthé doux (do majeur et la mineur, très
# consensuel/pop). On tire au sort une progression selon le "seed" du jour
# pour varier un peu d'un post à l'autre.
NOTE_FREQ = {
    "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.00, "A3": 220.00, "B3": 246.94,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.00, "A4": 440.00, "B4": 493.88,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99,
}

CHORDS = {
    "C":  ["C3", "E3", "G3"],
    "Am": ["A3", "C4", "E4"],
    "F":  ["F3", "A3", "C4"],
    "G":  ["G3", "B3", "D4"],
    "Dm": ["D3", "F3", "A3"],
}

PROGRESSIONS = [
    ["C", "G", "Am", "F"],
    ["Am", "F", "C", "G"],
    ["F", "C", "G", "Am"],
    ["C", "Am", "F", "G"],
]

MELODY_NOTES = ["C5", "D5", "E5", "G4", "A4", "E5", "D5", "G5"]


def _envelope(n_samples, attack=0.02, release=0.3):
    env = np.ones(n_samples)
    a = int(SR * attack)
    r = int(SR * release)
    if a > 0:
        env[:a] = np.linspace(0, 1, a)
    if r > 0 and r < n_samples:
        env[-r:] *= np.linspace(1, 0, r)
    return env


def _tone(freq, duration, wave="sine", volume=1.0):
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    if wave == "sine":
        s = np.sin(2 * np.pi * freq * t)
    elif wave == "triangle":
        s = 2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1
    else:
        s = np.sin(2 * np.pi * freq * t)
    return s * volume * _envelope(len(s))


def _chord(note_names, duration, volume=0.18):
    out = np.zeros(int(SR * duration))
    for n in note_names:
        out += _tone(NOTE_FREQ[n], duration, wave="triangle", volume=volume)
    return out


def _hihat(duration=0.06, volume=0.05):
    n = int(SR * duration)
    noise = np.random.uniform(-1, 1, n)
    return noise * volume * _envelope(n, attack=0.001, release=duration * 0.8)


def generate_background_music(duration_sec, output_path, seed=0, bpm=92):
    rng = np.random.default_rng(seed)
    progression = PROGRESSIONS[seed % len(PROGRESSIONS)]

    beat_dur = 60.0 / bpm
    bar_dur = beat_dur * 4
    n_bars = max(1, int(np.ceil(duration_sec / bar_dur)))

    total_samples = int(SR * (n_bars * bar_dur + 1))
    mix = np.zeros(total_samples)

    for bar_i in range(n_bars):
        chord_name = progression[bar_i % len(progression)]
        bar_start = int(SR * bar_i * bar_dur)

        # tapis d'accord tenu sur toute la mesure
        chord_wave = _chord(CHORDS[chord_name], bar_dur, volume=0.16)
        mix[bar_start:bar_start + len(chord_wave)] += chord_wave

        # petite mélodie qui rebondit, une note par temps (4 notes/mesure)
        for beat_i in range(4):
            note = MELODY_NOTES[rng.integers(0, len(MELODY_NOTES))]
            note_start = bar_start + int(SR * beat_i * beat_dur)
            note_wave = _tone(NOTE_FREQ[note], beat_dur * 0.85, wave="sine", volume=0.10)
            end = note_start + len(note_wave)
            if end <= total_samples:
                mix[note_start:end] += note_wave

            # léger charleston sur les temps 2 et 4 (rythme discret)
            if beat_i in (1, 3):
                hh = _hihat()
                end_hh = note_start + len(hh)
                if end_hh <= total_samples:
                    mix[note_start:end_hh] += hh

    # coupe à la durée demandée + fondu de sortie doux
    n_final = int(SR * duration_sec)
    mix = mix[:n_final]
    fade_out = int(SR * min(1.0, duration_sec * 0.15))
    if fade_out > 0:
        mix[-fade_out:] *= np.linspace(1, 0, fade_out)

    # normalisation pour éviter toute saturation
    peak = np.max(np.abs(mix)) or 1.0
    mix = (mix / peak) * 0.85

    audio_i16 = np.int16(mix * 32767)
    wavfile.write(output_path, SR, audio_i16)
    return output_path


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_test.wav")
    generate_background_music(duration_sec=10, output_path=out, seed=1)
    print("Musique générée :", out)
