"""Exact Python counterpart of Person 1's mulberry32 comet path."""

import math

MASK = 0xFFFFFFFF
DURATION_MS = 3000
PATH_VERSIONS = ("v1", "smooth_v2")


def mulberry32(seed):
    state = int(seed) & MASK

    def random():
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK
        value = ((state ^ (state >> 15)) * (state | 1)) & MASK
        value = ((value + (((value ^ (value >> 7)) * (value | 61)) & MASK)) & MASK) ^ value
        return ((value ^ (value >> 14)) & MASK) / 4294967296

    return random


def make_path(seed: int, path_version="v1"):
    """Return a versioned path; omitted version preserves recorded v1 evidence."""
    if path_version not in PATH_VERSIONS:
        raise ValueError("unsupported path_version")
    if path_version == "smooth_v2":
        return _smooth_path(seed)
    random = mulberry32(seed)
    components = []
    for amplitudes in ((130, 50, 20), (80, 35, 15)):
        axis = []
        for base in amplitudes:
            frequency = 0.10 + random() * 0.25
            phase = random() * 2 * math.pi
            amplitude = base * (0.6 + 0.4 * random())
            axis.append((frequency, phase, amplitude))
        components.append(axis)
    kicks = []
    for base_time in (900, 1900):
        time = base_time + random() * 500
        angle = random() * 2 * math.pi
        magnitude = 60 + random() * 30
        kicks.append((time, magnitude * math.cos(angle), magnitude * math.sin(angle)))

    def pos(t_ms: float):
        t = t_ms / 1000
        xy = [300.0, 200.0]
        for index, axis in enumerate(components):
            for frequency, phase, amplitude in axis:
                xy[index] += amplitude * math.sin(2 * math.pi * frequency * t + phase)
        for time, dx, dy in kicks:
            u = min(max((t_ms - time) / 120, 0), 1)
            smooth = u * u * (3 - 2 * u)
            xy[0] += dx * smooth
            xy[1] += dy * smooth
        return min(max(xy[0], 30), 570), min(max(xy[1], 30), 370)

    return pos


def _smooth_path(seed):
    """Continuous sinusoids: x=145..455, y=110..290, speed <158 px/s.

    Bounds follow from summed amplitudes (155, 90). The derivative bound is
    2*pi*.14*hypot(155,90), with no clipping, impulses, or piecewise transitions.
    """
    random = mulberry32(seed)
    components = []
    for amplitudes in ((120, 35), (70, 20)):
        axis = []
        for base in amplitudes:
            frequency = .08 + .06 * random()
            phase = random() * 2 * math.pi
            amplitude = base * (.8 + .2 * random())
            axis.append((frequency, phase, amplitude))
        components.append(axis)

    def pos(t_ms):
        t = t_ms / 1000
        return tuple(center + sum(amplitude * math.sin(2 * math.pi * frequency * t + phase)
                                  for frequency, phase, amplitude in axis)
                     for center, axis in zip((300, 200), components))

    return pos
