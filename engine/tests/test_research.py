"""Fixture-only tests: never create human evidence or deployable research weights."""
import copy
import json
import time

import numpy as np
import pytest

from contracts.research import COLLECTOR_VERSION, CONSENT_VERSION, RETENTION_S, SCHEMA, canonical, sign, verify
from engine.features_v2 import representation
from engine.ml.attacks import samples
from engine.ml.collect import cleanup, write_private
from engine.ml.dataset import load, normalization, split, transform

KEY = "fixture-only-key-not-a-secret"


def recording(seed=42, group="person_0001", label="human", family="lagged_noise"):
    now = time.time()
    return {"schema": SCHEMA, "record_id": f"record_{seed:08d}", "group_id": group, "session_group": "session_123456",
            "participant_id": group, "consent": CONSENT_VERSION, "label": label, "provenance": "test_fixture",
            "attack_family": family, "device": "mouse", "collector_version": COLLECTOR_VERSION,
            "collected_at": now, "expires_at": now + RETENTION_S, "seed": seed,
            "path_version": "smooth_v2", "presentation_version": "plain_ring_v1", "samples": samples(seed, family)}


def test_signed_provenance_tampering_expiry_and_fixture_exclusion():
    r = recording()
    envelope = sign(r, KEY)
    with pytest.raises(ValueError, match="test fixtures"):
        verify(envelope, KEY)
    assert verify(envelope, KEY, allow_test=True) == r
    with pytest.raises(ValueError, match="expired"):
        verify(envelope, KEY, allow_test=True, now=r["expires_at"])
    envelope["record"]["seed"] += 1
    with pytest.raises(ValueError, match="signature"):
        verify(envelope, KEY, allow_test=True)
    r = recording()
    r["provenance"] = "public_human_test"
    with pytest.raises(ValueError, match="enrolled"):
        verify(sign(r, KEY), KEY)


def test_target_response_distinguishes_unrelated_wave_and_masks_long_gaps():
    follow = representation(samples(42, "lagged_noise"), 42)
    wave = representation(samples(42, "open_loop_wave"), 42)
    assert follow["features"]["velocity_alignment"] > wave["features"]["velocity_alignment"] + .4
    assert follow["features"]["lag_alignment_gain"] > wave["features"]["lag_alignment_gain"]
    sparse = [p for p in samples(42, "perfect_follow") if not 800 < p[0] < 2000]
    rep = representation(sparse, 42)
    assert rep["quality"]["eligible"] is False
    assert np.all(rep["sequence"][60:110] == 0)
    assert rep["sequence"].shape == (181, 8) and len(rep["vector"]) == 25
    with pytest.raises(ValueError):
        representation([[0, 1, 1], [3001, 2, 2]], 42)


def test_dataset_rejects_legacy_duplicates_and_source_leakage(tmp_path):
    r = recording()
    target = tmp_path / "one.json"
    write_private(target, sign(r, KEY))
    assert len(load(tmp_path, KEY, allow_test=True)["records"]) == 1
    r["presentation_version"] = "legacy"
    target.write_bytes(canonical(sign(r, KEY)))
    with pytest.raises(ValueError, match="legacy"):
        load(tmp_path, KEY, allow_test=True)
    r["presentation_version"] = "plain_ring_v1"
    r["source_group"] = "other_person"
    target.write_bytes(canonical(sign(r, KEY)))
    with pytest.raises(ValueError, match="source group"):
        load(tmp_path, KEY, allow_test=True)
    del r["source_group"]
    target.write_bytes(canonical(sign(r, KEY)))
    write_private(tmp_path / "two.json", sign({**r, "record_id": "different_id"}, KEY))
    with pytest.raises(ValueError, match="duplicate"):
        load(tmp_path, KEY, allow_test=True)
    assert cleanup(tmp_path, now=r["expires_at"] + 1) == 2


def make_data(tmp_path):
    for label in ("human", "bot"):
        for i in range(30):
            # BOTH classes here are manufactured fixtures, never enrolled people.
            r = recording(1000 + i + (100 if label == "bot" else 0), f"{label}_group_{i:04d}", label,
                          "open_loop_wave" if label == "bot" else "lagged_noise")
            write_private(tmp_path / (r["record_id"] + ".json"), sign(r, KEY))
    return load(tmp_path, KEY, allow_test=True)


def test_quality_exclusions_are_bound_into_evidence_fingerprint(tmp_path):
    good, sparse = recording(42), recording(43)
    sparse["samples"] = [sparse["samples"][0], sparse["samples"][-1]]
    write_private(tmp_path / "good.json", sign(good, KEY))
    first = load(tmp_path, KEY, allow_test=True)
    write_private(tmp_path / "sparse.json", sign(sparse, KEY))
    second = load(tmp_path, KEY, allow_test=True)
    assert first["fingerprint"] != second["fingerprint"]
    assert len(second["records"]) == 1 and second["excluded"][0]["event_count"] == 2
    assert second["excluded"][0]["label"] == "human"


def test_group_partitions_and_train_only_normalization(tmp_path):
    data = make_data(tmp_path)
    parts = split(data)
    groups = [{data["records"][i]["group_id"] for i in ids} for ids in parts.values()]
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    norm = normalization(data, parts["train"])
    changed = copy.deepcopy(data)
    changed["x"][parts["test"]] *= 1e6
    assert normalization(changed, parts["train"]) == norm
    _, seq = transform(data["x"], data["sequence"], norm)
    assert np.all(seq[data["sequence"][:, :, 7] == 0] == 0)
    repeated = {**data, "records": data["records"] + [{**data["records"][0], "session_group": "new_session_123"}],
                "y": np.r_[data["y"], data["y"][0]]}
    again = split(repeated)
    assert next(k for k, ids in parts.items() if 0 in ids) == next(k for k, ids in again.items() if len(data["records"]) in ids)
    for i, r in enumerate(data["records"]):
        if r["label"] == "bot" and i % 2:
            r["attack_family"] = "feedback_control"
    unseen = split(data, "open_loop_wave")
    assert all(data["records"][i].get("attack_family") != "open_loop_wave" for name in ("train", "validation") for i in unseen[name])
    assert any(data["records"][i].get("attack_family") == "open_loop_wave" for i in unseen["test"])


def test_full_three_model_comparison_roundtrip_and_artifact_integrity(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("sklearn")
    from engine.ml.artifact import Artifact
    from engine.ml.train import compare
    raw = tmp_path / "raw"
    raw.mkdir()
    data = make_data(raw)
    output = tmp_path / "run"
    report = compare(data, output, epochs=1)
    assert set(report["models"]) == {"rf", "cnn", "lstm"}
    assert report["test_only"] is True
    for kind, result in report["models"].items():
        assert result["portable_max_error"] < 1e-5
        assert result["human_devices"]["touch"]["status"] == "untested"
        with pytest.raises(ValueError, match="test-only"):
            Artifact(output / kind)
    manifest = output / "rf" / "manifest.json"
    m = json.loads(manifest.read_bytes())
    m["presentation_version"] = "legacy"
    manifest.write_bytes(canonical(m))
    with pytest.raises(ValueError, match="incompatible"):
        Artifact(output / "rf", allow_test=True)
    with (output / "cnn" / "weights.npz").open("ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="changed"):
        Artifact(output / "cnn", allow_test=True)
