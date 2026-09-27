"""E443xB UND uses separate, big-endian, unsigned offset-14-bit I and Q files."""

import math
import re
import struct
import wave
from pathlib import Path

MAX_SAMPLES = 131_072


def waveform_name(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", name):
        raise ValueError("Waveform name must be 1–32 ASCII letters, digits, or underscores")
    return name


def finite_range(name, value, low, high):
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def voice_iq(path: str, depth: float):
    finite_range("AM depth", depth, 0.001, 0.99)
    with wave.open(str(Path(path).expanduser().resolve(strict=True)), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("Use an uncompressed mono, 16-bit PCM WAV")
        count, rate = wav.getnframes(), wav.getframerate()
        if not 16 <= count <= MAX_SAMPLES:
            raise ValueError(f"WAV must contain 16–{MAX_SAMPLES} samples")
        finite_range("Audio sample rate", rate, 8000, 48000)
        raw = wav.readframes(count)
    if len(raw) != count * 2:
        raise ValueError("Truncated WAV")
    samples = list(struct.unpack(f"<{count}h", raw))
    if len(samples) % 2:
        samples.append(0)
    peak = max(abs(s) for s in samples)
    if not peak:
        raise ValueError("WAV is silent")
    carrier = 0.9 / (1 + depth)
    i = [round(8192 + 8191 * carrier * (1 + depth * s / peak)) for s in samples]
    q = [8192] * len(i)
    return (struct.pack(f">{len(i)}H", *i), struct.pack(f">{len(q)}H", *q),
            {"sample_rate_hz": rate, "samples": len(i), "duration_s": len(i) / rate,
             "depth_fraction": depth, "carrier_scale": carrier})


def sample_data(data):
    """Mask marker/sequencer bits, which can legitimately change during playback."""
    if len(data) % 2:
        raise ValueError("Odd byte count in 16-bit waveform")
    return [v[0] & 0x3fff for v in struct.iter_unpack(">H", data)]
