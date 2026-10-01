/* hub1z UI behaviours for the design preview: sidebar, grid/list toggle, quick filters, kanban drag and drop. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // Indian compact rupees: 1,25,000 -> ₹1.25L, 1,20,00,000 -> ₹1.2Cr
  function inrCompact(n) {
    if (n >= 10000000) return '₹' + (n / 10000000).toFixed(2).replace(/\.?0+$/, '') + 'Cr';
    if (n >= 100000) return '₹' + (n / 100000).toFixed(2).replace(/\.?0+$/, '') + 'L';
    return '₹' + Math.round(n).toLocaleString('en-IN');
  }
  window.hub1zInrCompact = inrCompact;

  // Mobile sidebar
  $$('[data-h-toggle="side"]').forEach(function (b) {
    b.addEventListener('click', function () { $('.h-side').classList.toggle('open'); });
  });
  document.addEventListener('click', function (e) {
    var side = $('.h-side.open');
    if (side && !side.contains(e.target) && !e.target.closest('[data-h-toggle="side"]')) side.classList.remove('open');
  });

  // Grid / list (or board / list) toggle
  $$('[data-view-root]').forEach(function (root) {
    $$('[data-set-view]', root).forEach(function (btn) {
      btn.addEventListener('click', function () {
        root.setAttribute('data-view', btn.getAttribute('data-set-view'));
        $$('[data-set-view]', root).forEach(function (b) { b.classList.toggle('active', b === btn); });
      });
    });
  });

  // Quick filters: a search box and pill buttons narrow every [data-item] under the same root
  $$('[data-filter-root]').forEach(function (root) {
    var input = $('[data-filter-input]', root);
    var pills = $$('[data-filter-pill]', root);
    var items = $$('[data-item]', root);
    var state = { q: '', key: null, value: null };
    function apply() {
      items.forEach(function (el) {
        var okText = !state.q || el.textContent.toLowerCase().indexOf(state.q) !== -1;
        var okPill = !state.key || state.value === 'all' || el.getAttribute('data-' + state.key) === state.value;
        el.style.display = okText && okPill ? '' : 'none';
      });
      var count = items.filter(function (el) { return el.style.display !== 'none' && el.hasAttribute('data-count'); }).length;
      var badge = $('[data-visible-count]', root);
      if (badge) badge.textContent = count;
    }
    if (input) input.addEventListener('input', function () { state.q = input.value.trim().toLowerCase(); apply(); });
    pills.forEach(function (p) {
      p.addEventListener('click', function () {
        var group = p.getAttribute('data-filter-pill');
        $$('[data-filter-pill="' + group + '"]', root).forEach(function (x) { x.classList.toggle('active', x === p); });
        state.key = group; state.value = p.getAttribute('data-value');
        apply();
      });
    });
  });

  // Kanban: drag a lead between stages, keeping each column's count and total in step
  var dragged = null;
  function refreshColumn(col) {
    var cards = $$('.h-lead', col).filter(function (c) { return c.style.display !== 'none'; });
    var total = cards.reduce(function (s, c) { return s + (parseFloat(c.getAttribute('data-value')) || 0); }, 0);
    var n = $('[data-col-count]', col); if (n) n.textContent = cards.length;
    var t = $('[data-col-total]', col); if (t) t.textContent = inrCompact(total) + ' / mo';
  }
  $$('.h-lead[draggable]').forEach(function (card) {
    card.addEventListener('dragstart', function (e) {
      dragged = card; card.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', card.id || 'lead'); } catch (x) { /* older browsers */ }
    });
    card.addEventListener('dragend', function () {
      card.classList.remove('dragging'); $$('.h-col').forEach(function (c) { c.classList.remove('over'); });
    });
  });
  function showToast(text) {
    var toast = $('#h-toast');
    if (!toast) return;
    $('.t-body', toast).textContent = text;
    window.bootstrap && window.bootstrap.Toast.getOrCreateInstance(toast, { delay: 2200 }).show();
  }
  // Real boards carry data-move-url on each card; the design preview has none and saves nothing.
  function saveMove(card, col, from) {
    var root = card.closest('[data-board-root]');
    var url = card.getAttribute('data-move-url');
    var label = col.getAttribute('data-label') || col.getAttribute('data-stage');
    if (!root || !url) { showToast('Moved to ' + label + ' (preview only, nothing is saved)'); return; }
    fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': root.getAttribute('data-csrf') || '' },
      body: JSON.stringify({ stage: col.getAttribute('data-stage') })
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(); }).then(function (d) {
      var due = $('[data-due]', card); if (due && d.due_text) due.textContent = d.due_text;
      showToast('Moved to ' + d.label);
    }).catch(function () {
      if (from) { $('.h-col-body', from).appendChild(card); refreshColumn(from); }
      refreshColumn(col);
      showToast('Could not save that move. Please try again.');
    });
  }
  $$('.h-col').forEach(function (col) {
    var body = $('.h-col-body', col);
    col.addEventListener('dragover', function (e) { e.preventDefault(); col.classList.add('over'); });
    col.addEventListener('dragleave', function (e) { if (!col.contains(e.relatedTarget)) col.classList.remove('over'); });
    col.addEventListener('drop', function (e) {
      e.preventDefault(); col.classList.remove('over');
      if (!dragged) return;
      var from = dragged.closest('.h-col');
      if (from === col) return;
      body.appendChild(dragged);
      refreshColumn(col); if (from) refreshColumn(from);
      saveMove(dragged, col, from);
    });
    refreshColumn(col);
  });

  // The "Add" forms in the preview only show a confirmation
  $$('[data-demo-form]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var modal = form.closest('.modal');
      if (modal && window.bootstrap) window.bootstrap.Modal.getInstance(modal).hide();
      var toast = $('#h-toast');
      if (toast) {
        $('.t-body', toast).textContent = 'Saved (preview only, nothing is stored)';
        window.bootstrap.Toast.getOrCreateInstance(toast, { delay: 2200 }).show();
      }
    });
  });

  // Copy buttons (UPI ID, Google Pay number)
  $$('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(btn.getAttribute('data-copy')).then(function () {
        var before = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check2"></i> Copied';
        setTimeout(function () { btn.innerHTML = before; }, 1600);
      });
    });
  });

  // Installable app: register the service worker and offer "Install app" where the browser supports it
  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
  }
  var installPrompt = null;
  var standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  var isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  if (standalone) {
    $$('[data-install-card]').forEach(function (el) { el.hidden = true; });
  } else if (isIos) {
    $$('[data-install-ios]').forEach(function (el) { el.hidden = false; });
    $$('[data-install-other]').forEach(function (el) { el.hidden = true; });
  }
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    installPrompt = e;
    $$('[data-install-app]').forEach(function (el) { el.hidden = false; });
    $$('[data-install-other]').forEach(function (el) { el.hidden = true; });
  });
  $$('[data-install-app]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      if (!installPrompt) return;
      installPrompt.prompt();
      installPrompt.userChoice.finally(function () {
        installPrompt = null;
        $$('[data-install-app]').forEach(function (el) { el.hidden = true; });
      });
    });
  });
  window.addEventListener('appinstalled', function () {
    $$('[data-install-card]').forEach(function (el) { el.hidden = true; });
  });
})();
