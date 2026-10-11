# Follow It

On a ticket checkout, one AI (Red) learns to fake a human hand, a second AI (Blue) tries to block it, and before any block goes live, a fixed gate shows how many real people it would lock out, and a person approves.

- **Ticket page** (`/`): follow a comet for 3 seconds. Pass and you get a single-use token to reserve a ticket. Fail or skip and your browser solves a small proof-of-work instead. Nobody is ever blocked.
- **Lab** (`/lab`): Red forges pointer trails against the live scorer. Blue proposes a stricter scoring variant. The gate replays every stored human trace and every forgery against it, and the variant goes live only after a person presses Approve.

The full contract between the two halves is in [contracts/CONTRACT.md](contracts/CONTRACT.md).

## Akamai services used
- **Linode VM** (g6-standard-2): app, agent worker and Caddy, all under Docker Compose.
- **Managed PostgreSQL 18**: challenges, attempts (features only), tokens, variants, approvals, gate decisions, lab events.
- **Object Storage** (`followit-trails`, us-sea-1): raw movement traces, kept only from consenting testers and only for 72 hours.
- **Hosted inference** (`ws.akamai-workshops.com`): the model behind the Red and Blue Strands agents.

## Architecture
```text
 phone / browser ──HTTPS──▶ Caddy ──▶ FastAPI app (web/) ──▶ Managed Postgres
                                         │   │  └──────────▶ Object Storage (consented trails, 72 h)
                                         │   └─ engine_adapter ─▶ engine/ (path, scorer, gate: pure functions)
 /lab dashboard ◀──── SSE ───────────────┤
                                         │  HTTP (X-Lab-Key)
                         agent worker ───┘  Red + Blue (Strands) ──▶ Akamai hosted inference
```
- The app is the only thing that touches the database. The worker talks to it over HTTP only.
- A variant can't go live without an approved approval row. The server enforces this (`403`), not only the agent.
- Tokens are single-use: an atomic `UPDATE … WHERE consumed_at IS NULL RETURNING`, plus a per-session advisory lock for the reservation cap.

## Layout
| Folder | Owner | Branch |
|---|---|---|
| `contracts/` | shared, frozen; changes go through Person 2 and are logged in `CHANGELOG.md` | `main` |
| `web/` + `Dockerfile`, `compose.yaml`, `Caddyfile`, `deploy.sh`, `vm_setup.sh` | Person 1 | `p1-platform` |
| `engine/` | Person 2 | `p2` |

## Env vars
`DATABASE_URL`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_KEY`, `S3_SECRET`, `LAB_KEY`, `POW_BITS`, `DOMAIN`, `PUBLIC_URL`, `ACME_CA` (optional), `API_BASE`, `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, `MODEL_ID`. See [.env.example](.env.example).

## Try it
```bash
curl -s -X POST https://$DOMAIN/v1/challenges -H 'content-type: application/json' -d '{"session_id":"demo"}'
# {"challenge_id":"ch_…","seed":532532022,"variant_id":"v1","duration_ms":3000,"expires_in_s":120}
curl -s https://$DOMAIN/healthz          # engine mode, active variant, human trace counts by device
```
Print `https://$DOMAIN/qr` for the table. It's a QR code to tester mode (`/?tester=1`).

## Deploy (Linode)
1. Create the Managed Postgres **first**, because it takes 5–10 minutes to provision (details below). While it provisions, create the VM (Ubuntu 24.04, `g6-standard-2`) and the bucket plus a key scoped to it. The Cloud Firewall must allow TCP 22, 80 and 443.
2. Copy `vm_setup.sh` to the VM, then as root run `bash vm_setup.sh`. It installs Docker, clones `p1-platform` explicitly, and atomically writes a private `.env` with a fresh `LAB_KEY` and `DOMAIN=<ip-with-dashes>.sslip.io`. Set `BRANCH=main` after the platform has merged, or set `DOMAIN` to use your own hostname. Existing `.env` files are preserved; keys are never printed.
3. Fill `DATABASE_URL`, `S3_KEY`, `S3_SECRET` and `AKAMAI_API_KEY` in `~/followit/.env`.
4. Run `bash ~/followit/deploy.sh engine` to integrate the reviewed `origin/p2` engine with the platform. After merging the platform, use `BRANCH=main bash ~/followit/deploy.sh engine`; set `ENGINE_REF` to a reviewed commit when pinning a release. `bash ~/followit/deploy.sh` starts only the platform and stops an existing worker.

Deployment exports an isolated snapshot under `~/.local/share/followit/releases` and preserves the operator's checkout and uncommitted files. It validates Compose and builds images before replacing containers, waits for the app's database-backed health check, then checks the worker's authenticated API access. Failed readiness exits nonzero and requires inspecting `docker compose --project-name followit logs` from the printed release folder; old snapshots are retained for inspection. The worker uses `engine/Dockerfile`, receives only model/lab settings, and keeps its journal in the `followit_worker_state` Docker volume across releases. Internal HTTP is explicitly limited to the Compose service `http://app:8000`. The app build excludes credentials, local state and raw human recordings.

Only Caddy exposes public ports. Port 8000 binds to VM localhost for diagnostics; use HTTPS for phones and the dashboard. Retrieve `LAB_KEY` privately from the VM's `.env` when connecting the lab. Container build and live Linode readiness must be verified on a Docker host before presenting the deployment as complete.

### Managed Postgres
1. In Cloud Manager (cloud.linode.com), go to **Databases → Create Database Cluster**.
2. Fill in the form:
   - **Label:** `followit-db`
   - **Engine:** PostgreSQL **18**. The app is tested on 17 and 18.
   - **Region:** Seattle (`us-sea`), the same region as the VM and the bucket.
   - **Plan:** Shared CPU, **Nanode 1 GB** (`g6-nanode-1`).
   - **Cluster size:** 1 node.
   - **Allowed IPs:** the VM's public IPv4. If the VM doesn't exist yet, add its IP later. Until an IP is on the list, every connection is refused.
3. When the status is **Active**, copy the host, port, username and password from **Connection Details**. Then set this in `.env`, URL-encoding any `@ : /` characters in the password:
   ```
   DATABASE_URL=postgresql://USERNAME:PASSWORD@HOST:PORT/defaultdb?sslmode=require
   ```
4. Check the connection from the VM:
   ```bash
   docker run --rm postgres:18 psql "$DATABASE_URL" -c "select version();"
   ```
   If the command hangs, the VM's IP isn't on the allow list. If you get an SSL error, `?sslmode=require` is missing. The app creates its tables on startup, so there's no SQL to run.

CLI alternative:
```bash
linode-cli databases engines --text | grep -i postgres    # exact engine id for v18
linode-cli databases postgresql-create --label followit-db --region us-sea --type g6-nanode-1 \
  --cluster_size 1 --engine postgresql/18 --allow_list <VM_IP>/32   # use the engine id printed above
```

## Local dev
```bash
python3 -m venv .venv && .venv/bin/pip install -r web/requirements.txt
cp .env.example .env && set -a && . ./.env && set +a      # point DATABASE_URL at any Postgres 17 or 18
.venv/bin/uvicorn web.app:app --reload --port 8000
.venv/bin/pytest                                           # API tests skip without Postgres
python -m web.dev.replay_events --reset                    # play the fixture lab cycle into /lab
FOLLOWIT_LIVE_URL=https://$DOMAIN .venv/bin/pytest -s web/tests/test_concurrency.py   # "1 success, 19 rejected"
```
The startup log says `using stubs` until `engine/` is present, then `using real engine`.

Never point `pytest` at the production database: the lab tests call `/v1/lab/reset`.

## Backup run (REPLAY)
```bash
python -m web.dev.record_events https://$DOMAIN backup_run.jsonl     # then run Red, Blue, Approve on /lab
python -m web.dev.replay_events https://$DOMAIN --file backup_run.jsonl --reset
```
Show it at `/lab?replay=1`, which displays the REPLAY banner. The Approve buttons in a replay are inert, because the replayed approval doesn't exist in the database.

## Known limits
- Rate limits and the event stream live in memory, so the app runs as one uvicorn worker on one VM.
- The client IP is the last `X-Forwarded-For` hop, and only when the socket peer is Caddy itself — taking the first hop would let a client pick its own rate-limit identity. Port 8000 is bound to VM localhost; public requests must pass through Caddy.
- The proof-of-work uses `crypto.subtle`, which only exists on HTTPS or localhost. Phones need the HTTPS URL.
- The scorer's feature bands start from motor-control literature and need recalibrating from the collected human traces. The gate is only as good as that sample (count by device in `/healthz`).
- "Non-dominant hand" stands in for less precise movement. It is not a model of disability, and the gate's device groups are coarse.
- Raw tester traces are deleted after 72 hours by an in-app hourly job. Organic and Red attempts never store raw trails, only features.
