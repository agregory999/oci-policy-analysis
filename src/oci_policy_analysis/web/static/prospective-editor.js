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
            <table class="prospective-statements-table"><tbody data-role="rows"></tbody></table>
          </div>
          <div>
            <strong>Builder</strong>
            <div class="prospective-builder-grid" style="margin-top:.5rem;">
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbAction" class="no-margin-label">Action</label><select id="pbAction" data-role="pbAction" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Allow or Deny for the generated statement.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbPrincipal" class="no-margin-label">Principal</label><select id="pbPrincipal" data-role="pbPrincipal" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Principal template used in the statement subject.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbVerb" class="no-margin-label">Verb</label><select id="pbVerb" data-role="pbVerb" class="prospective-builder-control"></select></div>
                  <div class="helper-text">IAM verb to apply.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbResource" class="no-margin-label">Resource</label><select id="pbResource" data-role="pbResource" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Resource or resource family.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbLocation" class="no-margin-label">Location</label><select id="pbLocation" data-role="pbLocation" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Compartment/location path for the statement.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbEffectivePath" class="no-margin-label">Effective Path</label><select id="pbEffectivePath" data-role="pbEffectivePath" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Effective path used for simulation context.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <label class="checkbox-label"><input id="pbIncludeDefault" data-role="pbIncludeDefault" type="checkbox" /> Include Default</label>
                  <div class="helper-text">Adds Default domain even if not required.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <label class="checkbox-label"><input id="pbUseAllResources" data-role="pbUseAllResources" type="checkbox" /> All Resources</label>
                  <div class="helper-text">Show all known resources/families instead of resources in tenancy.</div>
                </div>
              </div>
              <div class="prospective-builder-cell">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbWhereMode" class="no-margin-label">Where Mode</label><select id="pbWhereMode" data-role="pbWhereMode" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Choose no clause, tag-based clause, or custom text clause.</div>
                </div>
              </div>

              <div data-role="pbTagWhereAccess" class="prospective-builder-cell prospective-builder-tag-row-start" style="display:none;">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbAccessType" class="no-margin-label">Access Type</label><select id="pbAccessType" data-role="pbAccessType" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Define the access attribute family.</div>
                </div>
              </div>
              <div data-role="pbTagWhereNamespace" class="prospective-builder-cell" style="display:none;">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbNamespace" class="no-margin-label">Tag Namespace</label><input id="pbNamespace" data-role="pbNamespace" class="prospective-builder-control" /></div>
                  <div class="helper-text">Namespace containing the tag key.</div>
                </div>
              </div>
              <div data-role="pbTagWhereTagKey" class="prospective-builder-cell" style="display:none;">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbTagKey" class="no-margin-label">Tag Key</label><input id="pbTagKey" data-role="pbTagKey" class="prospective-builder-control" /></div>
                  <div class="helper-text">Specific tag key to evaluate.</div>
                </div>
              </div>
              <div data-role="pbTagWhereOperator" class="prospective-builder-cell" style="display:none;">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbOperator" class="no-margin-label">Operator</label><select id="pbOperator" data-role="pbOperator" class="prospective-builder-control"></select></div>
                  <div class="helper-text">Comparison operator for the tag condition.</div>
                </div>
              </div>
              <div data-role="pbTagWhereValue" class="prospective-builder-cell prospective-builder-span-2" style="display:none;">
                <div class="field">
                  <div class="tenancy-options-row prospective-builder-inline-row"><label for="pbValue" class="no-margin-label">Value(s)</label><input id="pbValue" data-role="pbValue" class="prospective-builder-control" /></div>
                  <div class="helper-text">For IN/NOT IN, provide a comma-separated list of values.</div>
                </div>
              </div>
              <div data-role="pbOtherWhereRow" class="prospective-builder-cell prospective-builder-span-4" style="display:none;">
                <div class="field">
                  <label for="pbOtherWhereText" class="no-margin-label">Other Where Text (no 'where')</label>
                  <textarea id="pbOtherWhereText" data-role="pbOtherWhereText"></textarea>
                  <div class="helper-text">Enter the clause text only, without the leading where keyword.</div>
                </div>
              </div>
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
      if (!rows.length) {
        const trEmpty = document.createElement('tr');
        trEmpty.className = 'prospective-empty-row';
        trEmpty.innerHTML = '<td colspan="4" class="prospective-empty-state">No prospective statement - Use the builder or add a free form statement</td>';
        rowsBody.appendChild(trEmpty);
        return;
      }
      rows.forEach((row, idx) => {
        const trHeader = document.createElement('tr');
        trHeader.className = 'prospective-block-header-row';
        trHeader.innerHTML = '<th scope="col" style="width:40%;">Location</th><th scope="col" style="width:40%;">Description</th><th scope="col" style="width:5%;">Status</th><th scope="col" style="width:15%;">Actions</th>';

        const trValues = document.createElement('tr');
        trValues.className = 'prospective-block-values-row';
        trValues.innerHTML = `<td style="width:40%;"><input data-k="compartment_path" data-i="${idx}" value="${esc(row.compartment_path || 'ROOT')}" /></td><td style="width:40%;"><input data-k="description" data-i="${idx}" value="${esc(row.description || '')}" /></td><td style="width:5%;">${esc(rowStatus(row))}</td><td style="width:15%;"><button class="ghost" data-action="parse" data-i="${idx}" type="button" style="margin-top:0;">Parse</button> <button class="ghost" data-action="delete" data-i="${idx}" type="button" style="margin-top:0;">Delete</button></td>`;

        const trStatementHeader = document.createElement('tr');
        trStatementHeader.className = 'prospective-block-statement-header-row';
        trStatementHeader.innerHTML = '<th colspan="4" scope="col">Statement Text</th>';

        const trStatementValue = document.createElement('tr');
        trStatementValue.className = 'prospective-block-bottom prospective-block-statement-value-row';
        trStatementValue.innerHTML = `<td colspan="4" class="prospective-line2-cell"><textarea data-k="statement_text" data-i="${idx}">${esc(row.statement_text || '')}</textarea><div style="color:#b45309;font-size:.75rem;">${esc((row.invalid_reasons || []).join('; '))}</div></td>`;

        rowsBody.append(trHeader, trValues, trStatementHeader, trStatementValue);
      });
    }

    function updateWhereModeVisibility() {
      const modeVal = String(q('pbWhereMode').value || 'No Where Clause');
      const showTagMode = modeVal === 'Tag-based Where Clause';
      q('pbTagWhereAccess').style.display = showTagMode ? 'block' : 'none';
      q('pbTagWhereNamespace').style.display = showTagMode ? 'block' : 'none';
      q('pbTagWhereTagKey').style.display = showTagMode ? 'block' : 'none';
      q('pbTagWhereOperator').style.display = showTagMode ? 'block' : 'none';
      q('pbTagWhereValue').style.display = showTagMode ? 'block' : 'none';
      q('pbOtherWhereRow').style.display = modeVal === 'Other Where Clause' ? 'block' : 'none';
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
