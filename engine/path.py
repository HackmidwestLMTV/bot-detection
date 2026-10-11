"""Exact Python counterpart of Person 1's mulberry32 comet path."""

import math

MASK = 0xFFFFFFFF
DURATION_MS = 3000


def mulberry32(seed):
    state = int(seed) & MASK

    def random():
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK
        value = ((state ^ (state >> 15)) * (state | 1)) & MASK
        value = ((value + (((value ^ (value >> 7)) * (value | 61)) & MASK)) & MASK) ^ value
        return ((value ^ (value >> 14)) & MASK) / 4294967296

    return random


def make_path(seed: int):
    """Return pos(t_ms) -> (x, y), in 600 x 400 logical pixels."""
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
