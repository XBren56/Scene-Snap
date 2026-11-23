let csrfToken = null;
const $ = id => document.getElementById(id);
const statusBox = $('contentStatus');

function escapeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function setStatus(text, error = false) {
  statusBox.textContent = text;
  statusBox.classList.toggle('error', error);
}
async function api(url, options = {}) {
  const headers = { ...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...(options.headers || {}) };
  if (csrfToken && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(url, {...options, headers, credentials:'same-origin'});
  const data = await response.json().catch(() => ({error:'The server returned an unreadable response.'}));
  if (!response.ok) throw Error(data.error || 'The request could not be completed.');
  return data;
}
function displayPrice(cents) {
  return cents == null ? 'No starting price' : '$' + (Number(cents) / 100).toFixed(2);
}
function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}
function fillForm(form, item, fieldMap) {
  for (const [field, value] of Object.entries(fieldMap)) {
    const input = form.elements[field];
    if (!input) continue;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value ?? '';
  }
}
function updateFormTitle(type, editing) {
  const ids = {products:'productFormTitle',services:'serviceFormTitle',pages:'pageFormTitle'};
  const labels = {products:'product',services:'service',pages:'page'};
  $(ids[type]).textContent = editing ? 'Edit ' + labels[type] : (type === 'pages' ? 'Create a page' : 'Add a ' + labels[type]);
}
function renderProducts(items) {
  $('productList').innerHTML = items.map(p => '<article class="content-entry"><h3>' + escapeText(p.name) + '</h3><p>' + escapeText(p.category) + ' · ' + displayPrice(p.price_cents) + ' · ' + (p.active ? 'Shown in shop' : 'Hidden') + '</p><p>' + escapeText(p.description) + '</p><div class="content-entry-actions"><button data-edit-product="' + p.id + '">Edit</button><button data-toggle-product="' + p.id + '" data-active="' + p.active + '">' + (p.active ? 'Hide from shop' : 'Show in shop') + '</button></div></article>').join('') || '<p class="muted">No products yet.</p>';
  $('productList').querySelectorAll('[data-edit-product]').forEach(button => button.onclick = () => {
    const p = items.find(x => x.id === Number(button.dataset.editProduct));
    fillForm($('productForm'), p, {id:p.id,name:p.name,slug:p.slug,category:p.category,description:p.description,price:(p.price_cents/100).toFixed(2),emoji:p.emoji,image_url:p.image_url});
    $('productFormTitle').textContent = 'Edit product';
    $('productForm').scrollIntoView({behavior:'smooth',block:'start'});
  });
  $('productList').querySelectorAll('[data-toggle-product]').forEach(button => button.onclick = async () => {
    const p = items.find(x => x.id === Number(button.dataset.toggleProduct));
    try { await api('/api/ceo/products/' + p.id,{method:'PATCH',body:JSON.stringify({active:!p.active})}); await loadContent(); setStatus('Product visibility updated.'); }
    catch (error) { setStatus(error.message,true); }
  });
}
function renderServices(items) {
  $('serviceList').innerHTML = items.map(s => '<article class="content-entry"><h3>' + escapeText(s.name) + '</h3><p>' + displayPrice(s.price_cents) + ' · ' + (s.active ? 'Shown on site' : 'Hidden') + '</p><p>' + escapeText(s.description) + '</p><div class="content-entry-actions"><button data-edit-service="' + s.id + '">Edit</button><button data-toggle-service="' + s.id + '">' + (s.active ? 'Hide from site' : 'Show on site') + '</button></div></article>').join('') || '<p class="muted">No services yet.</p>';
  $('serviceList').querySelectorAll('[data-edit-service]').forEach(button => button.onclick = () => {
    const s = items.find(x => x.id === Number(button.dataset.editService));
    fillForm($('serviceForm'), s, {id:s.id,name:s.name,slug:s.slug,description:s.description,icon:s.icon,price:s.price_cents == null ? '' : (s.price_cents/100).toFixed(2),image_url:s.image_url});
    $('serviceFormTitle').textContent = 'Edit service';
    $('serviceForm').scrollIntoView({behavior:'smooth',block:'start'});
  });
  $('serviceList').querySelectorAll('[data-toggle-service]').forEach(button => button.onclick = async () => {
    const s = items.find(x => x.id === Number(button.dataset.toggleService));
    try { await api('/api/ceo/services/' + s.id,{method:'PATCH',body:JSON.stringify({active:!s.active})}); await loadContent(); setStatus('Service visibility updated.'); }
    catch (error) { setStatus(error.message,true); }
  });
}
function renderPages(items) {
  $('pageList').innerHTML = items.map(p => '<article class="content-entry"><h3>' + escapeText(p.title) + '</h3><p>/' + escapeText(p.slug) + ' · ' + (p.published ? 'Published' : 'Draft') + '</p><p>' + escapeText(p.summary) + '</p><div class="content-entry-actions"><button data-edit-page="' + p.id + '">Edit</button><button data-toggle-page="' + p.id + '">' + (p.published ? 'Unpublish' : 'Publish') + '</button>' + (p.published ? '<a class="copy-media" href="/page/' + encodeURIComponent(p.slug) + '" target="_blank" rel="noopener">View page</a>' : '') + '</div></article>').join('') || '<p class="muted">Create your first page here.</p>';
  $('pageList').querySelectorAll('[data-edit-page]').forEach(button => button.onclick = () => {
    const p = items.find(x => x.id === Number(button.dataset.editPage));
    fillForm($('pageForm'), p, {id:p.id,title:p.title,slug:p.slug,summary:p.summary,body:p.body,media_url:p.media_url,published:p.published});
    $('pageFormTitle').textContent = 'Edit page';
    $('pageForm').scrollIntoView({behavior:'smooth',block:'start'});
  });
  $('pageList').querySelectorAll('[data-toggle-page]').forEach(button => button.onclick = async () => {
    const p = items.find(x => x.id === Number(button.dataset.togglePage));
    try { await api('/api/ceo/pages/' + p.id,{method:'PATCH',body:JSON.stringify({published:!p.published})}); await loadContent(); setStatus('Page visibility updated.'); }
    catch (error) { setStatus(error.message,true); }
  });
}
function renderMedia(items) {
  $('mediaList').innerHTML = items.map(a => {
    const url = '/uploads/' + encodeURIComponent(a.stored_name);
    const preview = a.media_type === 'image' ? '<img class="media-preview" src="' + url + '" alt="">' : '<video class="media-preview" src="' + url + '" controls></video>';
    return '<article class="content-entry"><h3>' + escapeText(a.original_name) + '</h3>' + preview + '<p>' + a.media_type + ' · ' + Math.ceil(a.size_bytes/1024) + ' KB</p><p><code>' + escapeText(url) + '</code></p><div class="content-entry-actions"><button class="copy-media" data-copy-url="' + escapeText(url) + '">Copy media link</button></div></article>';
  }).join('') || '<p class="muted">Uploaded images and videos will appear here.</p>';
  $('mediaList').querySelectorAll('[data-copy-url]').forEach(button => button.onclick = async () => {
    try { await navigator.clipboard.writeText(button.dataset.copyUrl); setStatus('Relative media link copied. Paste it into a product, service, or page.'); }
    catch { setStatus('Copy this media link: ' + button.dataset.copyUrl); }
  });
}
function renderHomepage(settings) {
  fillForm($('homepageForm'),settings,{
    hero_kicker:settings.hero_kicker,hero_title:settings.hero_title,hero_emphasis:settings.hero_emphasis,
    hero_body:settings.hero_body,hero_note:settings.hero_note,shop_title:settings.shop_title,
    shop_intro:settings.shop_intro,services_title:settings.services_title,services_intro:settings.services_intro,
    inquiry_title:settings.inquiry_title,inquiry_intro:settings.inquiry_intro
  });
}
async function loadContent() {
  const result = await api('/api/ceo/content');
  renderProducts(result.products);
  renderServices(result.services);
  renderPages(result.pages);
  renderMedia(result.media);
  renderHomepage(result.settings);
}
function savePayload(form, kind) {
  const data = formData(form);
  if (kind === 'products') data.price = Number(data.price);
  if (kind === 'services') data.price = data.price || '';
  if (kind === 'pages') data.published = form.elements.published.checked;
  delete data.id;
  return data;
}
async function handleSave(event, kind) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  try {
    const url = id ? '/api/ceo/' + kind + '/' + id : '/api/ceo/' + kind;
    const result = await api(url,{method:id ? 'PATCH' : 'POST',body:JSON.stringify(savePayload(form,kind))});
    form.reset();
    form.elements.id.value = '';
    updateFormTitle(kind,false);
    await loadContent();
    setStatus(result.message || 'Saved.');
  } catch (error) { setStatus(error.message,true); }
}
document.querySelectorAll('.content-tab').forEach(button => button.onclick = () => {
  document.querySelectorAll('.content-tab').forEach(tab => tab.classList.toggle('active',tab === button));
  document.querySelectorAll('.content-panel').forEach(panel => panel.hidden = panel.id !== button.dataset.panel);
});
$('homepageForm').addEventListener('submit',async event=>{
  event.preventDefault();
  const data=Object.fromEntries(new FormData(event.currentTarget).entries());
  try { const result=await api('/api/ceo/site-settings',{method:'PATCH',body:JSON.stringify(data)});setStatus(result.message); }
  catch(error){setStatus(error.message,true);}
});
$('productForm').addEventListener('submit',event=>handleSave(event,'products'));
$('serviceForm').addEventListener('submit',event=>handleSave(event,'services'));
$('pageForm').addEventListener('submit',event=>handleSave(event,'pages'));
for (const [formId,kind] of [['productForm','products'],['serviceForm','services'],['pageForm','pages']]) {
  $(formId).addEventListener('reset',()=>setTimeout(()=>{ $(formId).elements.id.value=''; updateFormTitle(kind,false); },0));
}
$('mediaForm').addEventListener('submit',async event=>{
  event.preventDefault();
  const file=$('mediaForm').elements.file.files[0];
  if(!file)return;
  const data=new FormData();data.append('file',file);
  try { const result=await api('/api/ceo/media',{method:'POST',body:data});$('mediaForm').reset();await loadContent();setStatus(result.message+' Link: '+location.origin+result.asset.url); }
  catch(error){setStatus(error.message,true);}
});
document.querySelectorAll('.content-form').forEach(form=>form.addEventListener('input',()=>{if(statusBox.classList.contains('error'))setStatus('')}));
(async()=>{
  try {
    const me=await api('/api/me');
    if(!me.user||me.user.role!=='ceo'){location.href='/';return;}
    csrfToken=me.csrf;
    await loadContent();
  } catch(error) { setStatus(error.message,true); }
})();
