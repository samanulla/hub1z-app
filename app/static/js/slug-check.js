// Live availability hint for inputs marked data-slug-check (optional data-exclude-id when editing).
(function () {
  document.querySelectorAll('input[data-slug-check]').forEach(function (input) {
    var note = document.createElement('div');
    note.className = 'form-text';
    note.setAttribute('aria-live', 'polite');
    input.insertAdjacentElement('afterend', note);
    var timer, seq = 0;
    function show(ok, text) {
      note.textContent = text || '';
      note.className = 'form-text ' + (ok === true ? 'text-success' : ok === false ? 'text-danger' : '');
      input.classList.toggle('is-valid', ok === true);
      input.classList.toggle('is-invalid', ok === false);
    }
    function check() {
      var value = input.value.trim().toLowerCase();
      if (!value) { show(null, ''); return; }
      var mine = ++seq;
      var url = input.dataset.slugCheck + '?slug=' + encodeURIComponent(value) +
        (input.dataset.excludeId ? '&exclude_id=' + encodeURIComponent(input.dataset.excludeId) : '');
      fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (mine === seq) show(d.available, d.message); })
        .catch(function () { if (mine === seq) show(null, ''); });
    }
    input.addEventListener('input', function () { show(null, 'Checking...'); clearTimeout(timer); timer = setTimeout(check, 350); });
    input.addEventListener('blur', check);
    if (input.value && !input.dataset.excludeId) check();
  });
})();
