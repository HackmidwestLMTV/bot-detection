# Movement-model research

This is an offline comparison and optional shadow scorer. It cannot activate a
policy, issue a pass, or bypass the existing operator gate. Checkout still uses
the deterministic policy assigned when the challenge was issued. Red and Blue
still use Akamai `hackathon-chat` through Strands; RF/CNN/LSTM are separate models
trained locally. Raw research sequences are never included in agent prompts.

## What is measured

`target_response_v1` adds target-conditioned error, velocity alignment, lag-fit
improvement against unrelated paths, consistency across time windows, timing
quality, speed, acceleration/jerk proxies and turning statistics to the existing
five features. These describe browser pointer events, not measured physiology.
No universal tremor, entropy, fatigue, or mouse-vs-trackpad rule is assumed.

Sequences have 181 time steps at 60 Hz and eight channels: cursor velocity x/y,
target-relative error x/y, target velocity x/y, cursor speed, and a validity mask.
Coordinates are normalized by the logical 600×400 canvas. Native event times
remain in the signed recording; gaps over 100 ms and unsupported derivative
windows are masked, not filled with invented observations. At least 40 events,
2.5 seconds of coverage and 85% grid support are required for model evaluation.
Excluded trials appear in the report; insufficient coverage is not a bot label.

## Collect fresh evidence

The operator page at `/research` can create participant links and phone QR codes.
Enter the existing lab key there, choose **New person** for each new participant,
and retain the same pseudonymous ID when creating their next device/session invite.
The key is held only in page memory and sent in `X-Lab-Key`; never share it.
Only share the participant invitation. Its code travels in a URL fragment, which
is removed after the form is prefilled. Consent is always unchecked on entry.
Ask for 3–5 natural attempts per device, including misses, and refresh the coverage
table to confirm saved recordings. Calibration-only `/?tester=1` without an invite
does not create ML research evidence.

1. Keep one pseudonymous participant ID per person across devices and sessions.
   Have an operator supervise recruitment; an invite does **not** prove humanity.
2. Set a strong `LAB_KEY` (at least 16 characters). Configure **either** the
   existing private S3 settings or `RESEARCH_RECORDINGS_DIR` as an absolute,
   private persistent directory. This code does not enable any paid service.
   A Docker directory must be explicitly mounted; container-local data is not a
   durable recording store. On Windows protect the folder with a user-only ACL;
   POSIX creation requests mode 0700/0600. Keep recordings out of synced folders.
3. Use the collection CLI to issue an enrollment. Store the operator key in a
   private file outside the repository; never paste it into a URL or commit it.

```bash
python -m engine.ml.collect enroll research-data/invites --url https://YOUR-HOST \
  --key-file /private/operator-key --participant person_000001
```

The command saves a private `.invite` file, not the code in terminal output.
Give its code to that participant. They open `/?tester=1`, enter the code **first**,
select explicit model-training and recording consent, and select their device.
Invites expire in 24 hours, allow 30 challenges, and bind atomically to their first
browser session. Issue another invite with the **same** participant ID for a new
session. Expired or exhausted codes cannot issue new research challenges.

The browser reports mouse/trackpad from the participant's selection because
Pointer Events cannot distinguish them. Collect actual mouse, actual trackpad,
and physical phone touch; browser-emulated touch is not device evidence. Include
different people, browsers, hardware, repeated sessions, and users with differing
motor abilities. There is no established sufficient sample size here: the ten-person
minimum only prevents a trivial training smoke test from being called an experiment.

Research storage is separate from public `human_test` calibration. The legacy
local recorder and old JSON fixtures are deliberately **not** accepted as ML data.
Ordinary checkout never saves a raw sequence. A storage failure is shown to the
tester and does not change checkout's decision. `/v1/research/status` requires
`X-Lab-Key` and reports collection counts with missing devices marked `untested`.

## Export, retention and attacks

```bash
python -m engine.ml.collect export research-data/raw --url https://YOUR-HOST \
  --key-file /private/operator-key
python -m engine.ml.attacks research-data/raw --key-file /private/operator-key --groups 50
python -m engine.ml.collect cleanup research-data/raw
```

Only the header-authenticated export can read raw research storage. It rejects
changed/missing evidence and expired envelopes. Downloads keep their original
expiration; copying a file does not refresh consent or extend its lifetime.
Server reads reject at 72 hours, and the app's hourly janitor deletes expired
objects and orphan writes. Run `collect cleanup` at least hourly on **each export
machine** while it holds raw copies, and delete the workspace after the experiment.
The offline loader also rejects expired copies. The cleanup command must actually
be scheduled by the operator; it is not a background service installed by this kit.
Plan collection and training inside that 72-hour window. Do not change timestamps
or re-sign old data to keep it usable. Models and aggregate reports may be retained
under the distinct training consent; keep pseudonymous split lists private.

For the existing VM, `compose.research.yaml` mounts private recording storage at
`/root/followit/research/recordings` and a read-only model directory. From a reviewed
release under `/root/followit/releases/`, `bash deploy-research.sh` builds before
replacement, retains a rollback image, verifies storage expiry, and confirms the
active policy did not change. It also installs a host timer that removes expired
raw files each minute, independently of the app. Export access expires at 72 hours;
physical deletion follows on the next cleanup tick. No paid storage is enabled.
This first collection deployment requires `SHADOW_MODEL_DIR` empty: genuine-data
models are not available yet. The optional scorer remains shadow-only when a
reviewed genuine-data artifact is configured in a later deployment.

Synthetic regressions include open-loop waves, perfect following, lag plus noise,
and feedback control. The wave is an attack **family inspired by** the observed
cursor bypass; the live ordinary attempt was not saved, so this is not its exact
trajectory. These generators only create `bot` records. Future replay/transplant
tests must preserve the human source's `group_id` and `source_group`, including
all derived copies in the same partition. Signatures attest controlled ingestion,
not authenticity of forgeable client telemetry.

## Compare candidates

```bash
python -m venv .venv-ml
# Activate the environment using your platform's normal activation command.
python -m pip install -r engine/requirements-ml.txt
python -m engine.ml.train research-data/raw .ml-runs/experiment-001 \
  --key-file /private/operator-key --epochs 15
python -m engine.ml.train research-data/raw .ml-runs/unseen-wave-001 \
  --key-file /private/operator-key --epochs 15 --held-out-family open_loop_wave
```

RF uses 100 trees (depth ≤8, leaf size ≥2). CNN uses three 1D convolutions
(32/64/64 channels), masked pooling and a small dense head. LSTM uses 32 hidden
units, masked pooling and the same type of head. All receive the feature vector;
neural candidates additionally receive the sequence. Architectures and epochs are
fixed before auditing. The code trains on CPU with a fixed seed.

Hash-based 60/20/20 group assignments keep participants and synthetic source
groups apart, even when more sessions are added. Every partition needs both
classes and matching represented human device groups. Missing groups stop the
run. Normalization fits training rows only. A held-out attack family is removed
from training and validation; only its test-group rows are audited. This preserves
source separation without accidentally moving all related attacks into testing.

Thresholds are chosen on validation to block the most attacks while not increasing
human rejection counts within represented device groups and staying at or below
5% observed human rejection. The locked test report gives per-device human counts,
participant-cluster bootstrap intervals, attack-family acceptance, baseline
comparison and local CPU p95. Small/zero-error samples can give falsely narrow
bootstrap intervals. The sample gate asks for fewer accepted attacks and no rise
in human rejection counts. **A passing report is neither an accessibility
guarantee nor permission to deploy.** Do not tune against its test results;
subsequent tuning needs a new independent audit cohort. No risk score here is a
calibrated probability of humanity.

Each new run requires an empty directory and writes `report.json`, private
`partitions.json`, and `rf/`, `cnn/`, `lstm/` artifacts. Manifests fingerprint the
weights, feature/channel schema, preprocessing, path/display, threshold, dataset,
split and training versions. Artifacts contain JSON/NPZ numeric arrays, not pickle
or executable model code. Exported inference is checked against the training
library. Test fixtures require an explicit Python test-only flag; their artifacts
are rejected by normal loading and cannot be enabled in web shadow mode.

## Optional shadow use

Copy a reviewed artifact directory to a private, read-only mount, set
`SHADOW_MODEL_DIR` to that absolute directory, and restart the app. The loader
validates and caches an immutable snapshot until restart. Runtime inference uses
NumPy; PyTorch and scikit-learn are only required offline. Shadow results live in
`attempts.shadow_result` as scores, quality and a model fingerprint, never raw
points. Missing/incompatible models, inference errors and telemetry-write failures
preserve the deterministic result. Shadow inference adds CPU time, so measure on
the actual VM before enabling it widely. No hosted model request is added to checkout.

The existing feature-only approval gate cannot activate neural models. A later
activation phase must bind fresh sequence evidence, artifact/preprocessing hashes,
locked evaluations, explicit operator approval, challenge-time model snapshots,
rollback and server budgets. It is intentionally unavailable in this foundation.
Client forgery, public target paths, fallback abuse and independent adversarial
evaluation remain necessary work before production positioning.

Research basis and limitations: [BeCAPTCHA-Mouse](https://biometrics.eps.uam.es/fierrez/files/2022_PR_BeCAPTCHA-Mouse_Acien.pdf),
[mouse-dynamics sequence learning](https://www.researchgate.net/profile/Hongfeng-Niu/publication/354468819_Mouse_Dynamics_Based_Bot_Detection_Using_Sequence_Learning/links/6604089610ca86798715bbd3/Mouse-Dynamics-Based-Bot-Detection-Using-Sequence-Learning.pdf),
[adversarial synthesis](https://arxiv.org/abs/1905.11831),
and [Pointer Events](https://www.w3.org/TR/pointerevents3/).
