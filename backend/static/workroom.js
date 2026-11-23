let csrfToken = null;
const $ = id => document.getElementById(id);
const money = cents => '$' + (Number(cents || 0) / 100).toFixed(2);

async function api(url, options = {}) {
  const headers = {'Content-Type':'application/json', ...(options.headers || {})};
  if (csrfToken && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(url, {...options, headers, credentials:'same-origin'});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}
function escapeText(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
const metric = (label, value) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;

async function load() {
  try {
    const me = await api('/api/me');
    csrfToken = me.csrf;
    if (!me.user || me.user.role === 'customer') { location.href='/'; return; }
    $('workUser').textContent = `${me.user.name} · ${me.user.role.replaceAll('_',' ')}`;
    $('ownerLink').hidden = me.user.role !== 'ceo';
    $('inventoryForm').hidden = !['operations_manager','ceo'].includes(me.user.role);
    const data = await api('/api/workroom');
    $('workMetrics').innerHTML = [
      metric('Active events', data.events.filter(e=>!['completed','cancelled'].includes(e.status)).length),
      metric('Needs attention', data.events.filter(e=>['inquiry','quoted'].includes(e.status)).length),
      metric('Sourcing tasks', data.sourcing.length),
      metric('Low-stock items', data.inventory.length)
    ].join('');
    $('sourcingEvent').innerHTML = '<option value="">General inventory / not assigned</option>' + data.events.map(e=>`<option value="${e.id}">${escapeText(e.title)} · ${escapeText(e.event_date)}</option>`).join('');
    const canAssign = ['operations_manager','ceo'].includes(data.role);
    $('eventRows').innerHTML = data.events.length ? data.events.map(event => {
      const assignment = canAssign ? `<select data-assign="${event.id}" class="small-button"><option value="unassigned" ${event.assigned_to?'':'selected'}>Unassigned</option>${data.team.map(person=>`<option value="${person.id}" ${event.assigned_to===person.id?'selected':''}>${escapeText(person.display_name||person.email)}</option>`).join('')}</select>` : '';
      return `<tr><td><b>${escapeText(event.title)}</b><br>${escapeText(event.event_type)}</td><td>${escapeText(event.event_date)}</td><td>${escapeText(event.venue||'—')}</td><td>${escapeText(event.customer_email||'')}</td><td>${money(event.estimate_cents)}<br>${Math.round((event.estimated_minutes||0)/60*10)/10} hr</td><td><span class="status ${event.status==='inquiry'?'wait':''}">${escapeText(event.status.replaceAll('_',' '))}</span></td><td><select data-status="${event.id}" class="small-button"><option value="">Update…</option>${['quoted','approved','booked','in_progress','completed','cancelled'].map(status=>`<option>${status}</option>`).join('')}</select>${assignment}</td></tr>`;
    }).join('') : '<tr><td colspan="7">No assigned events yet.</td></tr>';
    document.querySelectorAll('[data-status]').forEach(select => select.onchange = async () => {
      if (!select.value) return;
      try { await api(`/api/workroom/events/${select.dataset.status}`, {method:'PATCH',body:JSON.stringify({status:select.value})}); await load(); }
      catch (error) { showError(error.message); }
    });
    document.querySelectorAll('[data-assign]').forEach(select => select.onchange = async () => {
      try { await api(`/api/workroom/events/${select.dataset.assign}/assignment`, {method:'PATCH',body:JSON.stringify({staff_id:select.value})}); await load(); }
      catch (error) { showError(error.message); }
    });
    $('sourcingList').innerHTML = data.sourcing.length ? data.sourcing.map(item=>`<div class="data-item"><b>${escapeText(item.item_name)}</b><span>${item.quantity} · ${escapeText(item.status.replaceAll('_',' '))} · expected ${money(item.expected_cost_cents)} · due ${escapeText(item.due_date||'not scheduled')}</span></div>`).join('') : '<div class="data-item"><span>No sourcing tasks.</span></div>';
    $('inventoryList').innerHTML = data.inventory.length ? data.inventory.map(item=>`<div class="data-item"><b>${escapeText(item.name)}</b><span>${item.quantity_on_hand} ${escapeText(item.unit)} on hand · reorder at ${item.reorder_at}</span></div>`).join('') : '<div class="data-item"><span>No low-stock items.</span></div>';
  } catch (error) { showError(error.message); }
}

function showError(text) { $('workMessage').textContent=text; $('workMessage').classList.add('error'); }
$('sourcingForm').onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try { const result=await api('/api/workroom/sourcing',{method:'POST',body:JSON.stringify(Object.fromEntries(form))}); $('workMessage').textContent=result.message; event.currentTarget.reset(); await load(); }
  catch(error) { showError(error.message); }
};
$('inventoryForm').onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try { const result=await api('/api/workroom/inventory',{method:'POST',body:JSON.stringify(Object.fromEntries(form))}); $('workMessage').textContent=result.message; event.currentTarget.reset(); await load(); }
  catch(error) { showError(error.message); }
};
$('workLogout').onclick = async () => { try { await api('/api/auth/logout',{method:'POST',body:'{}'}); } finally { location.href='/'; } };
load();
