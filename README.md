# Follow It

**Follow a ball for five seconds. See the evidence behind every proposed defense update.**

[Try the live demo](https://172-238-40-140.sslip.io/) ·
[Explore the agent lab](https://172-238-40-140.sslip.io/lab) ·
[Collect research recordings](https://172-238-40-140.sslip.io/research)

## Why we built it

Imagine reaching the checkout for a concert you have been waiting to attend.
Your ticket is one click away, but first you must solve another image puzzle.
The person buying the ticket feels the friction; the operator still has to ask
whether the check is stopping automation and whom it might be excluding.

We built Follow It around two goals:

- **Make the interaction simple.** Try a short movement task in a complete
  ticket checkout, with a browser-check fallback for people who skip the motion.
- **Make security updates explainable.** Let AI agents test attacks and propose
  defenses, but measure the effect on recorded human attempts before an operator
  decides what goes live.

The result is a working research demo: movement verification, visible attack
testing, and reviewed updates in one flow. Removing image puzzles alone is not
our claim to novelty, and this is not yet a validated production CAPTCHA replacement.

## What you can try

| Experience | What happens |
| --- | --- |
| **Ticket checkout** — `/` or `/qr` | Follow the ball for five seconds, receive a verification pass, and reserve a demo ticket. No payment is collected. |
| **Agent lab** — `/lab` | Watch timestamped Red/Blue progress, compare proposed rules, and review approvals. Requires the private operator key. |
| **Research collection** — `/research` | Create participant invitations and QR codes for consented mouse, trackpad, and physical-phone recordings. |
| **Calibration tester** — `/?tester=1` or `/qr/tester` | Record consented calibration attempts. A research invitation is additionally required for model-training collection. |

The ball has a ring and symmetric glow, with no arrow or fading movement trail.
Its seeded path varies between challenges and covers a broad area. Skip,
unsuccessful movement, and reduced-motion flows offer a keyboard-accessible
proof-of-work browser check. That fallback adds computational cost; it does not
prove someone is human.

Passes last 120 seconds and are single-use, session-bound, and bound to the
reservation action. The server consumes them atomically when reserving a ticket.

## How the app and agents work

```text
Visitor → Caddy HTTPS → FastAPI → deterministic scorer → pass → reservation
                         ├── Managed PostgreSQL
                         └── private consented recording storage

Lab dashboard ← events ← FastAPI ← authenticated HTTP ← Strands worker
                                                           ↕
                                                   Akamai inference
```

**Checkout:** the server issues a challenge with a random seed, path/display
version, and scoring-policy snapshot. The browser samples pointer movement;
the server evaluates features such as lag, tracking error, and movement variation.
The feature-band score is a heuristic, not a probability of humanity. Hosted model
calls are outside the visitor request path.

**Red:** a Strands agent generates synthetic pointer samples and submits them to
the same scorer. It adjusts parameters such as delay, noise, and overshoot after
reading results. A Red “pass” means a simulated attack was accepted by the scorer;
it does not mean Red completed a separate test or moved a hidden browser mouse.

**Blue:** a separate Strands agent reads attack results and aggregate human
statistics, then proposes scoring changes. Raw human recordings are not sent
in model prompts.

**Fixed gate and operator:** the server compares the candidate with the baseline
on the same stored evidence. A candidate must admit fewer forgeries without
increasing rejected human recordings within represented device groups. Passing
this gate requests human review; it does not activate the rule. The server binds
approval to the evidence and checks it again before activation. Denial, model
failure, missing evidence, or changed evidence preserves the active policy.
Approved changes affect newly issued challenges.

**Research models:** Random Forest, CNN, and LSTM candidates have offline training,
evaluation, and optional shadow inference. They cannot issue passes or activate a
policy. The verified live release has no trained artifact loaded; fresh consented
data and participant-separated evaluation come first.

## Sponsor challenges and technologies

Our implemented sponsor integrations are **AWS Strands Agents SDK** and **Akamai**.

| Sponsor | How Follow It uses the technology |
| --- | --- |
| **AWS — Strands Agents SDK** | Red and Blue are real `Agent` instances using tools, lifecycle hooks, structured reports, and an approval interrupt. See [Red](engine/agents/red.py), [Blue](engine/agents/blue.py), and [hooks](engine/agents/hooks.py). Strands orchestrates the agents; their deployed inference provider is Akamai. Optional Bedrock support exists but is not claimed as a live-verified integration. |
| **Akamai** | Linode runs the app, Caddy HTTPS, and agent worker. Managed PostgreSQL stores application state. Red and Blue call the configured hosted `hackathon-chat` endpoint through [the provider adapter](engine/agents/providers.py). The underlying model is unconfirmed. |

DevRev, Flex, and USDA APIs/platforms are **not integrated** in this submission.
Akamai Object Storage is an optional storage backend; the current deployment uses
private VM disk. Bot Manager and EdgeWorkers are future pilot options, not current
dependencies.

## Run it locally

You can run checkout and the browser fallback **without model credentials**.
The Red/Blue loop additionally requires access to a configured inference provider.

### 1. Install the app

Use Python **3.12**, Git, and PostgreSQL **17 or 18**. Docker is a convenient way
to run the local database; Node.js is needed only for frontend tests.

```bash
git clone https://github.com/HackmidwestLMTV/bot-detection.git
cd bot-detection
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

```bash
# macOS / Linux
source .venv/bin/activate
cp .env.example .env
```

Then install dependencies:

```bash
python -m pip install -r web/requirements.txt -r engine/requirements.txt
```

### 2. Start a disposable database and configure the app

With Docker running, this creates a database accessible only from your computer:

```bash
docker run --name followit-local-db -e POSTGRES_USER=followit -e POSTGRES_PASSWORD=local-demo-only -e POSTGRES_DB=followit -p 127.0.0.1:5432:5432 -d postgres:18
```

On subsequent sessions, reuse it with `docker start followit-local-db`. You can
also supply your own local PostgreSQL database. Edit the copied `.env`:

```dotenv
DATABASE_URL=postgresql://followit:local-demo-only@127.0.0.1:5432/followit
PUBLIC_URL=http://localhost:8000
API_BASE=http://127.0.0.1:8000
LAB_KEY=replace-with-a-private-random-key
RESEARCH_RECORDINGS_DIR=
SHADOW_MODEL_DIR=
```

Generate a local operator key with `python -c "import secrets; print(secrets.token_hex(32))"`
and put it in `LAB_KEY`. Keep `.env` private. The database password above is a local
development example, not a production credential. The app creates its schema at startup.

### 3. Open checkout

```bash
python -m uvicorn web.app:app --env-file .env --reload --port 8000
```

Open [localhost:8000](http://localhost:8000). Follow the ball, or use the browser
check, then reserve a demo ticket. [The health endpoint](http://localhost:8000/healthz)
reports the engine, active policy, path/display versions, and current calibration counts.

### 4. Enable the Red/Blue lab

Add your provider settings to `.env`. The current deployment uses:

```dotenv
AKAMAI_BASE_URL=https://ws.akamai-workshops.com/v1
AKAMAI_API_KEY=your-authorized-provider-key
MODEL_ID=hackathon-chat
USE_BEDROCK=0
```

The workshop endpoint requires authorized access; cloning the repository does not
provide a key. In a second terminal, activate the same environment and run:

```bash
python -m engine.agents.smoke --check-config
python -m engine.worker --check-api
python -m engine.worker
```

The first two commands check configuration/API access without model calls.
Open [localhost:8000/lab](http://localhost:8000/lab), enter your `LAB_KEY`, and run
Red, then Blue. Fresh databases have no human evidence, so the gate should reject
activation until suitable recordings exist. Never add synthetic data as human
evidence just to make an approval appear.

### 5. Collect real recordings when ready

Set `RESEARCH_RECORDINGS_DIR` to an absolute, private, persistent directory outside
the repository and synced folders, then restart the app. Open `/research`, unlock
it with the operator key, and issue a separate participant invitation. Share the
invitation, never the lab key. Participants explicitly consent before collection.
Ordinary checkout does not store raw movement recordings.

Use the public HTTPS deployment for phones: `localhost` on a phone points to the
phone itself, and the browser fallback requires HTTPS or localhost. See the
[research guide](engine/ml/README.md) for retention, exporting, grouped evaluation,
and optional shadow models, or the [engine guide](engine/README.md) for a supervised
local calibration recorder.

## Reproduce the cloud architecture

1. Provision a Linode VM with Docker/Compose and a Managed PostgreSQL database.
   Allow database access from the VM and configure a TLS database URL.
2. Set a public domain, `PUBLIC_URL`, provider credentials, and a private lab key.
   Caddy serves HTTPS; expose 80/443, restrict SSH, and keep the app's diagnostic
   port private.
3. Run the app, Caddy, and one agent worker from a reviewed integrated revision.
   Keep consented recordings on persistent private storage and enable retention
   cleanup. Mount model artifacts read-only if shadow inference is later enabled.
4. Verify HTTPS checkout, database-backed health, worker API access, storage privacy,
   and expiration. Test against disposable infrastructure before replacing a release.

[Operations](engine/OPERATIONS.md) covers bootstrap, pinned releases, the existing
collection VM's paired rollout/rollback, and worker recovery. The generic deploy
scripts default to `main`; pin `RELEASE_REF` for a reproducible release.

## Verify the project

Use a **disposable PostgreSQL database** and set its `DATABASE_URL` plus a test
`LAB_KEY` in your terminal environment. Pytest does not load the web configuration
from `.env`; integration tests reset lab state. Never aim them at the live database.

```bash
python -m pip install -r engine/requirements-dev.txt -r engine/requirements-ml.txt
python -m pytest contracts engine/tests web/tests -q
node --test web/tests/*.test.*
```

Database checks skip if PostgreSQL is unavailable. The [CI workflow](.github/workflows/integration.yml)
requires the integrated suites, runs against disposable PostgreSQL, and builds the
app and worker images. The five-second release was checked with 286 Python tests
(two expected skips), 22 frontend tests, and browser flows covering checkout,
consent, touch emulation, fallback, reservations, and lab timestamps. Emulated
input is not a physical-phone or human-usability study.

## Demo evidence and next steps

The live rollout was verified on **October 11, 2026** with `roaming_v3` motion,
`plain_ring_5s_v2` presentation, private VM recording storage, and 72-hour cleanup.
Historical recordings remain separate; fresh device coverage starts as **untested**.
No trained research model was enabled. Earlier bounded Akamai runs exercised Red
and Blue; the latest rollout checked worker/API compatibility without new model calls.

For a walkthrough, show checkout → reservation → Red attacks → Blue proposal →
human-impact comparison → operator decision. If the gate rejects a proposal,
show the rejection. The [recorded backup](recordings/README.md) uses historical
synthetic human evidence: label it as replay and never present its counts as real
user results. Run replay only in a disposable demo environment.

Client telemetry is forgeable, the seeded path is public, and automation can solve
the fallback. Automated cursor input passed an earlier presentation; wider motion
does not establish resistance. Gate results describe the recorded sample, not a
guarantee of accessibility or unseen-user accuracy. The current rate limiter and
event stream also assume one app process.

Next: collect diverse consented mouse, trackpad, and phone traces; evaluate models
on separate participants and held-out attacks; then build an embeddable widget and
authenticated server verification API for a customer pilot.

Technical references: [API contract](contracts/CONTRACT.md),
[path geometry](contracts/ROAMING_PATH.md), [engine](engine/README.md),
[operations](engine/OPERATIONS.md), and [model research](engine/ml/README.md).
