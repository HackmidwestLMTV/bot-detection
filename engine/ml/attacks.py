"""Labeled synthetic regressions, including the observed open-loop cursor-wave family."""
import argparse
import time
from pathlib import Path

import numpy as np

from contracts.presentation import PRESENTATION_VERSION
from contracts.research import COLLECTOR_VERSION, RETENTION_S, SCHEMA, sign
from engine.path import make_path
from .collect import write_private

FAMILIES = ("open_loop_wave", "perfect_follow", "lagged_noise", "feedback_control")


def samples(seed, family):
    rng = np.random.default_rng(seed)
    t = np.arange(0, 3001, 16, dtype=float)
    path = make_path(seed, "smooth_v2")
    target = np.asarray([path(float(x)) for x in t])
    if family == "open_loop_wave":
        # Same attack class as the successful drag experiment, not a recovered recording.
        phase = rng.uniform(-1, 1)
        xy = target[0] + np.column_stack([75 * np.sin(t / 530 + phase), 43 * np.sin(t / 310 + phase)])
    elif family == "perfect_follow":
        xy = target
    elif family == "lagged_noise":
        lag = rng.uniform(120, 350)
        xy = np.asarray([path(float(max(0, x - lag))) for x in t]) + rng.normal(0, 3, target.shape)
    elif family == "feedback_control":
        xy = np.zeros_like(target)
        xy[0] = target[0]
        gain = rng.uniform(.1, .3)
        for i in range(1, len(t)):
            xy[i] = xy[i - 1] + gain * (target[max(0, i - 8)] - xy[i - 1]) + rng.normal(0, 1.2, 2)
    else:
        raise ValueError("unknown attack family")
    return np.column_stack([t, np.clip(xy, [0, 0], [600, 400])]).round(3).tolist()


def generate(directory, key, *, groups=50, now=None):
    if not 10 <= groups <= 10000:
        raise ValueError("groups must be 10-10000")
    now = time.time() if now is None else now
    count = 0
    for seed in range(10000, 10000 + groups):
        # All strategies using the same source/seed stay in the same partition.
        group = f"synthetic_{seed}"
        for family in FAMILIES:
            rid = f"attack_{seed}_{family}"
            record = {"schema": SCHEMA, "record_id": rid, "group_id": group, "session_group": group,
                      "label": "bot", "provenance": "synthetic_generator_v1", "attack_family": family,
                      "collected_at": now, "expires_at": now + RETENTION_S,
                      "device": "mouse", "collector_version": COLLECTOR_VERSION,
                      "seed": seed, "path_version": "smooth_v2", "presentation_version": PRESENTATION_VERSION,
                      "samples": samples(seed, family)}
            write_private(Path(directory) / (rid + ".json"), sign(record, key))
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--groups", type=int, default=50)
    args = parser.parse_args()
    print("Synthetic recordings:", generate(args.directory, Path(args.key_file).read_text().strip(), groups=args.groups))


if __name__ == "__main__":
    main()
