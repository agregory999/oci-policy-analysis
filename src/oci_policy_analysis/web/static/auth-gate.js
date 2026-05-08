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
      if (!response.ok) return false;
      const payload = await response.json();
      return Boolean(payload.authenticated);
    } catch (_err) {
      return false;
    }
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
    const isAuthed = await checkStatus();
    if (isAuthed) {
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
