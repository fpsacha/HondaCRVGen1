r"""
The CR-V's own sounds, synthesised (no recordings): python scripts/features/_polish_sounds.py [out_dir]

Writes 44.1 kHz mono Ogg Vorbis files (ffmpeg's libvorbis; ffmpeg must be on PATH) into
mod/Contents/mods/HondaCRVGen1/42/media/sound by default. Deterministic (fixed seeds).

  CRVGen1_EngineLow.ogg   B20B layer at 1800 rpm (pitched 0.4-1.9x by the Lua: idle to ~3400 rpm)
  CRVGen1_EngineHigh.ogg  B20B layer at 4800 rpm with the light whine (pitched 0.55-1.5x: ~2600-7200 rpm)
  CRVGen1_Horn.ogg        90s Honda dual-tone horn, a seamless sustain loop (416 + 520 Hz)
  CRVGen1_Door*.ogg       door open / close, central locking lock / unlock (one-shots)

The engine loops are seamless because every component sits on the loop's frequency grid (2 s loop:
every frequency a multiple of 0.5 Hz) and the noise is made in the frequency domain on that grid.
What a 2.0 l DOHC inline four sounds like, as built here: the firing order (2 per crank turn) and its
harmonics carry it, the half orders stay tiny (smooth: balanced, no V-engine burble), the exhaust and
intake add pulse-modulated band noise, and the high layer carries a thin whine (cam drive / alternator
orders 24 and 36) that the low layer barely has.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "sound")


def _grid_noise(n, lo, hi, rng, tilt=0.0):
    """Periodic band noise of n samples: random phases on the FFT bins between lo and hi Hz (the loop
    length's own grid, so it wraps without a seam), spectrum tilted by f^-tilt."""
    f = np.fft.rfftfreq(n, 1.0 / SR)
    amp = ((f >= lo) & (f <= hi)).astype(float)
    amp *= np.where(f > 0, (np.maximum(f, 1.0) / max(lo, 1.0)) ** -tilt, 0.0)
    # soft band edges
    amp *= np.clip((f - lo) / (0.15 * lo + 1), 0, 1) * np.clip((hi - f) / (0.15 * hi + 1), 0, 1)
    spec = amp * np.exp(1j * rng.uniform(0, 2 * np.pi, len(f)))
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-12)


def _lowpass_periodic(x, fc):
    """A circular low pass (FFT): keeps the loop seamless."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    h = 1.0 / np.sqrt(1.0 + (f / fc) ** 4)
    return np.fft.irfft(np.fft.rfft(x) * h, n)


def engine_loop(rpm, whine, seed, seconds=2.0):
    n = int(SR * seconds)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    fc = rpm / 60.0                                     # crank frequency
    assert abs(fc * seconds - round(fc * seconds)) < 1e-9, "crank frequency off the loop grid"
    x = np.zeros(n)
    # firing order 2 and harmonics: the body of an inline four
    for order, a in ((2, 1.0), (4, 0.55), (6, 0.32), (8, 0.20), (10, 0.12), (12, 0.08), (16, 0.04)):
        x += a * np.sin(2 * np.pi * fc * order * t + rng.uniform(0, 2 * np.pi))
    for order, a in ((0.5, 0.05), (1, 0.08), (1.5, 0.04), (3, 0.06), (5, 0.03)):   # small imbalance
        x += a * np.sin(2 * np.pi * fc * order * t + rng.uniform(0, 2 * np.pi))
    # combustion / exhaust pulses: band noise gated at the firing rate
    pulse = 0.5 + 0.5 * np.cos(2 * np.pi * fc * 2 * t)
    pulse = pulse ** 3
    exhaust = _grid_noise(n, 90, 900, rng, tilt=0.8) * (0.25 + 0.75 * pulse)
    intake = _grid_noise(n, 900, 4000, rng, tilt=1.2) * (0.6 + 0.4 * pulse)
    x = x / np.abs(x).max()
    x = x * 0.75 + exhaust * 0.35 + intake * (0.06 + 0.06 * whine)
    # the whine: thin tones high up, steady (a belt and gear sound, not a combustion one)
    for order, a in ((24, 0.10), (36, 0.05), (48, 0.02)):
        f = fc * order
        x += whine * a * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) * (1.0 + 0.15 * np.sin(2 * np.pi * fc * t))
    x = _lowpass_periodic(x, 2600 if whine < 0.5 else 5200)
    x = np.tanh(1.3 * x / np.abs(x).max()) / np.tanh(1.3)       # gentle saturation, a fuller tone
    return x * 0.7


def horn_loop(seconds=1.0):
    """A 90s car horn: two tones about a major third apart (416 / 520 Hz), each a small disc diaphragm.
    The spectrum falls off fast (k^-1.6 over 8 harmonics), no clipping, a soft top end (about 3 kHz) and
    a short trumpet resonance near 1.6 kHz. The first version (a buzzing saw clipped with tanh over 21
    harmonics) sounded harsh in game (2026-10-15). A whole number of cycles per second, so it loops."""
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for f0, a0 in ((416.0, 1.0), (520.0, 0.8)):
        assert abs(f0 * seconds - round(f0 * seconds)) < 1e-9
        for k in range(1, 9):
            f = f0 * k
            form = 1.0 + 0.9 * np.exp(-((f - 1600) / 450) ** 2)
            x += a0 * form * k ** -1.6 * np.sin(2 * np.pi * f * t)
    x = _lowpass_periodic(x, 3000)
    return 0.75 * x / np.abs(x).max()


def _env(n, attack, decay):
    t = np.arange(n) / SR
    return np.clip(t / max(attack, 1e-4), 0, 1) * np.exp(-t / decay)


def _burst(n, lo, hi, rng, decay, at=0.0):
    out = np.zeros(n)
    i = int(at * SR)
    m = n - i
    out[i:] = _grid_noise(m, lo, hi, rng) * _env(m, 0.0005, decay)
    return out


def _thump(n, freqs, decay, rng, at=0.0):
    out = np.zeros(n)
    i = int(at * SR)
    t = np.arange(n - i) / SR
    for f, a in freqs:
        out[i:] += a * np.sin(2 * np.pi * f * t + rng.uniform(0, 1)) * np.exp(-t / (decay * (100.0 / f) ** 0.3))
    return out


def door_close():
    rng = np.random.default_rng(31)
    n = int(SR * 0.7)
    x = _burst(n, 2500, 7000, rng, 0.006) * 0.5                                   # latch striker
    x += _thump(n, ((62, 1.0), (98, 0.8), (145, 0.5), (230, 0.3), (410, 0.15)), 0.09, rng, at=0.004)
    x += _burst(n, 300, 2000, rng, 0.03, at=0.004) * 0.35                         # the panel's slap
    x += _burst(n, 1500, 5000, rng, 0.012, at=0.05) * 0.12                        # trim rattle
    x = _lowpass_periodic(x, 5000)
    return 0.9 * x / np.abs(x).max()


def door_open():
    rng = np.random.default_rng(32)
    n = int(SR * 0.6)
    x = _burst(n, 1800, 6000, rng, 0.008) * 0.6                                   # handle and latch release
    x += _thump(n, ((180, 0.4), (320, 0.3)), 0.03, rng, at=0.002)
    seal = _grid_noise(n, 200, 1500, rng, tilt=0.5)
    t = np.arange(n) / SR
    x += seal * np.exp(-((t - 0.09) / 0.05) ** 2) * 0.25                          # the seal letting go
    x += _burst(n, 600, 2400, rng, 0.05, at=0.16) * 0.08                          # check strap
    return 0.8 * x / np.abs(x).max()


def door_lock(unlock=False):
    rng = np.random.default_rng(33 if not unlock else 34)
    n = int(SR * 0.35)
    first, second = (0.0, 0.055) if not unlock else (0.0, 0.04)
    x = _thump(n, ((240, 0.7), (520, 0.4), (900, 0.2)), 0.025, rng, at=first)
    x += _burst(n, 2000, 6000, rng, 0.004, at=first) * 0.4
    x += _thump(n, ((300, 0.5), (700, 0.3)), 0.02, rng, at=second) * (0.8 if not unlock else 0.6)
    x += _burst(n, 2500, 7000, rng, 0.003, at=second) * 0.3
    return 0.75 * x / np.abs(x).max()


def _write_ogg(x, path):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    ff = shutil.which("ffmpeg")
    if not ff:
        raise SystemExit("ffmpeg (with libvorbis) is needed on PATH")
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", tmp.name, "-c:a", "libvorbis", "-q:a", "6",
                        "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact", path],
                       capture_output=True, text=True)
    os.remove(tmp.name)
    if r.returncode:
        raise SystemExit("ffmpeg failed: %s" % r.stderr)


def build(out=OUT):
    os.makedirs(out, exist_ok=True)
    clips = {
        "CRVGen1_EngineLow.ogg": engine_loop(1800, 0.15, 1),
        "CRVGen1_EngineHigh.ogg": engine_loop(4800, 1.0, 2),
        "CRVGen1_Horn.ogg": horn_loop(),
        "CRVGen1_DoorOpen.ogg": door_open(),
        "CRVGen1_DoorClose.ogg": door_close(),
        "CRVGen1_DoorLock.ogg": door_lock(),
        "CRVGen1_DoorUnlock.ogg": door_lock(unlock=True),
    }
    for name, x in clips.items():
        _write_ogg(x, os.path.join(out, name))
        print("WROTE %s (%.2f s)" % (name, len(x) / SR))
    return clips


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else OUT)
