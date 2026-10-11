const $ = id => document.getElementById(id);
let inviteUrl = '';
const message = (text, error = false) => { $('status').textContent = text; $('status').classList.toggle('error', error); };
const newPerson = () => { $('participant').value = 'person_' + crypto.randomUUID().replaceAll('-', ''); };
newPerson();
$('new-person').addEventListener('click', newPerson);
async function api(path, body) {
  const key = $('operator-key').value.trim();
  if (!key) throw new Error('Enter your operator key first.');
  const response = await fetch('/v1/research/' + path, { method: body ? 'POST' : 'GET', cache: 'no-store',
    headers: { 'X-Lab-Key': key, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Check the key and server status.');
  return data;
}
async function refresh() {
  const data = await api('status');
  $('counts').replaceChildren();
  for (const [device, evidence] of Object.entries(data.coverage)) {
    const row = document.createElement('tr');
    for (const value of [device === 'touch' ? 'Phone / touch' : device, evidence.recordings, evidence.status]) {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    }
    $('counts').append(row);
  }
  $('model-status').textContent = data.shadow_configured
    ? 'A shadow artifact is configured. Its results do not control checkout; inspect evaluation before drawing conclusions.'
    : 'Awaiting genuine training data. No trained research model is loaded; the shadow-only pipeline is ready.';
  $('coverage').hidden = false;
  message(data.storage_configured ? 'Collection storage is configured. Invitations are ready.' : 'Collection storage is unavailable.', !data.storage_configured);
}
$('refresh').addEventListener('click', () => refresh().catch(error => message(error.message, true)));
$('create').addEventListener('click', async () => {
  $('create').disabled = true;
  try {
    const participant_id = $('participant').value.trim();
    if (!/^[A-Za-z0-9_-]{8,100}$/.test(participant_id)) throw new Error('Use an 8–100 character pseudonymous ID with letters, numbers, underscores, or hyphens.');
    const data = await api('enrollments', { participant_id, device: $('device').value });
    inviteUrl = data.tester_url;
    $('invite-url').href = inviteUrl; $('invite-url').textContent = inviteUrl;
    $('qr').src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(data.qr_svg);
    $('invite-person').textContent = `Participant ${data.participant_id} · ${$('device').selectedOptions[0].textContent} · expires in 24 hours`;
    $('invitation').hidden = false;
    message('Invitation created. Share it only with the intended participant.');
  } catch (error) { message(error.message, true); }
  finally { $('create').disabled = false; }
});
$('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(inviteUrl); message('Invitation link copied.'); }
  catch { message('Select and copy the invitation link above.', true); }
});
$('lock').addEventListener('click', () => {
  $('operator-key').value = ''; inviteUrl = ''; $('invitation').hidden = true; $('coverage').hidden = true;
  $('invite-url').removeAttribute('href'); $('invite-url').textContent = ''; $('qr').removeAttribute('src');
  message('Key and invitation cleared from this page.');
});
