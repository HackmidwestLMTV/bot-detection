"""Strict input validation and stable participant/source-disjoint partitions."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from contracts.presentation import PRESENTATION_VERSION
from contracts.research import digest, verify
from engine.features_v2 import representation
from engine.path import DEFAULT_PATH_VERSION
from engine.scorer import score

BASELINE = json.loads((Path(__file__).parents[2] / "contracts/fixtures/variant_v1.json").read_text())


def load(directory, key, *, allow_test=False, now=None):
    now = time.time() if now is None else now
    records, values, excluded, evidence, seen_ids, seen_samples = [], [], [], [], set(), set()
    test_only = False
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise ValueError("no research envelopes; collect fresh enrolled recordings first")
    for path in paths:
        if path.stat().st_size > 1_000_000:
            raise ValueError("oversized recording: " + path.name)
        envelope = json.loads(path.read_bytes())
        r = verify(envelope, key, now=now, allow_test=allow_test)
        test_only = test_only or r["provenance"] == "test_fixture"
        if r.get("path_version") != DEFAULT_PATH_VERSION or r.get("presentation_version") != PRESENTATION_VERSION:
            raise ValueError("legacy or incompatible presentation: " + path.name)
        source = r.get("source_group")
        if source is not None and source != r["group_id"]:
            raise ValueError("derived/replayed recording must retain its source group")
        fingerprint = digest(r["samples"])
        if r["record_id"] in seen_ids or fingerprint in seen_samples:
            raise ValueError("duplicate identity or trajectory: " + path.name)
        seen_ids.add(r["record_id"])
        seen_samples.add(fingerprint)
        evidence.append(digest(r))
        item = representation(r["samples"], r["seed"], r["path_version"])
        if not item["quality"]["eligible"]:
            excluded.append({"record_id": r["record_id"], "label": r["label"], "device": r["device"],
                             "reason": "insufficient native coverage", **item["quality"]})
            continue
        records.append(r)
        values.append(item)
    if not records:
        raise ValueError("no recordings meet sequence quality requirements")
    return {"records": records, "x": np.stack([v["vector"] for v in values]),
            "sequence": np.stack([v["sequence"] for v in values]),
            "y": np.array([r["label"] == "bot" for r in records], dtype=np.int64),
            "baseline": np.array([score(r["samples"], r["seed"], {**BASELINE, "path_version": r["path_version"]})["pass"] for r in records]),
            "excluded": excluded, "fingerprint": digest(evidence),
            "test_only": test_only}


def split(data, held_out_family=None):
    records = data["records"]
    if len({r["group_id"] for r in records if r["label"] == "human"}) < 10:
        raise ValueError("need at least 10 independent enrolled human participants; this is a smoke-test minimum, not sufficient validation")
    if held_out_family and not any(r.get("attack_family") == held_out_family for r in records):
        raise ValueError("held-out attack family not found")
    parts = {"train": [], "validation": [], "test": []}
    for i, r in enumerate(records):
        # Assignment does not change when another session from a person is added.
        bucket = int(hashlib.sha256(("followit-split-v1:" + r["group_id"]).encode()).hexdigest()[:8], 16) % 100
        name = "test" if bucket >= 80 else "validation" if bucket >= 60 else "train"
        if name != "test" and held_out_family and r.get("attack_family") == held_out_family:
            continue
        parts[name].append(i)
    for name, indices in parts.items():
        if set(data["y"][indices]) != {0, 1}:
            raise ValueError(name + " needs both humans and attacks from independent groups; collect more groups")
    train_devices = {records[i]["device"] for i in parts["train"] if records[i]["label"] == "human"}
    for name in ("validation", "test"):
        devices = {records[i]["device"] for i in parts[name] if records[i]["label"] == "human"}
        if devices != train_devices:
            raise ValueError("human device coverage must match across train, validation and test; collect more groups")
    return {k: np.asarray(v, dtype=int) for k, v in parts.items()}


def normalization(data, train):
    x = data["x"][train]
    seq = data["sequence"][train]
    observed = seq[:, :, :7][seq[:, :, 7] > 0]
    return {"mean": x.mean(axis=0).tolist(), "scale": np.maximum(x.std(axis=0), 1e-5).tolist(),
            "sequence_mean": observed.mean(axis=0).tolist(), "sequence_scale": np.maximum(observed.std(axis=0), 1e-5).tolist()}


def transform(x, sequence, norm):
    x = np.clip((np.asarray(x) - norm["mean"]) / norm["scale"], -20, 20).astype(np.float32)
    seq = np.asarray(sequence, dtype=np.float32).copy()
    seq[..., :7] = np.clip((seq[..., :7] - norm["sequence_mean"]) / norm["sequence_scale"], -20, 20)
    seq[..., :7] *= seq[..., 7:8]
    return x, seq
