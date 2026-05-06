(() => {
  function esc(v) {
    return String(v ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function template(mode) {
    const shellClass =
      mode === 'page'
        ? 'card compact-card'
        : 'inspector-panel inspector-panel-bottom';
    const header =
      mode === 'page'
        ? '<div class="workflow-panel-header"><h2 class="workflow-panel-title">Prospective Statement Editor</h2><div class="workflow-actions"><button data-role="close" class="ghost" type="button">Close</button></div></div>'
        : '<div class="inspector-header"><strong>Prospective Statement Editor</strong><button data-role="close" class="ghost" style="margin-top:0;" type="button">×</button></div>';
    return `
      <aside data-role="root" class="${shellClass}" aria-live="polite">
        ${header}
        <div class="inspector-body custom-scrollbar" style="padding:.8rem; display:grid; gap:.8rem;">
          <div class="prospective-grid">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem;"><strong>Statements</strong><button data-role="add-row" class="ghost" style="margin-top:0;" type="button">Add Free-Form Statement</button></div>
            <table><thead class="prospective-rows-head"><tr><th>Location</th><th>Description</th><th>Status</th><th>Actions</th></tr></thead><tbody data-role="rows"></tbody></table>
          </div>
          <div>
            <strong>Builder</strong>
            <div class="prospective-builder-grid" style="margin-top:.5rem;">
              <div class="prospective-builder-row"><div class="prospective-field"><label>Action</label><select data-role="pbAction"></select></div><div class="prospective-field"><label>Principal</label><select data-role="pbPrincipal"></select></div><div class="prospective-field"><label>Include Default</label><div class="prospective-inline-check"><input data-role="pbIncludeDefault" type="checkbox" /><span class="prospective-note">Adds Default domain where applicable.</span></div></div></div>
              <div class="prospective-builder-row"><div class="prospective-field"><label>Verb</label><select data-role="pbVerb"></select></div><div class="prospective-field"><label>Resource</label><select data-role="pbResource"></select></div><div class="prospective-field"><label>All Resources</label><div class="prospective-inline-check"><input data-role="pbUseAllResources" type="checkbox" /><span class="prospective-note">Use all known resources/families.</span></div></div></div>
              <div class="prospective-builder-row two"><div class="prospective-field"><label>Location</label><select data-role="pbLocation"></select></div><div class="prospective-field"><label>Effective Path</label><select data-role="pbEffectivePath"></select></div></div>
              <div class="prospective-builder-row"><div class="prospective-field"><label>Where Mode</label><select data-role="pbWhereMode"></select></div></div>
              <div data-role="pbOtherWhereRow" class="prospective-builder-row" style="display:none;"><div class="prospective-field"><label>Other Where Text (no 'where')</label><textarea data-role="pbOtherWhereText"></textarea></div></div>
              <div data-role="pbTagWhereRow1" class="prospective-builder-row"><div class="prospective-field"><label>Access Type</label><select data-role="pbAccessType"></select></div><div class="prospective-field"><label>Tag Namespace</label><input data-role="pbNamespace" /></div><div class="prospective-field"><label>Tag Key</label><input data-role="pbTagKey" /></div></div>
              <div data-role="pbTagWhereRow2" class="prospective-builder-row two"><div class="prospective-field"><label>Operator</label><select data-role="pbOperator"></select></div><div class="prospective-field"><label>Value(s)</label><input data-role="pbValue" /></div></div>
            </div>
            <div style="display:flex;gap:.5rem;margin-top:.5rem;"><button data-role="preview" class="ghost" style="margin-top:0;" type="button">Preview</button><button data-role="clear" class="ghost" style="margin-top:0;" type="button">Clear Builder</button><button data-role="add-builder" class="ghost" style="margin-top:0;" type="button">Add to Statements</button><button data-role="save" type="button" style="margin-top:0;">Save and Close</button></div>
            <div data-role="previewBox" class="prospective-preview" style="margin-top:.5rem;">No preview yet.</div>
          </div>
        </div>
      </aside>`;
  }

  window.createProspectiveEditor = function createProspectiveEditor({ host, mode = 'drawer', onSaved }) {
    if (!host) throw new Error('ProspectiveEditor host is required');
    host.innerHTML = template(mode);
    const root = host.querySelector('[data-role="root"]');
    const q = (r) => root.querySelector(`[data-role="${r}"]`);
    const rowsBody = q('rows');
    let rows = [];
    let meta = null;

    function setOpts(role, vals) {
      q(role).innerHTML = (vals || []).map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    }

    function rowStatus(row) {
      if (row.parsed && row.valid) return 'Parsed';
      if (Array.isArray(row.invalid_reasons) && row.invalid_reasons.length) return 'Invalid';
      return 'Not parsed';
    }

    function renderRows() {
      rowsBody.innerHTML = '';
      rows.forEach((row, idx) => {
        const trTop = document.createElement('tr');
        trTop.innerHTML = `<td><input data-k="compartment_path" data-i="${idx}" value="${esc(row.compartment_path || 'ROOT')}" /></td><td><input data-k="description" data-i="${idx}" value="${esc(row.description || '')}" /></td><td>${esc(rowStatus(row))}</td><td><button class="ghost" data-action="parse" data-i="${idx}" type="button" style="margin-top:0;">Parse</button> <button class="ghost" data-action="delete" data-i="${idx}" type="button" style="margin-top:0;">Delete</button></td>`;
        const trBottom = document.createElement('tr');
        trBottom.innerHTML = `<td colspan="4" class="prospective-line2-cell"><textarea data-k="statement_text" data-i="${idx}">${esc(row.statement_text || '')}</textarea><div style="color:#b45309;font-size:.75rem;">${esc((row.invalid_reasons || []).join('; '))}</div></td>`;
        const trSep = document.createElement('tr');
        trSep.className = 'prospective-sep';
        trSep.innerHTML = '<td colspan="4"><div class="prospective-sep-line"></div></td>';
        rowsBody.append(trTop, trBottom, trSep);
      });
    }

    function updateWhereModeVisibility() {
      const modeVal = String(q('pbWhereMode').value || 'No Where Clause');
      q('pbTagWhereRow1').style.display = modeVal === 'Tag-based Where Clause' ? 'grid' : 'none';
      q('pbTagWhereRow2').style.display = modeVal === 'Tag-based Where Clause' ? 'grid' : 'none';
      q('pbOtherWhereRow').style.display = modeVal === 'Other Where Clause' ? 'grid' : 'none';
    }

    function refreshResourceDropdownFromMode() {
      if (!meta) return;
      const src = q('pbUseAllResources').checked ? (meta.resources_all_possible || []) : (meta.resources_in_use || []);
      const prior = q('pbResource').value;
      setOpts('pbResource', src);
      if (src.includes(prior)) q('pbResource').value = prior;
    }

    async function previewBuilder() {
      const payload = {
        action: q('pbAction').value,
        principal_key: q('pbPrincipal').value,
        include_default: q('pbIncludeDefault').checked,
        verb: q('pbVerb').value,
        resource: q('pbResource').value,
        location: q('pbLocation').value,
        effective_path: q('pbEffectivePath').value,
        where_mode: q('pbWhereMode').value,
        access_type: q('pbAccessType').value,
        namespace: q('pbNamespace').value,
        tag_key: q('pbTagKey').value,
        operator: q('pbOperator').value,
        value: q('pbValue').value,
        other_where_text: q('pbOtherWhereText').value,
      };
      const resp = await fetch('/prospective/builder/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const p = await resp.json();
      q('previewBox').textContent = p.statement_text || 'No preview.';
      return p;
    }

    async function load() {
      const [rowsResp, metaResp] = await Promise.all([fetch('/prospective/statements'), fetch('/prospective/builder/metadata')]);
      const rowsPayload = await rowsResp.json();
      meta = await metaResp.json();
      rows = Array.isArray(rowsPayload.rows) ? rowsPayload.rows : [];
      if (!rows.length) rows.push({ compartment_path: 'ROOT', description: '', statement_text: '', invalid_reasons: [] });
      setOpts('pbAction', meta.actions || ['Allow', 'Deny']);
      setOpts('pbPrincipal', meta.principals || []);
      setOpts('pbVerb', meta.verbs || ['inspect', 'read', 'use', 'manage']);
      setOpts('pbResource', meta.resources_in_use || []);
      setOpts('pbLocation', meta.locations || ['ROOT']);
      setOpts('pbEffectivePath', meta.effective_paths || ['ROOT']);
      setOpts('pbWhereMode', meta.where_modes || ['No Where Clause', 'Tag-based Where Clause', 'Other Where Clause']);
      setOpts('pbAccessType', meta.access_types || []);
      setOpts('pbOperator', meta.operators || ['=', '!=', 'IN', 'NOT IN']);
      q('pbAction').value = 'Allow';
      q('pbVerb').value = 'use';
      q('pbWhereMode').value = 'No Where Clause';
      q('pbOperator').value = '=';
      updateWhereModeVisibility();
      renderRows();
    }

    async function save() {
      await fetch('/prospective/statements/replace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows }),
      });
      close();
      if (typeof onSaved === 'function') await onSaved();
    }

    function open() {
      if (mode !== 'page') root.classList.add('open');
      return load();
    }

    function close() {
      if (mode !== 'page') root.classList.remove('open');
    }

    rowsBody.addEventListener('input', (event) => {
      const t = event.target;
      if (!(t instanceof HTMLElement)) return;
      const i = Number(t.dataset.i);
      const k = t.dataset.k;
      if (!Number.isFinite(i) || !k || !rows[i]) return;
      rows[i][k] = t.value;
    });

    rowsBody.addEventListener('click', async (event) => {
      const t = event.target;
      if (!(t instanceof HTMLElement)) return;
      const action = t.dataset.action;
      const i = Number(t.dataset.i);
      if (!Number.isFinite(i)) return;
      if (action === 'delete') {
        rows.splice(i, 1);
        if (!rows.length) rows.push({ compartment_path: 'ROOT', description: '', statement_text: '', invalid_reasons: [] });
        renderRows();
        return;
      }
      if (action === 'parse') {
        const resp = await fetch('/prospective/statements/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rows[i]) });
        const payload = await resp.json();
        rows[i] = payload.row;
        renderRows();
      }
    });

    q('add-row').addEventListener('click', () => {
      rows.push({ compartment_path: 'ROOT', description: '', statement_text: '', invalid_reasons: [] });
      renderRows();
    });
    q('preview').addEventListener('click', previewBuilder);
    q('add-builder').addEventListener('click', async () => {
      const p = await previewBuilder();
      rows.push({ compartment_path: q('pbLocation').value || 'ROOT', description: p.description_suggestion || '', statement_text: p.statement_text || '', invalid_reasons: [] });
      renderRows();
    });
    q('save').addEventListener('click', save);
    q('close').addEventListener('click', close);
    q('pbUseAllResources').addEventListener('change', refreshResourceDropdownFromMode);
    q('pbWhereMode').addEventListener('change', updateWhereModeVisibility);
    q('clear').addEventListener('click', () => {
      q('pbIncludeDefault').checked = false;
      q('pbWhereMode').value = 'No Where Clause';
      q('pbNamespace').value = '';
      q('pbTagKey').value = '';
      q('pbValue').value = '';
      q('pbOtherWhereText').value = '';
      q('previewBox').textContent = 'No preview yet.';
      updateWhereModeVisibility();
    });

    if (mode === 'page') load();
    return { open, close, reload: load };
  };
})();
