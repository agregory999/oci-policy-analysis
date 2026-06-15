(function () {
  const OVERLAY_ID = 'authGateOverlay';

  function removeOverlay() {
    const existing = document.getElementById(OVERLAY_ID);
    if (existing) existing.remove();
  }

  function buildOverlay() {
    removeOverlay();
    const overlay = document.createElement('div');
    overlay.id = OVERLAY_ID;
    overlay.className = 'modal-overlay animate-fade';
    overlay.innerHTML = `
      <section class="auth-modal-card" role="dialog" aria-modal="true" aria-labelledby="authGateTitle">
        <h2 id="authGateTitle">Session Access Key Required</h2>
        <p>Enter the runtime access key shown in server startup CRITICAL logs.</p>
        <label for="authGateKeyInput">Access Key</label>
        <input id="authGateKeyInput" type="password" autocomplete="off" placeholder="Paste startup access key" />
        <div id="authGateError" class="auth-modal-error"></div>
        <div class="auth-modal-actions">
          <button id="authGateSubmitBtn" type="button">Unlock</button>
        </div>
      </section>
    `;
    document.body.appendChild(overlay);
    return overlay;
  }

  async function checkStatus() {
    try {
      const response = await fetch('/auth/status', { cache: 'no-store' });
      if (!response.ok) return { authenticated: false };
      return response.json();
    } catch (_err) {
      return { authenticated: false };
    }
  }

  function ensureRoleBadge(statusPayload) {
    const masthead = document.querySelector('.app-masthead');
    if (!masthead) return;
    let meta = masthead.querySelector('.masthead-meta');
    if (!meta) {
      meta = document.createElement('div');
      meta.className = 'masthead-meta';
      masthead.appendChild(meta);
    }
    const mode = String(statusPayload?.auth_mode || '').trim() || 'unknown';
    const roleLabel = mode === 'admin' ? 'Admin' : mode === 'limited' ? 'Limited' : 'Unknown';
    const roleId = 'authGateRoleBadge';
    let roleEl = document.getElementById(roleId);
    if (!roleEl) {
      roleEl = document.createElement('span');
      roleEl.id = roleId;
      roleEl.className = 'pill';
      roleEl.style.marginLeft = '0.4rem';
      roleEl.style.display = 'inline-block';
      meta.appendChild(roleEl);
    }
    roleEl.textContent = `Mode: ${roleLabel}`;
  }

  function ensureLimitedBanner(statusPayload) {
    const isLimited = String(statusPayload?.auth_mode || '') === 'limited';
    const existing = document.getElementById('limitedScopeBanner');
    if (!isLimited) {
      if (existing) existing.remove();
      return;
    }
    if (existing) return;
    const scope = statusPayload?.limited_scope || {};
    const root = Array.isArray(scope.compartment_root_paths) && scope.compartment_root_paths.length
      ? scope.compartment_root_paths.join(', ')
      : String(scope.compartment_root_path || '').trim() || '(unspecified scope)';
    const domains = Array.isArray(scope.allowed_identity_domains) && scope.allowed_identity_domains.length
      ? scope.allowed_identity_domains.join(', ')
      : 'none';
    const banner = document.createElement('section');
    banner.id = 'limitedScopeBanner';
    banner.className = 'card compact-card';
    banner.style.margin = '0 0 0.5rem 0';
    banner.style.maxWidth = 'none';
    banner.style.boxSizing = 'border-box';
    banner.style.padding = '0.5rem 0.75rem';
    banner.style.gridColumn = '1 / -1';
    banner.innerHTML = `
      <p class="card-title">Showing scoped data</p>
      <p class="helper-text"><strong>Compartment Scope:</strong> ${root} &nbsp;•&nbsp; <strong>Allowed Identity Domains:</strong> ${domains}</p>
    `;
    const main = document.querySelector('main');
    if (main) {
      main.prepend(banner);
      return;
    }
    const topRow = document.querySelector('.top-row');
    if (topRow && topRow.parentNode) {
      topRow.parentNode.insertBefore(banner, topRow.nextSibling);
      return;
    }
    document.body.prepend(banner);
  }

  async function submitLogin(keyValue) {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: String(keyValue || '') }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  async function ensureAccess() {
    const status = await checkStatus();
    if (status && status.authenticated) {
      const isLimited = String(status?.auth_mode || '') === 'limited';
      const path = String(window.location.pathname || '');
      if (isLimited && (path === '/' || path === '/index.html')) {
        window.location.replace('/limited-home.html');
        return;
      }
      ensureRoleBadge(status);
      ensureLimitedBanner(status);
      removeOverlay();
      return;
    }

    const overlay = buildOverlay();
    const input = overlay.querySelector('#authGateKeyInput');
    const error = overlay.querySelector('#authGateError');
    const submitBtn = overlay.querySelector('#authGateSubmitBtn');

    async function tryLogin() {
      const candidate = String(input?.value || '').trim();
      if (!candidate) {
        if (error) error.textContent = 'Access key is required.';
        return;
      }
      if (submitBtn) submitBtn.disabled = true;
      if (error) error.textContent = '';
      try {
        const payload = await submitLogin(candidate);
        if (payload && payload.authenticated) {
          const postStatus = await checkStatus();
          const isLimited = String(postStatus?.auth_mode || '') === 'limited';
          const path = String(window.location.pathname || '');
          if (isLimited && (path === '/' || path === '/index.html')) {
            window.location.replace('/limited-home.html');
            return;
          }
          ensureRoleBadge(postStatus);
          ensureLimitedBanner(postStatus);
          removeOverlay();
          return;
        }
        if (error) error.textContent = payload?.message || 'Invalid access key.';
      } catch (_err) {
        if (error) error.textContent = 'Unable to verify key. Try again.';
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    }

    submitBtn?.addEventListener('click', tryLogin);
    input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        void tryLogin();
      }
    });
    input?.focus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      void ensureAccess();
    });
  } else {
    void ensureAccess();
  }
})();
