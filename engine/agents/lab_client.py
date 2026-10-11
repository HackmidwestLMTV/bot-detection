"""Fixed lab routes; the model cannot choose URLs, cohorts, or credentials."""

import time
from urllib.parse import quote, urlsplit

import httpx


class LabClient:
    def __init__(self, base_url, lab_key, *, transport=None, allow_internal_http=False):
        url = urlsplit(base_url)
        local = url.hostname in ("localhost", "127.0.0.1", "::1")
        internal = allow_internal_http and url.hostname == "app" and url.port == 8000
        if (not url.hostname or (url.scheme != "https" and not ((local or internal) and url.scheme == "http"))
                or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("API_BASE must be an HTTPS origin or loopback HTTP origin")
        if not lab_key:
            raise ValueError("LAB_KEY is required")
        self.client = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-Lab-Key": lab_key},
                                   timeout=15, follow_redirects=False, transport=transport)

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.status_code != 204 else None

    def active_variant(self):
        return self.request("GET", "/v1/variants/active")

    def forgeries(self, run_id=None):
        return self.request("GET", "/v1/lab/forgeries", params={"round_id": run_id} if run_id else {})

    def challenge(self, run_id):
        return self.request("POST", "/v1/challenges", json={"session_id": run_id})

    def submit(self, challenge, samples, run_id, *, device="mouse", pointer_type="mouse"):
        before = {row["attempt_id"] for row in self.forgeries(run_id)}
        response = self.request("POST", "/v1/challenges/" + quote(challenge["challenge_id"], safe="") + "/attempt",
                                json={"samples": samples, "device": device, "pointer_type": pointer_type,
                                      "cohort": "red", "round_id": run_id})
        after = [row for row in self.forgeries(run_id) if row["attempt_id"] not in before]
        if len(after) != 1:
            raise RuntimeError("cannot associate scored attempt with one stored evidence ID")
        return {"attempt_id": after[0]["attempt_id"], **response["result"]}

    def event(self, run_id, kind, data, *, agent="red"):
        self.request("POST", "/v1/lab/events", json={"run_id": run_id, "agent": agent, "type": kind,
                                                    "ts": time.time(), "data": data})

    def human_features(self):
        return self.request("GET", "/v1/lab/human-features")

    def propose(self, variant):
        return self.request("POST", "/v1/variants", json=variant)

    def run_gate(self, variant_id, run_id):
        return self.request("POST", "/v1/lab/gate", json={"candidate_id": variant_id, "run_id": run_id})

    def create_approval(self, interrupt_id, variant_id, decision, run_id):
        return self.request("POST", "/v1/lab/approvals", json={"interrupt_id": interrupt_id,
                            "variant_id": variant_id, "gate": decision, "run_id": run_id})

    def approval(self, approval_id):
        return self.request("GET", "/v1/lab/approvals/" + quote(approval_id, safe=""))

    def activate(self, variant_id, run_id):
        return self.request("POST", "/v1/variants/" + quote(variant_id, safe="") + "/activate", params={"run_id": run_id})

    def next_command(self):
        return self.request("GET", "/v1/lab/commands/next")
