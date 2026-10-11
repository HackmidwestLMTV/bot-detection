# Agent and deployment operations

Run commands from the repository root with Python 3.12 and the dependencies in
[the main README](../README.md). Keep credentials in the ignored `.env` or a private
environment. The app owns PostgreSQL; the worker uses authenticated HTTP only.

## Configure and run agents

Set `API_BASE`, `LAB_KEY`, `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, and `MODEL_ID`.
Use `MODEL_ID=hackathon-chat` for the configured Akamai endpoint. The worker loads
the root `.env`; existing process variables take precedence.

```bash
python -m engine.agents.smoke --check-config
python -m engine.worker --check-api
python -m engine.worker
```

The first two commands make no model calls. The worker consumes Run Red / Run Blue
commands from `/lab`. For one explicit round, use `--once red` or `--once blue`.
`python -m engine.agents.smoke` makes bounded live model calls with disposable
counter tools to check tool use, typed reports, denial, and approval interrupts.
It does not activate an application policy.

Akamai is the default provider. Optional Bedrock requires an explicit
`USE_BEDROCK=1`, `AWS_REGION`, `BEDROCK_MODEL_ID`, and suitable AWS credentials.
It is not an automatic fallback or a verified provider for the live demo.

## Evidence and approval

Red tests generated trails against the issued challenge's path, duration, and
scoring policy. It can use consented local residual transplantation from round 3.
Blue receives aggregate human-feature statistics and synthetic attack results.
Neither sends raw human recordings in model prompts.

The server compares matching path/presentation evidence and requires fewer forgery
passes with no increase in human rejection counts within represented device groups.
It fingerprints the evidence and rechecks it at activation. Passing the gate only
requests operator review. Denial, timeout, missing evidence, or changed evidence
cannot activate a policy. If the baseline already rejects all stored forgeries,
there is no strict improvement on that sample; keep the baseline or collect new
attack evidence instead of resetting state to manufacture a pass.

## Worker state and failures

- Red allows eight forge calls, four transplants from round 3, and 16 model calls.
  Blue allows three proposals and 24 model calls, with bounded tool budgets.
- Model requests time out after 60 seconds; lab HTTP calls after 15 seconds.
  Approval waits default to 180 seconds. Failures emit sanitized timestamped events.
- Run one worker replica: pacing budgets are shared within a process, not between
  replicas. Model failures preserve the active visitor policy.
- The SQLite journal persists round counters and claims. A crash does not
  automatically replay a claimed run. Queue a new run to retry; there is no
  exactly-once queue recovery guarantee. `/lab` Reset does not reset that journal.
- `--state` / `WORKER_STATE_PATH` selects the journal; `--traces` /
  `HUMAN_TRACES_DIR` selects consented local traces. Use separate state for
  disposable rehearsals. Never classify generated traces as human evidence.

## Disposable local lab

For engine experiments without PostgreSQL, set a local test `LAB_KEY` and run:

```bash
python -m uvicorn engine.labserver:app --host 127.0.0.1 --port 8001
```

Configure a separate worker with `API_BASE=http://127.0.0.1:8001` and the same key.
Open `/lab` on port 8001. The lab loads consented local calibration files at startup;
restart after collection. It does not issue real reservation passes and is not a
substitute for the PostgreSQL integration tests. Keep it bound to localhost.

## Deploy to Linode

The existing collection deployment uses `compose.yaml` plus
`compose.research.yaml`: one app, one worker, Caddy, private persistent recordings,
and a read-only model mount. Only Caddy exposes public HTTP/HTTPS. Port 8000 binds
to VM localhost. Restrict SSH to operator addresses. Caddy overwrites forwarded
client IPs; review the full trusted-proxy chain before adding a CDN.

For a new VM, review `vm_setup.sh` and explicitly pin an integrated commit with
`RELEASE_REF=<reviewed-commit-sha>`. Configure Managed PostgreSQL access for the VM,
`DATABASE_URL` with TLS, `DOMAIN`, `PUBLIC_URL`, a private lab key, and provider
credentials. The scripts default to `origin/main`; pin `RELEASE_REF` to a reviewed
commit when deploying a reproducible release.

For the **existing research VM**, use the paired, rollback-enabled collection
installer. Package the reviewed working tree locally:

```bash
python release-artifacts/package-research.py --release followit-reviewed-20261011
```

Choose a unique lowercase release name. Transfer its archive securely to the VM,
verify its SHA-256, extract it into a fresh `/root/followit/releases/<release>`
directory, and privately copy the active release's `.env` there with mode 0600.
From that new directory, run `bash deploy-research.sh`.

The installer requires an existing app and worker. It builds both images before
replacement, waits for idle lab work, preserves the active policy and historical
evidence, then verifies health, source hashes, private storage, retention, and worker
API access. Verification failure rolls both services back. Old releases remain
available. A stale journal row can block the idle check after a crash; inspect the
worker and journal instead of deleting evidence to force deployment.

Current collection storage is private VM disk; paid Object Storage is not required
or enabled by this workflow. The installer expects no loaded shadow artifact.
Optional future artifact deployment needs the validation described in
[model research](ml/README.md). It cannot activate a scoring policy.

After rollout, check public `/healthz`, `/`, `/lab`, and `/research`, plus authenticated
worker readiness. Do not run resetting test suites or replay fixtures against the
live database. Retrieve `LAB_KEY` privately from the active environment and share
only participant invitations. See [recordings](../recordings/README.md) for an
explicitly labeled local backup demonstration.
