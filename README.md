# Follow It

On a ticket checkout, one AI (Red) learns to fake a human hand, a second AI (Blue) tries to block it, and before any block goes live, a fixed gate shows how many real people it would lock out, and a person approves.

The full contract is in [contracts/CONTRACT.md](contracts/CONTRACT.md).

## Layout
| Folder | Owner | Branch |
|---|---|---|
| `contracts/` | shared, frozen; changes are made by Person 2 only and logged in `CHANGELOG.md` | `main` |
| `web/` + `Dockerfile`, `compose.yaml`, `Caddyfile`, `deploy.sh` | Person 1 | `p1-platform` |
| `engine/` | Person 2 | `p2-engine` |

## Local dev (Person 1)
```bash
python3 -m venv .venv && .venv/bin/pip install -r web/requirements.txt
cp .env.example .env                       # set DATABASE_URL to any Postgres 17
set -a; . ./.env; set +a
.venv/bin/uvicorn web.app:app --reload --port 8000   # http://localhost:8000, /healthz, /lab
.venv/bin/pytest                            # contracts/ + web/tests (API tests skip without Postgres)
```
The startup log says `using stubs` until `engine/` is present, then `using real engine`.

## Env vars
`DATABASE_URL`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_KEY`, `S3_SECRET`, `LAB_KEY`, `POW_BITS`, `API_BASE`, `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, `MODEL_ID`
