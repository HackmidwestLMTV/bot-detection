"""Non-executable JSON/NPZ artifacts and NumPy-only inference for optional shadow use."""
import hashlib
import json
from pathlib import Path

import numpy as np

from contracts.presentation import PRESENTATION_VERSION
from contracts.research import FEATURE_VERSION, digest
from engine.features_v2 import CHANNELS, FEATURE_NAMES, representation
from engine.path import DEFAULT_PATH_VERSION
from .dataset import transform


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -60, 60)))


def neural(kind, weights, sequence, features):
    mask = sequence[:, 7:8]
    if kind == "cnn":
        h = sequence.T
        for name, padding in (("conv1", 2), ("conv2", 2), ("conv3", 1)):
            w, b = weights[name + ".weight"], weights[name + ".bias"]
            windows = np.lib.stride_tricks.sliding_window_view(np.pad(h, ((0, 0), (padding, padding))), w.shape[2], axis=1)
            h = np.maximum(np.einsum("itk,oik->ot", windows, w, optimize=True) + b[:, None], 0)
        h = h.T
    else:
        h0, c = np.zeros(32, dtype=np.float32), np.zeros(32, dtype=np.float32)
        outputs = []
        wi, wh = weights["rnn.weight_ih_l0"], weights["rnn.weight_hh_l0"]
        bias = weights["rnn.bias_ih_l0"] + weights["rnn.bias_hh_l0"]
        for row in sequence:
            i, f, g, o = np.split(wi @ row + wh @ h0 + bias, 4)
            c = sigmoid(f) * c + sigmoid(i) * np.tanh(g)
            h0 = sigmoid(o) * np.tanh(c)
            outputs.append(h0)
        h = np.stack(outputs)
    pooled = (h * mask).sum(axis=0) / max(float(mask.sum()), 1)
    joined = np.r_[pooled, features]
    hidden = np.maximum(weights["head1.weight"] @ joined + weights["head1.bias"], 0)
    return float(sigmoid(weights["head2.weight"] @ hidden + weights["head2.bias"])[0])


def forest_predict(trees, x):
    values = []
    for tree in trees:
        node = 0
        while tree["left"][node] != -1:
            node = tree["left"][node] if x[tree["feature"][node]] <= tree["threshold"][node] else tree["right"][node]
        values.append(tree["bot_fraction"][node])
    return float(np.mean(values))


def expected_shapes(kind):
    shapes = {"head1.weight": (16, (64 if kind == "cnn" else 32) + 25), "head1.bias": (16,),
              "head2.weight": (1, 16), "head2.bias": (1,)}
    if kind == "cnn":
        for name, dims in (("conv1", (32, 8, 5)), ("conv2", (64, 32, 5)), ("conv3", (64, 64, 3))):
            shapes[name + ".weight"], shapes[name + ".bias"] = dims, (dims[0],)
    else:
        shapes.update({"rnn.weight_ih_l0": (128, 8), "rnn.weight_hh_l0": (128, 32),
                       "rnn.bias_ih_l0": (128,), "rnn.bias_hh_l0": (128,)})
    return shapes


class Artifact:
    def __init__(self, directory, *, allow_test=False):
        root = Path(directory)
        m = json.loads((root / "manifest.json").read_bytes())
        self.manifest = m
        self.fingerprint = digest(m)
        if (m.get("schema") != "movement_model_v1" or m.get("mode") != "shadow_only"
                or m.get("feature_version") != FEATURE_VERSION or m.get("features") != list(FEATURE_NAMES)
                or m.get("channels") != list(CHANNELS) or m.get("presentation_version") != PRESENTATION_VERSION
                or m.get("path_version") != DEFAULT_PATH_VERSION or m.get("kind") not in ("rf", "cnn", "lstm")
                or (m.get("test_only") is not False and not allow_test)):
            raise ValueError("incompatible or test-only model artifact")
        for name in ("dataset_fingerprint", "split_fingerprint"):
            if not isinstance(m.get(name), str) or len(m[name]) != 64:
                raise ValueError("missing evidence fingerprint")
        if not 0 <= m["threshold"] <= 1.000001:
            raise ValueError("invalid threshold")
        for name, size in (("mean", 25), ("scale", 25), ("sequence_mean", 7), ("sequence_scale", 7)):
            a = np.asarray(m["normalization"][name], dtype=float)
            if a.shape != (size,) or not np.isfinite(a).all() or ("scale" in name and (a <= 0).any()):
                raise ValueError("invalid preprocessing")
        filename = "forest.json" if m["kind"] == "rf" else "weights.npz"
        path = root / filename
        if path.stat().st_size > 10_000_000 or file_hash(path) != m["weights_sha256"]:
            raise ValueError("model weights missing or changed")
        if m["kind"] == "rf":
            self.weights = json.loads(path.read_bytes())
            if not 1 <= len(self.weights) <= 200:
                raise ValueError("invalid forest")
            for tree in self.weights:
                n = len(tree["left"])
                if not 1 <= n <= 2000 or any(len(v) != n for v in tree.values()):
                    raise ValueError("invalid tree size")
                for j in range(n):
                    if tree["left"][j] != -1 and not (j < tree["left"][j] < n and j < tree["right"][j] < n and 0 <= tree["feature"][j] < 25):
                        raise ValueError("invalid tree links")
                    if not np.isfinite(tree["threshold"][j]) or not 0 <= tree["bot_fraction"][j] <= 1:
                        raise ValueError("invalid tree values")
        else:
            with np.load(path, allow_pickle=False) as z:
                self.weights = {k: z[k] for k in z.files}
            shapes = expected_shapes(m["kind"])
            if set(self.weights) != set(shapes) or any(v.shape != shapes[k] or not np.isfinite(v).all() for k, v in self.weights.items()):
                raise ValueError("invalid neural weights")

    def predict(self, vector, sequence):
        x, seq = transform(vector, sequence, self.manifest["normalization"])
        risk = forest_predict(self.weights, x) if self.manifest["kind"] == "rf" else neural(self.manifest["kind"], self.weights, seq, x)
        return {"bot_risk": risk, "would_pass": risk < self.manifest["threshold"],
                "model_fingerprint": self.fingerprint, "mode": "shadow_only"}

    def score(self, samples, seed, path_version, presentation_version):
        if path_version != self.manifest["path_version"] or presentation_version != self.manifest["presentation_version"]:
            raise ValueError("challenge/model version mismatch")
        rep = representation(samples, seed, path_version)
        if not rep["quality"]["eligible"]:
            return {"status": "insufficient_coverage", "quality": rep["quality"], "model_fingerprint": self.fingerprint}
        return {"status": "scored", **self.predict(rep["vector"], rep["sequence"]), "quality": rep["quality"]}
