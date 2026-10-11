"""The disposable lab never combines evidence from different target motions."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.labserver import create_lab_app
from engine.path import make_path


def test_lab_versions_challenges_and_filters_legacy_evidence():
    variant = json.loads((Path(__file__).resolve().parents[2] / "contracts/fixtures/variant_v1.json").read_text())
    variant["path_version"] = "smooth_v2"
    features = {name: sum(band) / 2 for name, band in variant["features"].items()}
    humans = [{"attempt_id": "legacy", "device": "mouse", "features": features},
              {"attempt_id": "current", "device": "touch", "features": features, "path_version": "smooth_v2",
               "presentation_version": "plain_ring_v1"}]
    app = create_lab_app(variant=variant, humans=humans)
    auth = {"X-Lab-Key": "dev"}
    with TestClient(app) as client:
        health = client.get("/healthz").json()
        assert health["human_records"] == 1 and health["excluded_legacy_human_traces"] == 1
        assert client.get("/v1/lab/human-features", headers=auth).json()[0]["attempt_id"] == "current"
        challenge = client.post("/v1/challenges", headers=auth, json={"session_id": "test-version"}).json()
        assert challenge["path_version"] == "smooth_v2"
        path = make_path(challenge["seed"], challenge["path_version"])
        samples = [[t, *path(t)] for t in (i * 1000 / 60 for i in range(181))]
        response = client.post(f"/v1/challenges/{challenge['challenge_id']}/attempt", headers=auth,
                               json={"samples": samples, "device": "mouse", "pointer_type": "mouse",
                                     "cohort": "red", "round_id": "test-version"})
        assert response.status_code == 200, response.text
        assert response.json()["result"]["features"]["err_mean_px"]["value"] < 0.01
        assert client.get("/v1/lab/forgeries", headers=auth).json()[0]["path_version"] == "smooth_v2"
        assert client.post("/v1/variants", headers=auth,
                           json={**variant, "id": "switch", "path_version": "v1"}).status_code == 422
