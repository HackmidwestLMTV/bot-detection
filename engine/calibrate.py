"""Local human-evidence audit; never overwrites the shared variant."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from engine.forger import forge_trail
from engine.path import DEFAULT_PATH_VERSION, PATH_VERSIONS
from engine.scorer import FEATURES, features, normalize_samples, score_features, validate_variant
from contracts.presentation import LEGACY_PRESENTATION, PRESENTATION_VERSION, PRESENTATION_DURATIONS

ROOT = Path(__file__).resolve().parents[1]
DEVICES = ("mouse", "trackpad", "touch")


def load_traces(folder, path_version="v1", presentation_version=PRESENTATION_VERSION):
    """Read a path/display cohort; None explicitly requests all for transplantation."""
    if path_version is not None and path_version not in PATH_VERSIONS:
        raise ValueError("unsupported path_version")
    traces, rejected, seen = [], [], set()
    for path in sorted(Path(folder).glob("*.json")):
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
            version = trace.get("path_version", "v1")
            if version not in PATH_VERSIONS:
                raise ValueError("unsupported path_version")
            if path_version is not None and version != path_version:
                continue
            presentation = trace.get("presentation_version", LEGACY_PRESENTATION)
            if presentation not in PRESENTATION_DURATIONS:
                raise ValueError("unsupported presentation_version")
            if presentation_version is not None and presentation != presentation_version:
                continue
            if (trace.get("cohort") != "human_test" or trace.get("tester", {}).get("consent") is not True
                    or trace.get("round_id") is not None or trace.get("device") not in DEVICES):
                raise ValueError("requires consented human_test evidence with a supported device")
            seed = trace["seed"]
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
                raise ValueError("invalid seed")
            samples = normalize_samples(trace["samples"])
            if samples[-1, 0] > PRESENTATION_DURATIONS[presentation]:
                raise ValueError("trace exceeds challenge duration")
            fingerprint = hashlib.sha256(json.dumps([version, presentation, seed, samples.tolist()]).encode()).hexdigest()
            if fingerprint in seen:
                raise ValueError("duplicate recording")
            values = features(samples, seed, version)
            seen.add(fingerprint)
            traces.append({"file": path.name, "trace": trace, "features": values})
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            rejected.append({"file": path.name, "reason": str(exc)})
    return traces, rejected


def calibration_report(folder, baseline, *, path_version=None, presentation_version=PRESENTATION_VERSION):
    baseline = deepcopy(baseline)
    if path_version is not None:
        baseline["path_version"] = path_version
    validate_variant(baseline)
    version = baseline.get("path_version", "v1")
    rows, rejected = load_traces(folder, version, presentation_version)
    baseline["presentation_version"] = presentation_version
    counts = {device: sum(row["trace"]["device"] == device for row in rows) for device in DEVICES}
    reasons = []
    if len(rows) < 10:
        reasons.append(f"need at least 10 unique consented recordings; found {len(rows)}")
    missing = [device for device, count in counts.items() if not count]
    if missing:
        reasons.append("missing devices: " + ", ".join(missing))
    if rejected:
        reasons.append("resolve rejected recording files before adopting bands")
    candidate = deepcopy(baseline)
    candidate.update(id="calibration_candidate", parent=baseline["id"], author="operator",
                     reason="5th–95th percentiles of consented team traces, padded 10% per side; provisional")
    degenerate = []
    if rows:
        for feature in FEATURES:
            low, high = np.percentile([row["features"][feature] for row in rows], [5, 95])
            pad = .1 * (high - low)
            band = [round(float(low - pad), 3), round(float(high + pad), 3)]
            if band[0] >= band[1]:
                degenerate.append(feature)
            else:
                candidate["features"][feature] = band
    if degenerate:
        reasons.append("insufficient variation; retained baseline bands for: " + ", ".join(degenerate))
    groups = {device: {"total": counts[device], "baseline_rejected": 0, "candidate_rejected": 0} for device in DEVICES}
    failures = []
    for row in rows:
        group = groups[row["trace"]["device"]]
        group["baseline_rejected"] += not score_features(row["features"], baseline)["pass"]
        result = score_features(row["features"], candidate)
        group["candidate_rejected"] += not result["pass"]
        if not result["pass"]:
            failures.append({"file": row["file"], "device": row["trace"]["device"],
                             "failed": [k for k, value in result["features"].items() if value["enabled"] and not value["ok"]]})
    if failures:
        reasons.append("candidate still rejects recorded humans; inspect per-device failures")
    seeds = sorted({row["trace"]["seed"] for row in rows})
    naive_passed = sum(score_features(features(forge_trail(seed, path_version=version,
                                     duration_ms=PRESENTATION_DURATIONS[presentation_version]), seed, version),
                                     candidate)["pass"] for seed in seeds)
    if naive_passed:
        reasons.append(f"perfect-target baseline passes on {naive_passed} of {len(seeds)} recorded seeds")
    return {"ready_for_review": not reasons, "reasons": reasons, "recordings": len(rows), "path_version": version,
            "presentation_version": presentation_version,
            "devices": groups, "rejected_files": rejected, "human_failures": failures,
            "naive_forgeries": {"total": len(seeds), "passed": naive_passed},
            "candidate": candidate if rows else None,
            "note": "Only recordings matching path_version and presentation_version are included. In-sample team calibration only; not held-out accuracy or proof of humanity."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path, default=ROOT / "contracts/fixtures/human_traces")
    parser.add_argument("--variant", type=Path, default=ROOT / "contracts/fixtures/variant_v1.json")
    parser.add_argument("--path-version", choices=PATH_VERSIONS, default=DEFAULT_PATH_VERSION, help="Select a separate path cohort (default: roaming_v3)")
    parser.add_argument("--presentation-version", choices=tuple(PRESENTATION_DURATIONS),
                        default=PRESENTATION_VERSION, help="Select a display cohort; legacy is audit-only")
    args = parser.parse_args(argv)
    report = calibration_report(args.traces, json.loads(args.variant.read_text(encoding="utf-8")),
                                path_version=args.path_version, presentation_version=args.presentation_version)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["ready_for_review"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
