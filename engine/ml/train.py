"""Compare fixed RF/CNN/LSTM candidates, tune on validation, audit on locked test."""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from contracts.presentation import PRESENTATION_VERSION
from contracts.research import DEVICES, FEATURE_VERSION, canonical, digest
from engine.features_v2 import CHANNELS, FEATURE_NAMES
from .artifact import Artifact, file_hash
from .dataset import load, normalization, split, transform


def choose_threshold(risk, data, indices):
    records, y, baseline = data["records"], data["y"], data["baseline"]
    candidates = np.r_[0., np.unique(risk) + 1e-7, 1.000001]
    best, blocked = 1.000001, -1
    for threshold in candidates:
        passing = risk < threshold
        safe = True
        for device in DEVICES:
            human = np.array([y[i] == 0 and records[i]["device"] == device for i in indices])
            if human.any() and ((~passing[human]).sum() > (~baseline[indices][human]).sum()
                                or (~passing[human]).mean() > .05):
                safe = False
        rejected_bots = int((~passing[y[indices] == 1]).sum())
        if safe and rejected_bots > blocked:
            best, blocked = float(threshold), rejected_bots
    return best


def metrics(data, indices, passing):
    rows = [data["records"][i] for i in indices]
    y = data["y"][indices]
    out = {"human_devices": {}, "attack_families": {}}
    for device in DEVICES:
        mask = np.array([r["label"] == "human" and r["device"] == device for r in rows])
        out["human_devices"][device] = {"n": int(mask.sum()), "rejected": int((~passing[mask]).sum()),
            "participants": len({r["group_id"] for r, keep in zip(rows, mask) if keep}),
            "status": "represented sample" if mask.any() else "untested"}
        groups = sorted({r["group_id"] for r, keep in zip(rows, mask) if keep})
        if len(groups) >= 2:
            totals = np.array([[sum(keep and r["group_id"] == g and not p for r, keep, p in zip(rows, mask, passing)),
                                sum(keep and r["group_id"] == g for r, keep in zip(rows, mask))] for g in groups])
            draws = np.random.default_rng(42).integers(0, len(groups), size=(1000, len(groups)))
            sampled = totals[draws].sum(axis=1)
            out["human_devices"][device]["participant_bootstrap_95_interval"] = np.percentile(sampled[:, 0] / sampled[:, 1], [2.5, 97.5]).tolist()
            out["human_devices"][device]["uncertainty_note"] = "Cluster bootstrap; small or zero-error samples may give misleadingly narrow intervals."
    for family in sorted({r["attack_family"] for r in rows if r["label"] == "bot"}):
        mask = np.array([r.get("attack_family") == family for r in rows])
        out["attack_families"][family] = {"n": int(mask.sum()), "accepted": int(passing[mask].sum())}
    out["attacks_accepted"] = int(passing[y == 1].sum())
    out["attacks_total"] = int((y == 1).sum())
    return out


def compare(data, output, *, epochs=15, held_out_family=None):
    import sklearn
    import torch
    from sklearn.ensemble import RandomForestClassifier
    from .models import SequenceModel

    if not 1 <= epochs <= 100:
        raise ValueError("epochs must be 1-100")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("use a new empty run directory; preserve the previous audit")
    parts = split(data, held_out_family)
    norm = normalization(data, parts["train"])
    x, seq = transform(data["x"], data["sequence"], norm)
    y = data["y"]
    tr, va, te = (parts[k] for k in ("train", "validation", "test"))
    assignments = {name: sorted({data["records"][i]["group_id"] for i in ids}) for name, ids in parts.items()}
    split_fingerprint = digest(assignments)
    report = {"mode": "offline_research", "test_only": data["test_only"], "dataset_fingerprint": data["fingerprint"],
              "split_fingerprint": split_fingerprint, "partitions": {k: {"records": len(v), "groups": len(assignments[k])} for k, v in parts.items()},
              "held_out_family": held_out_family, "quality_exclusions": data["excluded"],
              "baseline": metrics(data, te, data["baseline"][te]), "models": {},
              "caveat": "Recorded sample only. Bot risk is not calibrated probability of humanity. No activation is authorized by this report."}
    torch.set_num_threads(1)
    for kind in ("rf", "cnn", "lstm"):
        directory = root / kind
        directory.mkdir()
        if kind == "rf":
            model = RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_leaf=2,
                                           class_weight="balanced", random_state=42, n_jobs=1)
            model.fit(x[tr], y[tr])
            trees = []
            for estimator in model.estimators_:
                tree = estimator.tree_
                value = tree.value[:, 0, :]
                trees.append({"left": tree.children_left.tolist(), "right": tree.children_right.tolist(),
                              "feature": tree.feature.tolist(), "threshold": tree.threshold.tolist(),
                              "bot_fraction": (value[:, 1] / value.sum(axis=1)).tolist()})
            (directory / "forest.json").write_bytes(canonical(trees))
            predict = lambda ids: model.predict_proba(x[ids])[:, 1]
        else:
            torch.manual_seed(42)
            model = SequenceModel(kind)
            optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.01)
            loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(float((y[tr] == 0).sum() / (y[tr] == 1).sum())))
            xt, st, yt = torch.from_numpy(x), torch.from_numpy(seq), torch.tensor(y, dtype=torch.float32)
            generator = np.random.default_rng(42)
            for _ in range(epochs):
                model.train()
                shuffled = generator.permutation(tr)
                for offset in range(0, len(shuffled), 32):
                    batch = shuffled[offset:offset + 32]
                    optimizer.zero_grad()
                    loss = loss_fn(model(st[batch], xt[batch]), yt[batch])
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
                    optimizer.step()
            model.eval()
            def predict(ids):
                with torch.no_grad():
                    return torch.sigmoid(model(st[ids], xt[ids])).numpy()
            np.savez_compressed(directory / "weights.npz", **{k: v.detach().numpy() for k, v in model.state_dict().items()})
        threshold = choose_threshold(predict(va), data, va)
        manifest = {"schema": "movement_model_v1", "mode": "shadow_only", "kind": kind,
                    "test_only": data["test_only"], "feature_version": FEATURE_VERSION,
                    "features": list(FEATURE_NAMES), "channels": list(CHANNELS),
                    "path_version": "smooth_v2", "presentation_version": PRESENTATION_VERSION,
                    "threshold": threshold, "normalization": norm, "dataset_fingerprint": data["fingerprint"],
                    "split_fingerprint": split_fingerprint, "held_out_family": held_out_family,
                    "training": {"seed": 42, "epochs": epochs if kind != "rf" else None,
                                 "torch": torch.__version__, "sklearn": sklearn.__version__},
                    "weights_sha256": file_hash(directory / ("forest.json" if kind == "rf" else "weights.npz"))}
        (directory / "manifest.json").write_bytes(canonical(manifest))
        artifact = Artifact(directory, allow_test=data["test_only"])
        # Validate deployment-format inference against the training library on held-out inputs.
        portable = np.array([artifact.predict(data["x"][i], data["sequence"][i])["bot_risk"] for i in te])
        expected = predict(te)
        if not np.allclose(portable, expected, rtol=1e-4, atol=1e-5):
            raise ValueError("portable inference disagrees with training model")
        candidate = metrics(data, te, portable < threshold)
        baseline = report["baseline"]
        candidate["recorded_sample_gate"] = (candidate["attacks_accepted"] < baseline["attacks_accepted"] and all(
            candidate["human_devices"][d]["rejected"] <= baseline["human_devices"][d]["rejected"] for d in DEVICES))
        latencies = []
        for i in te[:30]:
            r = data["records"][i]
            t = time.perf_counter()
            artifact.score(r["samples"], r["seed"], r["path_version"], r["presentation_version"])
            latencies.append((time.perf_counter() - t) * 1000)
        candidate.update({"threshold": threshold, "model_fingerprint": artifact.fingerprint,
                          "cpu_p95_ms_including_features": float(np.percentile(latencies, 95)),
                          "latency_samples": len(latencies), "portable_max_error": float(np.max(np.abs(portable - expected)))})
        report["models"][kind] = candidate
    # Contains pseudonymous partition IDs, not raw trajectories. Protect the run directory.
    (root / "partitions.json").write_bytes(canonical(assignments))
    (root / "report.json").write_bytes(canonical(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data")
    parser.add_argument("output")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--held-out-family")
    args = parser.parse_args()
    key = Path(args.key_file).read_text().strip()
    data = load(args.data, key)
    report = compare(data, args.output, epochs=args.epochs, held_out_family=args.held_out_family)
    print(json.dumps({"report": str(Path(args.output) / "report.json"), "models": list(report["models"]), "activation": False}))


if __name__ == "__main__":
    main()
