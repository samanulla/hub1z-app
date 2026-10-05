(function () {
  'use strict';
  const root = document.querySelector('[data-notification-center]');
  if (!root) return;
  const count = root.querySelector('[data-notification-count]');
  const bell = root.querySelector('[data-notification-bell]');
  async function refresh() {
    if (document.hidden) return;
    try {
      const response = await fetch(root.dataset.summaryUrl, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
      if (!response.ok || !response.headers.get('content-type').includes('application/json')) return;
      const data = await response.json();
      count.hidden = !data.unread;
      count.textContent = data.unread > 99 ? '99+' : String(data.unread);
      bell.setAttribute('aria-label', 'Notifications, ' + data.unread + ' unread');
      const items = root.querySelector('[data-notification-items]');
      items.replaceChildren();
      for (const item of data.items) {
        const form = document.createElement('form');
        form.method = 'post';
        form.action = item.open_url;
        const token = document.createElement('input');
        token.type = 'hidden'; token.name = 'csrf_token'; token.value = root.dataset.csrf;
        const button = document.createElement('button');
        button.type = 'submit'; button.className = 'h-notification-item';
        const title = document.createElement('span');
        title.textContent = item.title; title.className = item.unread ? 'fw-bold' : '';
        button.append(title);
        if (item.unread) {
          const dot = document.createElement('span'); dot.className = 'h-notification-unread'; dot.setAttribute('aria-label', 'Unread'); button.append(dot);
        }
        const body = document.createElement('small');
        body.textContent = item.body.length > 100 ? item.body.slice(0, 100) + '...' : item.body;
        body.className = 'text-muted d-block'; button.append(body);
        form.append(token, button); items.append(form);
      }
      if (!data.items.length) {
        const empty = document.createElement('p'); empty.className = 'text-muted px-3 py-2 mb-0'; empty.textContent = 'No notifications yet.'; items.append(empty);
      }
    } catch (error) {}
  }
  window.setInterval(refresh, 60000);
  document.addEventListener('visibilitychange', refresh);
  bell.addEventListener('click', refresh);
})();