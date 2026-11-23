let csrfToken = null;
const $ = id => document.getElementById(id);
const money = cents => '$' + (Number(cents || 0) / 100).toFixed(2);

async function api(url, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (csrfToken && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}

function escapeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
const metric = (label, value) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;

function drawList(id, items, isStaff = false) {
  const target = $(id);
  if (!items.length) {
    target.innerHTML = '<div class="data-item"><span>Nothing saved here yet.</span></div>';
    return;
  }
  target.innerHTML = items.map(item => `<div class="data-item"><b>${escapeText(item.title)}</b><span>${escapeText(item.sub)}</span>${isStaff ? `<button class="small-button" data-staff-id="${item.id}" data-active="${item.active}">${item.active ? 'Pause access' : 'Restore access'}</button>` : ''}</div>`).join('');
}

async function load() {
  try {
    const me = await api('/api/me');
    csrfToken = me.csrf;
    if (!me.user || me.user.role !== 'ceo') { location.href = '/'; return; }
    $('ceoUser').textContent = `${me.user.name} · CEO`;
    const data = await api('/api/ceo/summary');
    $('ceoMetrics').innerHTML = [
      metric('Active events', data.metrics.active_events),
      metric('New inquiries', data.metrics.new_inquiries),
      metric('Open order requests', data.metrics.open_orders),
      metric('Staff accounts', data.metrics.staff)
    ].join('');
    $('ceoEvents').innerHTML = data.events.length ? data.events.map(event => `<tr><td>${escapeText(event.title)}</td><td>${escapeText(event.customer_email)}</td><td>${escapeText(event.event_date)}</td><td><span class="status ${event.status === 'inquiry' ? 'wait' : ''}">${escapeText(event.status.replaceAll('_',' '))}</span></td><td>${money(event.estimate_cents)}</td></tr>`).join('') : '<tr><td colspan="5">No inquiries yet.</td></tr>';
    $('ceoOrders').innerHTML = data.orders.length ? data.orders.map(order => `<tr><td>#${order.id}</td><td>${escapeText(order.customer_email)}</td><td>${escapeText(order.status.replaceAll('_',' '))}</td><td>${money(order.subtotal_cents)}</td><td>${escapeText(order.created_at)}</td></tr>`).join('') : '<tr><td colspan="5">No order requests yet.</td></tr>';
    drawList('recordsList', data.records.map(record => ({title:record.title,sub:`${record.record_type.replaceAll('_',' ')} · updated ${record.updated_at}`})));
    drawList('auditList', data.audit.map(row => ({title:row.action.replaceAll('_',' '),sub:`${row.actor_email || 'System'} · ${row.entity} ${row.entity_id || ''} · ${row.created_at}`})));
    const staff = await api('/api/ceo/staff');
    drawList('staffList', staff.staff.map(person => ({id:person.id,active:person.active,title:`${person.display_name} · ${person.role.replaceAll('_',' ')}`,sub:`${person.email} · ${person.email_verified ? 'verified' : 'not verified'} · ${person.active ? 'active' : 'paused'}`})), true);
  } catch (error) {
    $('ceoMessage').textContent = error.message;
    $('ceoMessage').classList.add('error');
  }
}

$('inviteForm').onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api('/api/ceo/staff-invites', {method:'POST',body:JSON.stringify(Object.fromEntries(form))});
    $('ceoMessage').textContent = data.development_invitation_link ? `${data.message} Local invitation: ${data.development_invitation_link}` : data.message;
    event.currentTarget.reset();
  } catch (error) { $('ceoMessage').textContent = error.message; $('ceoMessage').classList.add('error'); }
};

$('recordForm').onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api('/api/ceo/business-records', {method:'POST',body:JSON.stringify(Object.fromEntries(form))});
    $('ceoMessage').textContent = data.message;
    event.currentTarget.reset();
    await load();
  } catch (error) { $('ceoMessage').textContent = error.message; $('ceoMessage').classList.add('error'); }
};

$('staffList').addEventListener('click', async event => {
  const button = event.target.closest('[data-staff-id]');
  if (!button) return;
  try {
    await api(`/api/ceo/staff/${button.dataset.staffId}`, {method:'PATCH',body:JSON.stringify({active:button.dataset.active !== 'true'})});
    await load();
  } catch (error) { $('ceoMessage').textContent = error.message; $('ceoMessage').classList.add('error'); }
});

$('ceoLogout').onclick = async () => {
  try { await api('/api/auth/logout', {method:'POST',body:'{}'}); }
  finally { location.href = '/'; }
};

load();
