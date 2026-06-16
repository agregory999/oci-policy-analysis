(function () {
  function formatStartTime(value) {
    if (!value) return 'unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZoneName: 'short',
    });
  }

  function createPair(labelText, valueText) {
    const item = document.createElement('span');
    item.className = 'app-version-item';

    const label = document.createElement('span');
    label.className = 'app-version-label';
    label.textContent = labelText;
    const version = document.createElement('span');
    version.className = 'app-version-value';
    version.textContent = valueText || 'unknown';

    item.append(label, version);
    return item;
  }

  function createFooter(metadata) {
    const footer = document.createElement('footer');
    footer.className = 'app-version-footer';
    footer.setAttribute('aria-label', 'Application runtime details');
    footer.append(
      createPair('Application Version', metadata.version || 'dev'),
      createPair('Server Started', formatStartTime(metadata.server_started_at))
    );
    return footer;
  }

  async function resolveMetadata() {
    try {
      const response = await fetch('/metadata/app', { cache: 'no-store' });
      if (!response.ok) return { version: 'dev', server_started_at: '' };
      const payload = await response.json();
      return {
        version: payload.version || 'dev',
        server_started_at: payload.server_started_at || '',
      };
    } catch (_err) {
      return { version: 'dev', server_started_at: '' };
    }
  }

  async function renderVersionFooter() {
    if (document.querySelector('.app-version-footer')) return;

    const metadata = await resolveMetadata();
    document.body.appendChild(createFooter(metadata));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderVersionFooter);
  } else {
    renderVersionFooter();
  }
})();
