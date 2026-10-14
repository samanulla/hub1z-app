/* Eye button on every password field: press to show what you typed, press again to hide it. */
(function () {
  'use strict';

  function enhance(input) {
    if (input.dataset.pwToggle) return;
    input.dataset.pwToggle = '1';
    var wrap = document.createElement('div');
    wrap.className = 'h-pw';
    wrap.style.position = 'relative';          // layout set here too, so the eye sits beside the field even if the stylesheet is stale
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'h-pw-toggle';
    button.style.cssText = 'position:absolute;top:0;right:0;height:100%;width:42px;display:flex;align-items:center;justify-content:center;border:0;background:transparent;padding:0;';
    button.setAttribute('aria-pressed', 'false');
    button.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i>';
    wrap.appendChild(button);

    function show(visible) {
      input.type = visible ? 'text' : 'password';
      button.setAttribute('aria-pressed', visible ? 'true' : 'false');
      button.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
      button.title = visible ? 'Hide password' : 'Show password';
      button.firstChild.className = 'bi ' + (visible ? 'bi-eye-slash' : 'bi-eye');
    }
    show(false);
    button.addEventListener('click', function () { show(input.type === 'password'); input.focus(); });
    // Never leave a password showing on a page the browser restores from its back/forward cache.
    window.addEventListener('pagehide', function () { show(false); });
  }

  function run() { document.querySelectorAll('input[type="password"]').forEach(enhance); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
