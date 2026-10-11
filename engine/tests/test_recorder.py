import json

from fastapi.testclient import TestClient

from engine.devserver import create_app
from engine.forger import forge_trail


def submit(client):
    challenge = client.post("/dev/challenges").json()
    response = client.post("/dev/attempts", json={"challenge_id": challenge["challenge_id"],
        "samples": forge_trail(challenge["seed"], path_version=challenge["path_version"]), "device": "mouse", "pointer_type": "mouse"})
    assert response.status_code == 200
    return response.json()


def test_recorder_consent_unique_save_and_no_implicit_persistence(tmp_path):
    # Synthetic API tests write only to pytest's temporary directory, never human fixtures.
    folder = tmp_path / "recordings"
    client = TestClient(create_app(traces_dir=folder))
    assert client.get("/dev/recorder").status_code == 200
    assert client.get("/dev/path.js").status_code == 200
    attempt = submit(client)
    assert attempt["saved"] is False and not folder.exists()
    payload = {"attempt_id": attempt["attempt_id"], "consent": False}
    assert client.post("/dev/recordings", json=payload).status_code == 400
    assert not folder.exists()
    payload.update(consent=True, nondominant_hand=True)
    saved = client.post("/dev/recordings", json=payload).json()
    assert saved["saved"]
    assert client.post("/dev/recordings", json=payload).json() == saved
    trace = json.loads((folder / saved["filename"]).read_text())
    assert trace["tester"] == {"consent": True, "nondominant_hand": True}
    assert trace["cohort"] == "human_test" and trace["device"] == "mouse"
    assert trace["path_version"] == "smooth_v2"
    assert attempt["result"]["features"]["err_mean_px"]["value"] < 1e-9
    assert "seed" in trace and len(trace["samples"]) == 181
    second = submit(client)
    next_saved = client.post("/dev/recordings", json={"attempt_id": second["attempt_id"], "consent": True}).json()
    assert saved["filename"] != next_saved["filename"]
    assert len(list(folder.glob("*.json"))) == 2


def test_expiration_and_bad_attempts(tmp_path):
    now = [0]
    client = TestClient(create_app(traces_dir=tmp_path, clock=lambda: now[0]))
    challenge = client.post("/dev/challenges").json()
    payload = {"challenge_id": challenge["challenge_id"], "samples": [[0, 1, 2], [500, 2, 3]],
               "device": "touch", "pointer_type": "touch"}
    assert client.post("/dev/attempts", json=payload).status_code == 400
    payload["samples"] = [[0, 1, 2], [3001, 2, 3]]
    assert client.post("/dev/attempts", json=payload).status_code == 400
    payload["samples"] = [[0, 1, 2], [3000, 2, 3]]
    now[0] = 121
    assert client.post("/dev/attempts", json=payload).status_code == 404
    attempt = submit(client)
    now[0] += 601
    assert client.post("/dev/recordings", json={"attempt_id": attempt["attempt_id"], "consent": True}).status_code == 404
    assert not list(tmp_path.glob("*.json"))


def test_missing_javascript_and_strict_consent(tmp_path):
    client = TestClient(create_app(traces_dir=tmp_path, path_js=tmp_path / "missing.js"))
    assert client.get("/dev/path.js").status_code == 503
    assert client.get("/healthz").json()["path_js_available"] is False
    attempt = submit(client)
    assert client.post("/dev/recordings", json={"attempt_id": attempt["attempt_id"], "consent": "true"}).status_code == 422
    assert not list(tmp_path.glob("*.json"))
