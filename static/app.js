/* Meteroid frontend - subscribes to the JSON API in meteroid/api.py. */

const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  catalog: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
  metrics: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  coupons: '<path d="M4 6h16v4a2 2 0 0 0 0 4v4H4v-4a2 2 0 0 0 0-4z"/><path d="M12 8v8"/>',
  addons: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  features: '<path d="M12 3l2.6 6 6.4.5-4.9 4.2L17.6 20 12 16.6 6.4 20l1.5-6.3L3 9.5 9.4 9z"/>',
  billing: '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M2.5 10h19"/>',
  subscriptions: '<path d="M20 11A8 8 0 1 0 12 20"/><path d="M20 5v6h-6"/>',
  invoices: '<path d="M6 2h9l4 4v16H6z"/><path d="M9 12h7M9 16h7"/>',
  'credit-notes': '<path d="M4 6h13l3 3v9H4z"/><path d="M8 12h8"/>',
  customers: '<circle cx="9" cy="8" r="3.2"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M17 11h4M19 9v4"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.3 2.4c-.6.3-.8.7-.8 1.3v.3"/><path d="M12 17h.01"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/>',
  developers: '<path d="M8 6 2.5 12 8 18"/><path d="M16 6l5.5 6L16 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};

const NAV = [
  { key: 'home', label: 'Home' },
  { key: 'catalog', label: 'Product catalog' },
  { key: 'metrics', label: 'Metrics' },
  { key: 'coupons', label: 'Coupons' },
  { key: 'addons', label: 'Addons' },
  { key: 'features', label: 'Features' },
  { key: 'billing', label: 'Billing' },
  { key: 'subscriptions', label: 'Subscriptions' },
  { key: 'invoices', label: 'Invoices' },
  { key: 'credit-notes', label: 'Credit notes' },
  { key: 'customers', label: 'Customers' },
  { sep: true },
  { key: 'help', label: 'Help & Feedback' },
  { key: 'settings', label: 'Settings' },
  { key: 'developers', label: 'Developers' },
];

const state = { view: 'subscriptions', q: '' };

/* ------------------------------------------------------------------ utils */
const $ = (sel) => document.querySelector(sel);

const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function isoToDisplay(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}

function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.toggle('error', isError);
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 3200);
}

const titleCase = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);
const statusBadge = (status) => `<span class="badge ${esc(status)}">${esc(titleCase(status))}</span>`;
const initials = (name) => String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

/* ------------------------------------------------------------------- nav */
function renderNav() {
  $('#nav').innerHTML = NAV.map((item) => {
    if (item.sep) return '<div class="nav-sep"></div>';
    const active = item.key === state.view ? ' active' : '';
    return `<div class="nav-item${active}" data-view="${item.key}">
      <svg viewBox="0 0 24 24">${ICONS[item.key] || ''}</svg><span>${esc(item.label)}</span></div>`;
  }).join('');
  $('#nav').querySelectorAll('.nav-item').forEach((el) => {
    el.addEventListener('click', () => { state.view = el.dataset.view; state.q = ''; render(); });
  });
}

/* ----------------------------------------------------------- table render */
function subscriptionsTable(items, { clickable = true } = {}) {
  const rows = items.map((s) => `
    <tr class="${clickable ? 'clickable' : ''}" data-id="${s.id}">
      <td><div class="customer-cell"><span class="avatar">${esc(initials(s.customer))}</span>${esc(s.customer)}</div></td>
      <td>${esc(s.plan)}</td>
      <td class="num">${esc(s.version)}</td>
      <td class="num">${s.status === 'active' ? esc(s.mrr) : ''}</td>
      <td class="num">${esc(isoToDisplay(s.start_date))}</td>
      <td class="num">${s.end_date ? esc(isoToDisplay(s.end_date)) : '<span class="dash">&mdash;</span>'}</td>
      <td>${statusBadge(s.status)}</td>
      <td>${esc(s.currency)}</td>
    </tr>`).join('');

  return `<div class="table-wrap"><table>
    <thead><tr>
      <th>Customer</th><th>Plan</th><th>Version</th><th>MRR</th>
      <th>Start date</th><th>End date</th><th>Status</th><th>Currency</th>
    </tr></thead>
    <tbody>${rows || `<tr><td class="empty" colspan="8">No subscriptions found</td></tr>`}</tbody>
  </table></div>`;
}

function bindRowClicks(root = document) {
  root.querySelectorAll('tr.clickable').forEach((tr) => {
    tr.addEventListener('click', () => openSubscription(Number(tr.dataset.id)));
  });
}

/* ---------------------------------------------------------------- views */
async function viewSubscriptions() {
  const data = await api(`/api/subscriptions?q=${encodeURIComponent(state.q)}`);
  $('#page-count').textContent = `(${data.total})`;
  $('#topbar-actions').innerHTML =
    `<button class="btn-primary" id="new-sub">+ New subscription</button>`;
  $('#new-sub').addEventListener('click', openNewSubscriptionModal);
  $('#content').innerHTML = `
    <div class="search-row">
      <input class="search" id="search" placeholder="Search subscriptions" value="${esc(state.q)}">
      <span class="muted" id="result-count">${data.count} of ${data.total}</span>
    </div>
    ${subscriptionsTable(data.items)}`;
  const input = $('#search');
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = input.value; viewSubscriptions().catch((e) => toast(e.message, true)); }, 200);
  });
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  bindRowClicks();
}

async function viewHome() {
  const [summary, subs] = await Promise.all([api('/api/summary'), api('/api/subscriptions')]);
  $('#page-count').textContent = '';
  $('#topbar-actions').innerHTML = '';
  $('#content').innerHTML = `
    <div class="cards">
      <div class="card"><div class="label">Monthly recurring revenue</div>
        <div class="value accent">${esc(summary.mrr)}</div></div>
      <div class="card"><div class="label">Active subscriptions</div>
        <div class="value">${summary.active}</div></div>
      <div class="card"><div class="label">Pending subscriptions</div>
        <div class="value">${summary.pending}</div></div>
      <div class="card"><div class="label">Open invoices</div>
        <div class="value">${summary.open_invoices}</div></div>
    </div>
    <h2 class="section">Recent subscriptions</h2>
    ${subscriptionsTable(subs.items.slice(0, 5))}`;
  bindRowClicks();
}

async function viewCustomers() {
  const data = await api('/api/customers');
  $('#page-count').textContent = `(${data.items.length})`;
  $('#topbar-actions').innerHTML = `<button class="btn-primary" id="new-cust">+ New customer</button>`;
  $('#new-cust').addEventListener('click', openNewCustomerModal);
  const rows = data.items.map((c) => `
    <tr>
      <td><div class="customer-cell"><span class="avatar">${esc(initials(c.name))}</span>${esc(c.name)}</div></td>
      <td>${c.email ? esc(c.email) : '<span class="dash">&mdash;</span>'}</td>
      <td class="num">${esc(c.created_at)}</td>
      <td>${c.premium
        ? '<span class="badge active">Premium</span>'
        : '<span class="badge canceled">No access</span>'}</td>
    </tr>`).join('');
  $('#content').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Customer</th><th>Email</th><th>Created</th><th>Premium access</th></tr></thead>
    <tbody>${rows || '<tr><td class="empty" colspan="4">No customers yet</td></tr>'}</tbody></table></div>`;
}

async function viewCatalog() {
  const data = await api('/api/plans');
  $('#page-count').textContent = `(${data.items.length})`;
  $('#topbar-actions').innerHTML = `<button class="btn-primary" id="new-plan">+ New plan</button>`;
  $('#new-plan').addEventListener('click', openNewPlanModal);
  const rows = data.items.map((p) => `
    <tr>
      <td>${esc(p.name)}</td>
      <td class="num">${esc(p.version)}</td>
      <td class="num">${esc(p.amount)}</td>
      <td>${p.interval === 'year' ? 'per year' : 'per month'}</td>
      <td>${esc(p.currency)}</td>
      <td>${esc(p.created_at)}</td>
    </tr>`).join('');
  $('#content').innerHTML = `
    <p class="muted">Each plan name has versions. Publishing a plan that already exists creates the next
      version; existing subscriptions keep the version they signed up with.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Plan</th><th>Version</th><th>Amount</th><th>Billing</th><th>Currency</th><th>Published</th></tr></thead>
      <tbody>${rows || '<tr><td class="empty" colspan="6">No plans yet</td></tr>'}</tbody></table></div>`;
}

async function viewInvoices() {
  const data = await api('/api/invoices');
  $('#page-count').textContent = `(${data.items.length})`;
  $('#topbar-actions').innerHTML = '';
  const rows = data.items.map((i) => `
    <tr>
      <td class="mono">${esc(i.number)}</td>
      <td>${esc(i.customer_name)}</td>
      <td>${esc(i.plan_name)}</td>
      <td class="num">${esc(i.amount)}</td>
      <td class="num">${esc(isoToDisplay(i.period_start))} &ndash; ${esc(isoToDisplay(i.period_end))}</td>
      <td>${statusBadge(i.status)}</td>
    </tr>`).join('');
  $('#content').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Invoice</th><th>Customer</th><th>Plan</th><th>Amount</th><th>Period</th><th>Status</th></tr></thead>
    <tbody>${rows || '<tr><td class="empty" colspan="6">No invoices yet</td></tr>'}</tbody></table></div>`;
}

async function viewMetrics() {
  const [summary, subs] = await Promise.all([api('/api/summary'), api('/api/subscriptions')]);
  $('#page-count').textContent = '';
  $('#topbar-actions').innerHTML = '';

  const byPlan = new Map();
  subs.items.forEach((s) => {
    if (s.status !== 'active') return;
    const entry = byPlan.get(s.plan) || { plan: s.plan, count: 0, mrr: 0 };
    entry.count += 1;
    entry.mrr += s.mrr_cents;
    byPlan.set(s.plan, entry);
  });
  const rows = [...byPlan.values()]
    .sort((a, b) => b.mrr - a.mrr)
    .map((e) => `<tr><td>${esc(e.plan)}</td><td class="num">${e.count}</td>
      <td class="num">${esc(formatMoney(e.mrr))}</td></tr>`).join('');

  $('#content').innerHTML = `
    <div class="cards">
      <div class="card"><div class="label">MRR</div><div class="value accent">${esc(summary.mrr)}</div></div>
      <div class="card"><div class="label">Subscriptions</div><div class="value">${summary.subscriptions}</div></div>
      <div class="card"><div class="label">Active</div><div class="value">${summary.active}</div></div>
      <div class="card"><div class="label">Invoices</div><div class="value">${summary.invoices}</div></div>
    </div>
    <h2 class="section">MRR by plan</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Plan</th><th>Active subscriptions</th><th>MRR</th></tr></thead>
      <tbody>${rows || '<tr><td class="empty" colspan="3">No active subscriptions</td></tr>'}</tbody></table></div>`;
}

function placeholder(label) {
  $('#page-count').textContent = '';
  $('#topbar-actions').innerHTML = '';
  $('#content').innerHTML =
    `<p class="muted">${esc(label)} is not part of this build. The working pages are Home, Product catalog,
      Metrics, Subscriptions, Invoices and Customers.</p>`;
}

/* --------------------------------------------------------------- drawer */
async function openSubscription(id) {
  const s = await api(`/api/subscriptions/${id}`);
  const invoiceRows = (s.invoices || []).map((i) => `
    <tr><td class="mono">${esc(i.number)}</td><td class="num">${esc(i.amount)}</td>
    <td>${statusBadge(i.status)}</td></tr>`).join('');

  $('#drawer').innerHTML = `
    <div class="title-wrap"><h3>${esc(s.customer)}</h3>${statusBadge(s.status)}</div>
    <div class="sub">${esc(s.plan)} &middot; version ${esc(s.version)}</div>
    <dl class="kv">
      <dt>Monthly value</dt><dd>${s.status === 'active' ? esc(s.mrr) : '<span class="dash">&mdash;</span>'}</dd>
      <dt>Plan price</dt><dd>${esc(s.amount)} / ${s.interval === 'year' ? 'year' : 'month'}</dd>
      <dt>Currency</dt><dd>${esc(s.currency)}</dd>
      <dt>Start date</dt><dd>${esc(isoToDisplay(s.start_date))}</dd>
      <dt>End date</dt><dd>${s.end_date ? esc(isoToDisplay(s.end_date)) : '<span class="dash">&mdash;</span>'}</dd>
    </dl>
    <h2 class="section">Invoices</h2>
    <div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Amount</th><th>Status</th></tr></thead>
      <tbody>${invoiceRows || '<tr><td class="empty" colspan="3">No invoices</td></tr>'}</tbody></table></div>
    <div class="modal-actions">
      ${s.status === 'pending' ? '<button class="btn" id="activate">Activate</button>' : ''}
      ${s.status !== 'canceled' ? '<button class="btn btn-danger" id="cancel">Cancel subscription</button>' : ''}
      <button class="btn" id="close-drawer">Close</button>
    </div>`;

  $('#drawer').hidden = false;
  $('#drawer-scrim').hidden = false;

  const close = () => { $('#drawer').hidden = true; $('#drawer-scrim').hidden = true; };
  $('#close-drawer').addEventListener('click', close);
  $('#drawer-scrim').addEventListener('click', close, { once: true });

  const activate = $('#activate');
  if (activate) activate.addEventListener('click', async () => {
    try {
      await api(`/api/subscriptions/${s.id}/activate`, { method: 'POST', body: '{}' });
      toast(`Subscription ${s.id} activated`);
      close(); render();
    } catch (e) { toast(e.message, true); }
  });

  const cancel = $('#cancel');
  if (cancel) cancel.addEventListener('click', async () => {
    if (!confirm('Cancel this subscription? Open invoices are voided.')) return;
    try {
      await api(`/api/subscriptions/${s.id}/cancel`, { method: 'POST', body: '{}' });
      toast(`Subscription ${s.id} canceled`);
      close(); render();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------------------------------------------------------- modal */
function closeModal() { $('#modal-scrim').hidden = true; }

function showModal(html) {
  $('#modal').innerHTML = html;
  $('#modal-scrim').hidden = false;
  $('#modal-scrim').addEventListener('click', (e) => { if (e.target.id === 'modal-scrim') closeModal(); });
}

async function openNewSubscriptionModal() {
  const [customers, plans] = await Promise.all([api('/api/customers'), api('/api/plans')]);
  if (!customers.items.length) { toast('Create a customer first', true); return; }
  if (!plans.items.length) { toast('Create a plan first', true); return; }
  const today = new Date().toISOString().slice(0, 10);
  showModal(`
    <h3>New subscription</h3>
    <form id="form">
      <div class="field"><label for="customer">Customer</label>
        <select id="customer">${customers.items.map((c) =>
          `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>
      <div class="field"><label for="plan">Plan</label>
        <select id="plan">${plans.items.map((p) =>
          `<option value="${p.id}">${esc(p.name)} v${p.version} &middot; ${esc(p.amount)}</option>`).join('')}</select></div>
      <div class="field"><label for="start">Start date</label>
        <input id="start" type="date" value="${today}"></div>
      <div class="field"><label for="status">Status</label>
        <select id="status"><option value="active">Active</option><option value="pending">Pending</option></select></div>
      <div class="modal-actions">
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn-primary">Create subscription</button>
      </div>
    </form>`);
  $('#cancel-btn').addEventListener('click', closeModal);
  $('#form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api('/api/subscriptions', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: Number($('#customer').value),
          plan_id: Number($('#plan').value),
          start_date: $('#start').value,
          status: $('#status').value,
        }),
      });
      closeModal(); toast('Subscription created'); render();
    } catch (err) { toast(err.message, true); }
  });
}

function openNewCustomerModal() {
  showModal(`
    <h3>New customer</h3>
    <form id="form">
      <div class="field"><label for="name">Name</label><input id="name" required></div>
      <div class="field"><label for="email">Billing email</label><input id="email" type="email"></div>
      <div class="modal-actions">
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn-primary">Create customer</button>
      </div>
    </form>`);
  $('#cancel-btn').addEventListener('click', closeModal);
  $('#form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api('/api/customers', {
        method: 'POST',
        body: JSON.stringify({ name: $('#name').value, email: $('#email').value }),
      });
      closeModal(); toast('Customer created'); render();
    } catch (err) { toast(err.message, true); }
  });
}

function openNewPlanModal() {
  showModal(`
    <h3>New plan</h3>
    <form id="form">
      <div class="field"><label for="name">Plan name</label><input id="name" required></div>
      <div class="field"><label for="amount">Price</label><input id="amount" placeholder="49.00" required></div>
      <div class="field"><label for="currency">Currency</label>
        <select id="currency"><option>EUR</option><option>USD</option><option>GBP</option></select></div>
      <div class="field"><label for="interval">Billing period</label>
        <select id="interval"><option value="month">Monthly</option><option value="year">Yearly</option></select></div>
      <p class="muted">Using an existing name publishes a new version of that plan.</p>
      <div class="modal-actions">
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn-primary">Publish plan</button>
      </div>
    </form>`);
  $('#cancel-btn').addEventListener('click', closeModal);
  $('#form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const plan = await api('/api/plans', {
        method: 'POST',
        body: JSON.stringify({
          name: $('#name').value,
          amount: $('#amount').value,
          currency: $('#currency').value,
          interval: $('#interval').value,
        }),
      });
      closeModal(); toast(`${plan.name} v${plan.version} published`); render();
    } catch (err) { toast(err.message, true); }
  });
}

/* ---------------------------------------------------------------- money */
function formatMoney(cents, currency = 'EUR') {
  const symbols = { EUR: '\u20ac', USD: '$', GBP: '\u00a3', JPY: '\u00a5' };
  const body = (cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return symbols[currency] ? symbols[currency] + body : `${body} ${currency}`;
}

/* --------------------------------------------------------------- render */
async function render() {
  renderNav();
  const label = (NAV.find((n) => n.key === state.view) || {}).label || '';
  $('#page-title').textContent = label;
  try {
    if (state.view === 'subscriptions') return await viewSubscriptions();
    if (state.view === 'home') return await viewHome();
    if (state.view === 'customers') return await viewCustomers();
    if (state.view === 'catalog') return await viewCatalog();
    if (state.view === 'invoices') return await viewInvoices();
    if (state.view === 'metrics') return await viewMetrics();
    return placeholder(label);
  } catch (err) {
    $('#content').innerHTML = `<p class="muted">${esc(err.message)}</p>`;
  }
}

document.addEventListener('DOMContentLoaded', render);
