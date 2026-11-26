/* Real-time client: connects to Flask-SocketIO and updates the page without refreshing. */
(function () {
  const body = document.body;
  const csrf = body.dataset.csrf;

  // ---- image preview on report forms
  document.querySelectorAll('input[type=file][data-preview]').forEach(function (input) {
    input.addEventListener('change', function () {
      const img = document.querySelector(input.dataset.preview);
      const f = input.files && input.files[0];
      if (!f) { img.classList.add('d-none'); return; }
      img.src = URL.createObjectURL(f);
      img.classList.remove('d-none');
    });
  });

  // ---- dashboard search + filters (client side)
  const fSearch = document.getElementById('f-search');
  function applyFilters() {
    const q = (fSearch && fSearch.value || '').toLowerCase().trim();
    const kind = document.getElementById('f-kind').value;
    const cat = document.getElementById('f-cat').value;
    document.querySelectorAll('#recent-body tr').forEach(function (tr) {
      const ok = (!q || tr.dataset.text.indexOf(q) > -1) && (!kind || tr.dataset.kind === kind) && (!cat || tr.dataset.cat === cat);
      tr.classList.toggle('d-none', !ok);
    });
  }
  ['f-search', 'f-kind', 'f-cat'].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) { el.addEventListener('input', applyFilters); el.addEventListener('change', applyFilters); }
  });

  // ---- match score filter
  const minScore = document.getElementById('min-score');
  if (minScore) minScore.addEventListener('change', function () {
    document.querySelectorAll('.match').forEach(function (m) {
      m.classList.toggle('d-none', Number(m.dataset.score) < Number(minScore.value));
    });
  });

  // ---- notifications page: mark one as read when its link is clicked
  document.querySelectorAll('#notif-list .notif a').forEach(bindNotifClick);
  function bindNotifClick(a) {
    a.addEventListener('click', function () {
      const row = a.closest('.notif');
      const fd = new FormData(); fd.append('id', row.dataset.id);
      fetch('/notifications/read', { method: 'POST', body: fd, keepalive: true,
        headers: { 'X-CSRF-Token': csrf, 'X-Requested-With': 'fetch' } });
    });
  }

  // ---- helpers
  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function toast(message, link) {
    const box = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 text-bg-dark'; el.setAttribute('role', 'status');
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + esc(message) +
      (link ? ' <a class="link-warning" href="' + esc(link) + '">Open</a>' : '') +
      '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    box.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 7000 }); t.show();
    el.addEventListener('hidden.bs.toast', function () { el.remove(); });
  }
  function setBadge(n) {
    const b = document.getElementById('notif-badge'); if (!b) return;
    b.textContent = n; b.classList.toggle('d-none', !n);
  }

  // ---- admin tabs keep their place in the URL hash
  const tabs = document.querySelectorAll('#admin-tabs [data-hash]');
  if (tabs.length) {
    const open = function () {
      const h = location.hash.replace('#', '');
      tabs.forEach(function (t) { if (t.dataset.hash === h) bootstrap.Tab.getOrCreateInstance(t).show(); });
    };
    open();
    tabs.forEach(function (t) { t.addEventListener('shown.bs.tab', function () { history.replaceState(null, '', '#' + t.dataset.hash); }); });
  }

  if (body.dataset.loggedIn !== 'yes' || typeof io === 'undefined') return;

  // ---- Socket.IO events
  const socket = io();

  socket.on('new_notification', function (n) {
    setBadge(n.unread);
    toast(n.message, n.link);
    const list = document.getElementById('notif-list');
    if (list) {                                           // notifications page: add row instantly
      const row = document.createElement('div');
      row.className = 'notif unread'; row.dataset.id = n.id;
      row.innerHTML = '<a href="' + esc(n.link) + '">' + esc(n.message) + '</a><span class="small text-muted ms-auto">' + esc(n.created_at) + '</span>';
      list.prepend(row); bindNotifClick(row.querySelector('a'));
      const empty = document.getElementById('notif-empty'); if (empty) empty.classList.add('d-none');
    }
  });

  socket.on('stats_update', function (s) {                // dashboard + admin counters
    document.querySelectorAll('[data-stat]').forEach(function (el) {
      if (s[el.dataset.stat] !== undefined) el.textContent = s[el.dataset.stat];
    });
  });

  socket.on('new_report', function (r) {                  // recent-reports table gains a row
    const tbody = document.getElementById('recent-body'); if (!tbody) return;
    const tr = document.createElement('tr');
    tr.dataset.kind = r.kind; tr.dataset.cat = r.category; tr.dataset.text = (r.item_name + ' ' + r.location).toLowerCase();
    tr.innerHTML = '<td><span class="pill pill-' + esc(r.kind) + '">' + esc(r.kind) + '</span></td><td>' + esc(r.item_name) +
      '</td><td>' + esc(r.category) + '</td><td>' + esc(r.location) + '</td><td>' + esc(r.date) + '</td>';
    tbody.prepend(tr);
    while (tbody.children.length > 10) tbody.removeChild(tbody.lastChild);
    const empty = document.getElementById('recent-empty'); if (empty) empty.classList.add('d-none');
    if (fSearch) applyFilters();
  });

  socket.on('admin_alert', function (a) { toast(a.message, '/admin#claims'); });
})();
