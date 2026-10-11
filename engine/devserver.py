"""Local recording/scoring server, deliberately not the full lab API emulator."""

import json
import secrets
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool

from engine.scorer import normalize_samples, score

ROOT = Path(__file__).resolve().parents[1]


class Attempt(BaseModel):
    challenge_id: str
    samples: list[tuple[float, float, float]] = Field(min_length=2, max_length=10000)
    device: Literal["mouse", "trackpad", "touch"]
    pointer_type: Literal["mouse", "pen", "touch"]


class SaveRecording(BaseModel):
    attempt_id: str
    consent: StrictBool
    nondominant_hand: StrictBool = False


def create_app(*, traces_dir=None, path_js=None, clock=time.monotonic):
    app = FastAPI(title="Follow It local recorder")
    traces_dir = Path(traces_dir) if traces_dir is not None else ROOT / "contracts/fixtures/human_traces"
    path_js = Path(path_js) if path_js is not None else ROOT / "web/static/path.js"
    variant = json.loads((ROOT / "contracts/fixtures/variant_v1.json").read_text())
    challenges = {}
    attempts = {}

    def prune():
        now = clock()
        for collection in (challenges, attempts):
            for key in list(collection):
                if collection[key]["expires"] <= now:
                    del collection[key]

    @app.get("/healthz")
    def health():
        return {"status": "ok", "mode": "local_recorder", "path_js_available": path_js.is_file()}

    @app.get("/dev/recorder")
    def recorder():
        return FileResponse(Path(__file__).parent / "static/recorder.html")

    @app.get("/dev/path.js")
    def javascript():
        if not path_js.is_file():
            raise HTTPException(503, "Person 1's path.js is missing; run engine/prepare-recorder.ps1")
        return FileResponse(path_js, media_type="text/javascript")

    @app.post("/dev/challenges")
    def challenge():
        prune()
        challenge_id = uuid4().hex
        seed = secrets.randbits(32)
        challenges[challenge_id] = {"seed": seed, "expires": clock() + 120}
        return {"challenge_id": challenge_id, "seed": seed, "duration_ms": 3000, "expires_in_s": 120}

    @app.post("/dev/attempts")
    def attempt(body: Attempt):
        prune()
        challenge = challenges.get(body.challenge_id)
        if challenge is None:
            raise HTTPException(404, "challenge missing, expired, or already submitted")
        try:
            samples = normalize_samples(body.samples)
            if samples[-1, 0] > 3000:
                raise ValueError("recordings must stay inside the three-second challenge")
            result = score(samples.tolist(), challenge["seed"], variant)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        del challenges[body.challenge_id]
        attempt_id = uuid4().hex
        attempts[attempt_id] = {"expires": clock() + 600, "filename": None, "trace": {
            "seed": challenge["seed"], "samples": samples.tolist(), "device": body.device,
            "pointer_type": body.pointer_type, "cohort": "human_test", "round_id": None,
        }}
        return {"attempt_id": attempt_id, "result": result, "saved": False}

    @app.post("/dev/recordings")
    def save(body: SaveRecording):
        if not body.consent:
            raise HTTPException(400, "explicit consent is required to save a human recording")
        prune()
        attempt = attempts.get(body.attempt_id)
        if attempt is None:
            raise HTTPException(404, "attempt missing or expired; record again")
        if attempt["filename"] is None:
            trace = {**attempt["trace"], "tester": {"consent": True, "nondominant_hand": body.nondominant_hand}}
            traces_dir.mkdir(parents=True, exist_ok=True)
            filename = "team_" + uuid4().hex + ".json"
            with (traces_dir / filename).open("x", encoding="utf-8") as output:
                json.dump(trace, output, indent=2, allow_nan=False)
                output.write("\n")
            attempt["filename"] = filename
        return {"saved": True, "filename": attempt["filename"]}

    return app


app = create_app()
