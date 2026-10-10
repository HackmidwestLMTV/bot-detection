"""The ONLY place web/ touches engine/. Real engine if importable, otherwise stubs.

Never import engine.* anywhere else. The merge flips this to real code with zero edits.
Stub results carry "stub": True so the UI can show a grey "stub scorer" badge.
"""
import json
import logging
import math
import pathlib

log = logging.getLogger("followit")
_GATE_FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "contracts" / "fixtures" / "gate_example.json"

try:
    from engine.path import make_path
    from engine.scorer import score
    from engine.gate import gate
    USING_STUBS = False
    log.warning("using real engine")
except ImportError:
    USING_STUBS = True
    log.warning("using stubs")

    def make_path(seed):
        def pos(t):  # NOT the real path; only so the page works before integration
            return (300 + 200 * math.sin(t / 700 + seed % 7), 200 + 120 * math.cos(t / 900 + seed % 5))
        return pos

    def score(samples, seed, variant):
        if not samples or samples[-1][0] - samples[0][0] < 1000:
            raise ValueError("trail too short")
        feats = {n: {"value": 0.0, "band": variant["features"][n], "ok": True,
                     "enabled": n in variant["enabled"]} for n in variant["features"]}
        return {"score": 1.0, "pass": True, "variant": variant["id"], "features": feats, "stub": True}

    def gate(candidate, baseline, humans, forgeries):
        return json.loads(_GATE_FIXTURE.read_text())
