#!/usr/bin/env bash
# Pre-deploy check for Follow It. Run this BEFORE deploy.sh, on the VM:
#
#   bash ~/followit/scripts/preflight.sh
#   RELEASE_REF=<sha> bash ~/followit/scripts/preflight.sh      # also check that revision
#
# Read-only: it resolves names, opens TCP connections, reads .env and asks Docker
# for its configuration. It never writes to .env, never starts or stops a container
# and never prints a secret value. Safe to run repeatedly, and safe to run on the
# wrong machine -- it will simply report that this host is not a Follow It VM.
#
# Exit status: 0 when nothing fatal was found (warnings may remain), 1 otherwise.
set -uo pipefail
umask 077

FOLLOWIT_DIR="${FOLLOWIT_DIR:-$HOME/followit}"
ENV_FILE="${FOLLOWIT_ENV:-$FOLLOWIT_DIR/.env}"
release_ref="${RELEASE_REF:-origin/${BRANCH:-main}}"
engine_ref="${ENGINE_REF:-$release_ref}"
CONNECT_TIMEOUT="${PREFLIGHT_TIMEOUT:-8}"

passes=0
fails=0
warns=0

pass() { printf '[PASS] %s\n' "$*"; passes=$((passes + 1)); }
fail() { printf '[FAIL] %s\n' "$*"; fails=$((fails + 1)); }
warn() { printf '[WARN] %s\n' "$*"; warns=$((warns + 1)); }
info() { printf '[ ... ] %s\n' "$*"; }
hint() { printf '        -> %s\n' "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

# Read one key from .env without sourcing it (never echo the value).
env_value() {
  [ -f "$ENV_FILE" ] || return 1
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

# A python3 that can import the named module, if one exists on this host.
PY=""
for candidate in "${FOLLOWIT_PYTHON:-}" "$FOLLOWIT_DIR/.venv/bin/python" python3 python; do
  [ -n "$candidate" ] || continue
  if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then PY="$candidate"; break; fi
done
# Prefer an interpreter that has psycopg/boto3 (the project venv) when one exists.
py_with() {
  local module=$1 candidate
  for candidate in "${FOLLOWIT_PYTHON:-}" "$FOLLOWIT_DIR/.venv/bin/python" "$PWD/.venv/bin/python" python3 python; do
    [ -n "$candidate" ] || continue
    if { command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; } \
       && "$candidate" -c "import $module" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

compose_ok=0
daemon_ok=0

printf '==> Follow It deploy preflight\n'
printf '    host %s   dir %s   release_ref %s\n' "$(hostname 2>/dev/null || echo unknown)" "$FOLLOWIT_DIR" "$release_ref"
printf '    %s\n\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true)"

# ---------------------------------------------------------------- host sanity
printf -- '-- host --\n'
case "$(uname -s 2>/dev/null)" in
  Linux) pass "Linux host" ;;
  *) warn "this is $(uname -s 2>/dev/null || echo an unknown OS), not the Ubuntu VM" \
     && hint "ports/firewall/systemd checks below do not describe the deployment host" ;;
esac
if [ -d "$FOLLOWIT_DIR/.git" ]; then
  pass "checkout present at $FOLLOWIT_DIR"
else
  fail "no git checkout at $FOLLOWIT_DIR"
  hint "run vm_setup.sh first, or set FOLLOWIT_DIR to the checkout"
fi

# ----------------------------------------------------------------------- .env
printf -- '\n-- .env (%s) --\n' "$ENV_FILE"
if [ -s "$ENV_FILE" ]; then
  pass ".env exists and is non-empty"
  mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%OLp' "$ENV_FILE" 2>/dev/null || echo unknown)
  case "$mode" in
    600|400) pass ".env permissions $mode" ;;
    unknown) warn "could not read .env permissions" ;;
    *) warn ".env permissions are $mode; expected 600" && hint "chmod 600 $ENV_FILE" ;;
  esac
else
  fail ".env missing or empty at $ENV_FILE"
  hint "run vm_setup.sh, then fill DATABASE_URL, S3_KEY, S3_SECRET, AKAMAI_API_KEY"
fi

DATABASE_URL=$(env_value DATABASE_URL || true)
LAB_KEY=$(env_value LAB_KEY || true)
DOMAIN=$(env_value DOMAIN || true)
S3_ENDPOINT=$(env_value S3_ENDPOINT || true)
S3_BUCKET=$(env_value S3_BUCKET || true)
S3_KEY=$(env_value S3_KEY || true)
S3_SECRET=$(env_value S3_SECRET || true)
PUBLIC_URL=$(env_value PUBLIC_URL || true)
AKAMAI_API_KEY=$(env_value AKAMAI_API_KEY || true)
API_BASE=$(env_value API_BASE || true)
POW_BITS=$(env_value POW_BITS || true)

for key in DATABASE_URL LAB_KEY DOMAIN; do
  if [ -n "${!key}" ]; then
    pass "$key is set"
  else
    fail "$key is missing or empty in .env (names only; values are never printed)"
  fi
done

if [ -z "$LAB_KEY" ]; then
  :
elif [ "${#LAB_KEY}" -ge 16 ]; then
  pass "LAB_KEY length ${#LAB_KEY} (>= 16, research endpoints enabled)"
else
  fail "LAB_KEY is only ${#LAB_KEY} characters; /v1/research/* needs >= 16 (web/research.py)"
  hint "regenerate with: openssl rand -hex 32   (then paste into .env, do not echo it)"
fi
case "$LAB_KEY" in
  change-me-to-a-random-32-char-string|dev-lab-key)
    fail "LAB_KEY is still the .env.example placeholder" ;;
esac

if [ -n "$S3_KEY" ] && [ -n "$S3_SECRET" ]; then
  pass "S3_KEY and S3_SECRET are set"
else
  warn "S3_KEY/S3_SECRET not both set -- raw consented trail upload will be SILENTLY SKIPPED"
  hint "web/storage.py logs a warning and returns None; the site keeps working, the trails are lost"
  hint "do not promise testers a 72-hour retention window until this is configured"
fi
if [ -n "$PUBLIC_URL" ] && [ "$PUBLIC_URL" != "https://localhost" ]; then
  pass "PUBLIC_URL is set"
  if [ -n "$DOMAIN" ] && [ "$PUBLIC_URL" != "https://$DOMAIN" ]; then
    warn "PUBLIC_URL does not match https://DOMAIN -- /qr codes will point elsewhere"
  fi
else
  warn "PUBLIC_URL unset or still localhost -- /qr links fall back to the request URL"
fi
if [ -n "$AKAMAI_API_KEY" ]; then
  pass "AKAMAI_API_KEY is set"
else
  warn "AKAMAI_API_KEY is empty -- 'deploy.sh engine' will FAIL at 'engine.worker --check-api'"
  hint "the ticket page still works; Red/Blue cannot run without it"
fi
if [ -z "$API_BASE" ]; then
  warn "API_BASE unset; the worker container defaults to http://app:8000"
elif [ "$API_BASE" = "http://app:8000" ]; then
  pass "API_BASE points at the Compose service (http://app:8000)"
else
  warn "API_BASE is not http://app:8000 -- the worker reaches the app over the Compose network"
fi
case "$POW_BITS" in
  ''|18) info "POW_BITS ${POW_BITS:-unset (default 18)}; drop to 16 if a real phone stalls > 4 s" ;;
  *) info "POW_BITS=$POW_BITS (contract default is 18)" ;;
esac

# --------------------------------------------------------------------- domain
printf -- '\n-- domain and HTTPS --\n'
public_ip=""
if have curl; then
  for service in https://ifconfig.me https://api.ipify.org https://icanhazip.com; do
    public_ip=$(curl -fsS --max-time 6 "$service" 2>/dev/null | tr -d '[:space:]')
    case "$public_ip" in
      [0-9]*.[0-9]*.[0-9]*.[0-9]*) break ;;
      *) public_ip="" ;;
    esac
  done
fi
[ -n "$public_ip" ] && info "this host's public IPv4: $public_ip" \
  || warn "could not discover this host's public IPv4 (no egress?); DOMAIN/IP match unverified"

if [ -z "$DOMAIN" ]; then
  :
elif [ "$DOMAIN" = localhost ]; then
  fail "DOMAIN is still 'localhost' -- Caddy cannot get a certificate and phones get no HTTPS"
  hint "proof-of-work needs crypto.subtle, which browsers only expose on HTTPS or localhost"
  hint "set DOMAIN=<ip-with-dashes>.sslip.io in .env"
else
  sslip_ip=""
  case "$DOMAIN" in
    *.sslip.io)
      label=${DOMAIN%%.sslip.io}
      label=${label##*.}
      if [[ "$label" =~ ^([0-9]{1,3})-([0-9]{1,3})-([0-9]{1,3})-([0-9]{1,3})$ ]]; then
        sslip_ip="${label//-/.}"
        pass "DOMAIN is the expected sslip.io form (encodes $sslip_ip)"
      else
        warn "DOMAIN is under sslip.io but does not encode a dashed IPv4: $DOMAIN"
      fi ;;
    *) warn "DOMAIN=$DOMAIN is a custom hostname, not the <ip-with-dashes>.sslip.io form" \
       && hint "its A record must already point at this VM or Caddy's ACME challenge fails" ;;
  esac

  resolved=""
  if [ -n "$PY" ]; then
    resolved=$("$PY" - "$DOMAIN" <<'PY' 2>/dev/null
import socket, sys
try:
    infos = socket.getaddrinfo(sys.argv[1], None, socket.AF_INET)
except OSError:
    sys.exit(1)
print(" ".join(sorted({i[4][0] for i in infos})))
PY
)
  elif have dig; then
    resolved=$(dig +short +time=5 "$DOMAIN" A 2>/dev/null | tr '\n' ' ')
  fi
  resolved=$(printf '%s' "$resolved" | tr -s '[:space:]' ' ' | sed 's/ *$//')
  if [ -z "$resolved" ]; then
    fail "DOMAIN $DOMAIN does not resolve to an A record"
    hint "sslip.io needs outbound DNS; a custom name needs its own A record"
  else
    pass "DOMAIN resolves to: $resolved"
    expect="${sslip_ip:-$public_ip}"
    if [ -n "$public_ip" ] && [ -n "$sslip_ip" ] && [ "$sslip_ip" != "$public_ip" ]; then
      fail "DOMAIN encodes $sslip_ip but this host's public IP is $public_ip"
      hint "the .env was written on a different VM; fix DOMAIN and PUBLIC_URL before deploying"
    elif [ -n "$expect" ] && [[ " $resolved " != *" $expect "* ]]; then
      fail "DOMAIN resolves to $resolved, not $expect -- Caddy's ACME HTTP challenge will fail"
    elif [ -n "$expect" ]; then
      pass "DOMAIN resolves to this host ($expect)"
    else
      warn "could not compare DOMAIN's address with this host's public IP"
    fi
  fi
fi

# ------------------------------------------------------------------- postgres
printf -- '\n-- managed postgres --\n'
if [ -z "$DATABASE_URL" ]; then
  fail "no DATABASE_URL to test"
else
  db_host=""
  db_port=""
  if [ -n "$PY" ]; then
    # Parse only; the password never leaves this subshell.
    db_target=$(DBURL="$DATABASE_URL" "$PY" - <<'PY' 2>/dev/null
import os, sys
from urllib.parse import urlsplit
u = urlsplit(os.environ["DBURL"])
if not u.hostname:
    sys.exit(1)
print(u.hostname, u.port or 5432, "require" if "sslmode=require" in (u.query or "") else "default")
PY
)
    db_host=$(printf '%s' "$db_target" | awk '{print $1}')
    db_port=$(printf '%s' "$db_target" | awk '{print $2}')
    db_ssl=$(printf '%s' "$db_target" | awk '{print $3}')
  fi
  if [ -z "$db_host" ]; then
    fail "could not parse a host out of DATABASE_URL"
    hint "expected postgresql://USER:PASS@HOST:PORT/defaultdb?sslmode=require"
  else
    pass "DATABASE_URL parses (host $db_host port $db_port)"
    if [ "${db_ssl:-}" = require ]; then
      pass "DATABASE_URL carries ?sslmode=require"
    else
      warn "DATABASE_URL has no ?sslmode=require -- Managed Postgres will reject or warn"
    fi
    reach=$(DBHOST="$db_host" DBPORT="$db_port" TMO="$CONNECT_TIMEOUT" "$PY" - <<'PY' 2>/dev/null
import os, socket
host, port, tmo = os.environ["DBHOST"], int(os.environ["DBPORT"]), float(os.environ["TMO"])
try:
    s = socket.create_connection((host, port), timeout=tmo)
except socket.timeout:
    print("timeout")
except socket.gaierror:
    print("dns")
except ConnectionRefusedError:
    print("refused")
except OSError as e:
    print("error:%s" % e.__class__.__name__)
else:
    s.close()
    print("open")
PY
)
    case "${reach:-error}" in
      open) pass "TCP connect to $db_host:$db_port succeeded" ;;
      timeout)
        fail "TCP connect to $db_host:$db_port TIMED OUT after ${CONNECT_TIMEOUT}s"
        hint "THIS IS THE COMMON ONE: this host's IP is almost certainly not on the"
        hint "Managed Postgres allow list. Cloud Manager -> Databases -> followit-db ->"
        hint "Settings -> Manage Access -> add ${public_ip:-the VM public IPv4}/32."
        hint "A blocked connection HANGS; it does not return an error. deploy.sh would"
        hint "sit in 'up -d --wait' for 120s and then fail with no useful message." ;;
      refused)
        fail "TCP connect to $db_host:$db_port was REFUSED -- wrong host or port, not the allow list" ;;
      dns)
        fail "DATABASE_URL host $db_host does not resolve" ;;
      *)
        fail "TCP connect to $db_host:$db_port failed ($reach)" ;;
    esac

    if [ "${reach:-}" = open ]; then
      version=""
      how=""
      if have psql; then
        how="psql"
        version=$(PGCONNECT_TIMEOUT="$CONNECT_TIMEOUT" DBURL="$DATABASE_URL" \
          sh -c 'psql "$DBURL" -tAXc "show server_version" 2>&1' | tr -d '[:space:]')
      elif pgpy=$(py_with psycopg); then
        how="python/psycopg"
        version=$(DBURL="$DATABASE_URL" TMO="$CONNECT_TIMEOUT" "$pgpy" - <<'PY' 2>&1
import os, psycopg
try:
    with psycopg.connect(os.environ["DBURL"], connect_timeout=float(os.environ["TMO"])) as c:
        print(c.execute("show server_version").fetchone()[0])
except Exception as e:
    print("ERROR:%s" % e.__class__.__name__)
PY
)
      elif docker info >/dev/null 2>&1; then
        how="docker run postgres:18 psql (may pull the image once)"
        version=$(DBURL="$DATABASE_URL" docker run --rm -e DBURL -e PGCONNECT_TIMEOUT="$CONNECT_TIMEOUT" \
          postgres:18 sh -c 'psql "$DBURL" -tAXc "show server_version" 2>&1' | tr -d '[:space:]')
      fi
      case "$version" in
        "")
          warn "no Postgres client available; authentication and server version are UNVERIFIED"
          hint "the TCP check above only proves the allow list lets this host through" ;;
        18.*|18)
          pass "server_version $version via $how (expected 18)" ;;
        1[0-7].*|19.*|2[0-9].*)
          warn "server_version $version via $how; the app is tested on 17 and 18" ;;
        *)
          fail "could not read the server version via $how"
          case "$version" in
            *password*|*auth*|*Auth*|*OperationalError*)
              hint "that looks like an authentication failure: check the user and the"
              hint "URL-encoding of @ : / in the password inside DATABASE_URL" ;;
            *) hint "client output was suppressed to avoid printing credentials; re-run the"
               hint "client by hand on the VM if you need the raw error" ;;
          esac ;;
      esac
    fi
  fi
fi

# ---------------------------------------------------------- object storage
printf -- '\n-- object storage (raw consented trails) --\n'
if [ -z "$S3_KEY" ] || [ -z "$S3_SECRET" ] || [ -z "$S3_ENDPOINT" ] || [ -z "$S3_BUCKET" ]; then
  warn "object storage is NOT configured -- raw trail upload is skipped silently"
  hint "web/storage.py: configured() is false, put_trail() returns None and only logs"
  hint "features and scores still persist in Postgres; only raw traces are lost"
else
  s3_result=$(S3_ENDPOINT="$S3_ENDPOINT" S3_BUCKET="$S3_BUCKET" S3_KEY="$S3_KEY" \
    S3_SECRET="$S3_SECRET" TMO="$CONNECT_TIMEOUT" "$PY" - <<'PY' 2>/dev/null
# Signed list-objects against the configured bucket, using only the standard library.
# Prints a classification, never a credential.
import datetime, hashlib, hmac, os, socket, sys, urllib.error, urllib.request
from urllib.parse import urlsplit

endpoint = os.environ["S3_ENDPOINT"].rstrip("/")
bucket = os.environ["S3_BUCKET"]
key, secret = os.environ["S3_KEY"], os.environ["S3_SECRET"]
tmo = float(os.environ["TMO"])
parts = urlsplit(endpoint if "//" in endpoint else "https://" + endpoint)
host = parts.hostname or ""
if not host:
    print("badendpoint"); sys.exit(0)
try:
    socket.create_connection((host, parts.port or (80 if parts.scheme == "http" else 443)), timeout=tmo).close()
except socket.timeout:
    print("timeout"); sys.exit(0)
except OSError as e:
    print("unreachable:%s" % e.__class__.__name__); sys.exit(0)

region = host.split(".")[0] or "us-east-1"
now = datetime.datetime.now(datetime.timezone.utc)
stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
empty = hashlib.sha256(b"").hexdigest()
uri, query = "/" + bucket, "list-type=2&max-keys=1"
canonical_headers = "host:%s\nx-amz-content-sha256:%s\nx-amz-date:%s\n" % (host, empty, stamp)
signed_headers = "host;x-amz-content-sha256;x-amz-date"
canonical = "\n".join(["GET", uri, query, canonical_headers, signed_headers, empty])
scope = "%s/%s/s3/aws4_request" % (day, region)
to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])


def sign(k, m):
    return hmac.new(k, m.encode(), hashlib.sha256).digest()


k = sign(sign(sign(sign(("AWS4" + secret).encode(), day), region), "s3"), "aws4_request")
signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
request = urllib.request.Request(
    "%s://%s%s?%s" % (parts.scheme or "https", host, uri, query),
    headers={"Host": host, "x-amz-date": stamp, "x-amz-content-sha256": empty,
             "Authorization": "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
                              % (key, scope, signed_headers, signature)})
try:
    with urllib.request.urlopen(request, timeout=tmo) as r:
        print("ok:%d:%s" % (r.status, region))
except urllib.error.HTTPError as e:
    body = e.read(600).decode("utf-8", "replace")
    code = ""
    if "<Code>" in body:
        code = body.split("<Code>", 1)[1].split("</Code>", 1)[0]
    print("http:%d:%s:%s" % (e.code, code or "unknown", region))
except Exception as e:
    print("error:%s" % e.__class__.__name__)
PY
)
  case "${s3_result:-error}" in
    ok:*) pass "object storage reachable and the key can list $S3_BUCKET (${s3_result##*:})" ;;
    http:403:SignatureDoesNotMatch:*)
      fail "object storage rejected the signature -- S3_SECRET is wrong or truncated"
      hint "uploads will fail at runtime and raw trails will be dropped with only a log line" ;;
    http:403:InvalidAccessKeyId:*)
      fail "object storage does not know this S3_KEY -- wrong or revoked access key"
      hint "uploads will fail at runtime and raw trails will be dropped with only a log line" ;;
    http:403:*|http:401:*)
      fail "object storage returned 403/401 (${s3_result}) -- the key is not scoped to $S3_BUCKET"
      hint "uploads will fail at runtime and raw trails will be dropped with only a log line" ;;
    http:404:*|http:301:*|http:307:*)
      fail "bucket $S3_BUCKET not found at $S3_ENDPOINT (${s3_result})"
      hint "check the bucket name and that the endpoint region matches the bucket's region" ;;
    timeout) fail "object storage endpoint timed out after ${CONNECT_TIMEOUT}s" ;;
    badendpoint) fail "S3_ENDPOINT is not a usable URL" ;;
    *) warn "object storage check inconclusive (${s3_result}); treat raw upload as unproven" ;;
  esac
fi

# --------------------------------------------------------------------- docker
printf -- '\n-- docker and compose --\n'
if have docker; then
  pass "docker binary present ($(docker --version 2>/dev/null | head -n 1))"
  if docker compose version >/dev/null 2>&1; then
    compose_ok=1
    pass "compose plugin present ($(docker compose version --short 2>/dev/null || echo v2))"
  else
    fail "the 'docker compose' plugin is missing -- deploy.sh cannot run"
    hint "vm_setup.sh installs it via https://get.docker.com; re-run it"
  fi
  if docker info >/dev/null 2>&1; then
    daemon_ok=1
    pass "docker daemon reachable"
  else
    fail "docker daemon is not reachable"
    hint "systemctl start docker, then re-run this script"
  fi
else
  fail "docker is not installed -- run vm_setup.sh"
fi

compose_dir="$FOLLOWIT_DIR"
[ -f "$compose_dir/compose.yaml" ] || compose_dir="$PWD"
if [ "$compose_ok" = 1 ] && [ -f "$compose_dir/compose.yaml" ] && [ -s "$ENV_FILE" ]; then
  env_link=""
  if [ ! -e "$compose_dir/.env" ]; then
    env_link="$compose_dir/.env"
    ln -s "$ENV_FILE" "$env_link" 2>/dev/null || env_link=""
  fi
  if (cd "$compose_dir" && docker compose --profile engine config --quiet) 2>&1 | sed 's/^/        /'; then
    pass "docker compose --profile engine config is valid"
  else
    fail "compose.yaml did not validate (see the lines above)"
  fi
  if [ -f "$compose_dir/compose.research.yaml" ]; then
    if (cd "$compose_dir" && docker compose -f compose.yaml -f compose.research.yaml --profile engine config --quiet) 2>&1 | sed 's/^/        /'; then
      pass "compose.yaml + compose.research.yaml config is valid"
    else
      fail "the research overlay did not validate (see the lines above)"
    fi
  else
    info "compose.research.yaml not in $compose_dir; research overlay not checked"
  fi
  [ -n "$env_link" ] && rm -f -- "$env_link"
else
  warn "skipped 'docker compose config' (needs the compose plugin, compose.yaml and .env)"
fi

# ---------------------------------------------------------------------- ports
printf -- '\n-- ports 80/443 (Caddy is the only public edge) --\n'
listeners_for() {
  local port=$1
  if have ss; then
    ss -ltnpH 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {print $4, $NF}'
  elif have lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9, $1"/"$2}'
  elif have netstat; then
    netstat -an 2>/dev/null | awk -v p="\\.$port\$|:$port\$" '$1 ~ /tcp/ && $4 ~ p && /LISTEN/ {print $4, "unknown"}'
  fi
}
followit_caddy=""
if [ "$daemon_ok" = 1 ]; then
  followit_caddy=$(docker ps --filter label=com.docker.compose.project=followit \
    --filter label=com.docker.compose.service=caddy -q 2>/dev/null)
fi
for port in 80 443; do
  found=$(listeners_for "$port")
  if [ -z "$found" ]; then
    pass "port $port is free"
  elif [ -n "$followit_caddy" ] && printf '%s' "$found" | grep -qiE 'docker|caddy'; then
    warn "port $port is already held by the existing followit Caddy container"
    hint "a redeploy replaces it; this is expected on a second deploy"
  else
    fail "port $port is in use by something else: $(printf '%s' "$found" | tr '\n' ';')"
    hint "Caddy cannot bind it and 'up -d --wait' will fail; stop that service first"
  fi
done
if ! have ss && ! have lsof && ! have netstat; then
  warn "no ss/lsof/netstat available; port occupancy was not actually checked"
fi
if have ufw; then
  if ufw status 2>/dev/null | grep -q '8000.*DENY'; then
    pass "ufw denies inbound 8000"
  else
    warn "ufw does not show a DENY rule for 8000 (vm_setup.sh adds one)"
  fi
  hint "the Linode Cloud Firewall is separate: allow 22/80/443, remove any 8000 rule"
fi

# ------------------------------------------------------------------- git refs
printf -- '\n-- release revision --\n'
if [ -d "$FOLLOWIT_DIR/.git" ]; then
  git_c=(git -C "$FOLLOWIT_DIR")
  if "${git_c[@]}" fetch origin --quiet 2>/dev/null; then
    pass "git fetch origin succeeded"
  else
    warn "git fetch origin failed; ref resolution below uses the last fetched state"
  fi
  release_commit=$("${git_c[@]}" rev-parse --verify --end-of-options "$release_ref^{commit}" 2>/dev/null)
  if [ -n "$release_commit" ]; then
    pass "RELEASE_REF $release_ref -> $release_commit"
    for path in compose.yaml web/app.py Caddyfile; do
      if "${git_c[@]}" cat-file -e "$release_commit:$path" 2>/dev/null; then
        pass "$path present in that revision"
      else
        fail "$path is MISSING from $release_ref -- deploy.sh will refuse this revision"
      fi
    done
  else
    fail "RELEASE_REF $release_ref does not resolve"
    hint "git ls-remote origin main should print the integrated release branch; check RELEASE_REF if overridden"
  fi
  engine_commit=$("${git_c[@]}" rev-parse --verify --end-of-options "$engine_ref^{commit}" 2>/dev/null)
  if [ -z "$engine_commit" ]; then
    engine_commit=$("${git_c[@]}" rev-parse --verify --end-of-options "origin/$engine_ref^{commit}" 2>/dev/null)
    [ -n "$engine_commit" ] && engine_ref="origin/$engine_ref"
  fi
  if [ -n "$engine_commit" ]; then
    pass "engine ref $engine_ref -> $engine_commit"
    if "${git_c[@]}" cat-file -e "$engine_commit:engine/Dockerfile" 2>/dev/null; then
      pass "engine/Dockerfile present in that revision"
    else
      fail "engine/Dockerfile missing from $engine_ref -- 'deploy.sh engine' cannot build the worker"
      hint "without the real engine, /lab Approve and the gate return 503 by design"
    fi
  else
    fail "engine ref $engine_ref does not resolve (default is origin/main)"
  fi
else
  warn "no checkout at $FOLLOWIT_DIR; release revision not checked"
fi

# -------------------------------------------------------------------- summary
printf -- '\n==> %d passed, %d warnings, %d FAILED\n' "$passes" "$warns" "$fails"
if [ "$fails" -gt 0 ]; then
  printf 'Do NOT run deploy.sh yet. Fix every [FAIL] line above first.\n'
  exit 1
fi
if [ "$warns" -gt 0 ]; then
  printf 'No blockers. Read the [WARN] lines: they are things the demo will silently do without.\n'
else
  printf 'Clear. Next: RELEASE_REF=%s bash %s/deploy.sh engine\n' "${release_commit:-<sha>}" "$FOLLOWIT_DIR"
fi
exit 0
