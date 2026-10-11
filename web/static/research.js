const $ = id => document.getElementById(id);
// Phase C's starting checkpoint: ten consented recordings with every device represented.
const TARGET = 10;
const LABELS = { mouse: 'Mouse', trackpad: 'Trackpad', touch: 'Phone / touch' };
const SAY = {
  mouse: 'Open this on your laptop, then follow the ball with your mouse for five seconds.',
  trackpad: 'Open this on your laptop and use the trackpad — follow the ball for five seconds.',
  touch: 'Scan this, follow the ball with your finger for five seconds.',
};
const KEY_STORE = 'followit_operator_key';
let inviteUrl = '';
let poll = null;
let counts = null;          // last seen per-device counts, for the "just landed" flash
let landedFade = null;      // timer that clears a stale "just landed" message
const message = (text, error = false) => { $('status').textContent = text; $('status').classList.toggle('error', error); };
const newPerson = () => { $('participant').value = 'person_' + crypto.randomUUID().replaceAll('-', ''); };
newPerson();
$('new-person').addEventListener('click', newPerson);

function key() { return $('operator-key').value.trim(); }
async function api(path, body) {
  if (!key()) throw new Error('Enter your operator key first.');
  const response = await fetch('/v1/research/' + path, { method: body ? 'POST' : 'GET', cache: 'no-store',
    headers: { 'X-Lab-Key': key(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Check the key and server status.');
  return data;
}

// ---- progress ----
function renderCoverage(data) {
  const fresh = Object.fromEntries(Object.entries(data.coverage).map(([d, e]) => [d, e.recordings]));
  const total = Object.values(fresh).reduce((a, b) => a + b, 0);
  $('total').textContent = total;
  $('chips').replaceChildren(...Object.entries(data.coverage).map(([device, evidence]) => {
    const li = document.createElement('li');
    li.className = evidence.recordings ? 'done' : 'missing';
    const name = document.createElement('b'); name.textContent = LABELS[device] || device;
    const n = document.createElement('i'); n.textContent = evidence.recordings;
    const note = document.createElement('em');
    note.textContent = evidence.recordings ? evidence.status : 'nothing collected yet';
    li.append(name, n, note);
    return li;
  }));
  const missing = Object.keys(data.coverage).filter(d => !fresh[d]).map(d => LABELS[d] || d);
  const short = Math.max(0, TARGET - total);
  $('need').textContent = !short && !missing.length
    ? `${total} consented recordings saved here, every device represented. That is a training-consent milestone, not Phase C’s calibration checkpoint — check the local recorder trace count below for that. Keep going if people are willing.`
    : [short ? `${short} more recording${short === 1 ? '' : 's'} needed` : 'Count reached',
       missing.length ? `${missing.join(' and ')} still missing` : 'every device represented'].join(' · ') + '.';
  // A count that went up while the operator was standing next to the volunteer is the
  // only trustworthy confirmation that a recording actually landed. The flash fades on
  // its own so an old gain can never be mistaken for the save that just happened.
  if (counts) {
    const gained = Object.entries(fresh).filter(([d, n]) => n > (counts[d] ?? 0));
    if (gained.length) {
      clearTimeout(landedFade);
      $('landed').textContent = '+ ' + gained.map(([d, n]) => `${n - (counts[d] ?? 0)} ${LABELS[d] || d}`).join(', ')
        + ' just landed · ' + new Date().toLocaleTimeString();
      landedFade = setTimeout(() => { $('landed').textContent = ''; }, 12000);
    }
  }
  counts = fresh;
  $('model-status').textContent = data.shadow_configured
    ? 'A shadow artifact is configured. Its results do not control checkout; inspect evaluation before drawing conclusions.'
    : 'Awaiting genuine training data. No trained research model is loaded; the shadow-only pipeline is ready.';
  $('freshness').textContent = 'updated ' + new Date().toLocaleTimeString();
}

async function refresh() {
  const data = await api('status');
  renderCoverage(data);
  message(data.storage_configured ? 'Watching for recordings. Invitations are ready.' : 'Collection storage is unavailable: nothing can be saved. Set RESEARCH_RECORDINGS_DIR or S3 before inviting anyone.', !data.storage_configured);
  return data;
}

function watch() {
  clearInterval(poll);
  poll = setInterval(() => {
    if (document.hidden || !key()) return;
    refresh().catch(error => { clearInterval(poll); poll = null; message(error.message + ' Progress updates stopped.', true); });
  }, 5000);
}
// Polling pauses in a background tab, so catch up the moment the operator looks again.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && poll && key()) refresh().catch(error => message(error.message, true));
});

// Unauthenticated: proves phones are reaching this app even before anything is saved.
async function health() {
  try {
    const response = await fetch('/healthz', { cache: 'no-store' });
    const data = await response.json();
    const traces = data.human_traces || {};
    const byDevice = Object.entries(traces).filter(([k]) => k !== 'total')
      .map(([k, n]) => `${n} ${LABELS[k] || k}`).join(', ');
    $('attempts').textContent = traces.total
      ? `${traces.total} tester attempt${traces.total === 1 ? '' : 's'} scored${byDevice ? ' (' + byDevice + ')' : ''}.`
      : 'No tester attempts have reached this server yet.';
    $('versions').textContent = `${data.path_version} / ${data.presentation_version}`;
    if (data.excluded_legacy_human_traces) {
      $('attempts').textContent += ` ${data.excluded_legacy_human_traces} older attempt(s) are excluded: different path or display version.`;
    }
  } catch { $('attempts').textContent = 'Could not read /healthz; this app may be restarting.'; }
}
health();
setInterval(health, 15000);

$('refresh').addEventListener('click', () => {
  if ($('remember').checked && key()) { try { sessionStorage.setItem(KEY_STORE, key()); } catch { /* ignore */ } }
  refresh().then(watch).catch(error => message(error.message, true));
});

// ---- invitations ----
function renderInvite(data, device) {
  inviteUrl = data.tester_url;
  $('invite-url').href = inviteUrl; $('invite-url').textContent = inviteUrl;
  $('qr').src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(data.qr_svg);
  $('invite-person').textContent = `${LABELS[device] || device} · participant ${data.participant_id} · expires in 24 hours`;
  $('say-device').textContent = SAY[device] || SAY.mouse;
  $('invitation').hidden = false;
  $('invitation').scrollIntoView({ block: 'start', behavior: 'smooth' });
}

async function create(participant_id, device) {
  if (!/^[A-Za-z0-9_-]{8,100}$/.test(participant_id)) throw new Error('Use an 8–100 character pseudonymous ID with letters, numbers, underscores, or hyphens.');
  renderInvite(await api('enrollments', { participant_id, device }), device);
  message('Invitation ready. Show the QR code or send the link to this one person.');
  if (!poll) refresh().then(watch).catch(() => { /* status already shown */ });
}

for (const button of document.querySelectorAll('.quick button')) {
  button.addEventListener('click', async () => {
    const device = button.dataset.device;
    button.disabled = true;
    try {
      newPerson();                       // a fresh pseudonym per volunteer, nothing to type
      $('device').value = device;
      await create($('participant').value, device);
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });
}

$('create').addEventListener('click', async () => {
  $('create').disabled = true;
  try { await create($('participant').value.trim(), $('device').value); }
  catch (error) { message(error.message, true); }
  finally { $('create').disabled = false; }
});

const copy = async (text, ok) => {
  try { await navigator.clipboard.writeText(text); message(ok); }
  catch { message('Copying was blocked. Select the text and copy it by hand.', true); }
};
$('copy').addEventListener('click', () => copy(inviteUrl, 'Invitation link copied.'));
$('copy-count').addEventListener('click', () => copy($('count-cmd').textContent, 'Trace-counting command copied. Run it on the machine the recorder is running on.'));

$('lock').addEventListener('click', () => {
  clearInterval(poll); poll = null; counts = null; clearTimeout(landedFade); landedFade = null;
  try { sessionStorage.removeItem(KEY_STORE); } catch { /* ignore */ }
  $('operator-key').value = ''; $('remember').checked = false; inviteUrl = ''; $('invitation').hidden = true;
  $('invite-url').removeAttribute('href'); $('invite-url').textContent = ''; $('qr').removeAttribute('src');
  $('chips').replaceChildren(); $('total').textContent = '–'; $('landed').textContent = ''; $('freshness').textContent = '';
  $('need').textContent = 'Unlock with your operator key to see what is still missing.';
  $('model-status').textContent = '';
  message('Key and invitation cleared from this page.');
});

// A reload mid-session should not cost the operator their key, but only if they asked.
try {
  const saved = sessionStorage.getItem(KEY_STORE);
  if (saved) {
    $('operator-key').value = saved; $('remember').checked = true;
    refresh().then(watch).catch(error => message(error.message, true));
  }
} catch { /* storage unavailable; the key simply is not remembered */ }
