(() => {
  const $ = id => document.getElementById(id);
  const scopes = {requestor_group_tag:'Requestor Group',requestor_compartment_tag:'Requestor Compartment',target_resource_tag:'Target Resource',target_compartment_tag:'Target Compartment'};
  let inventory = {statements:[],conditions:[],catalog:[]}, tab = 'statements', selected = null, generation = 0;
  const text = value => typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
  const identity = row => JSON.stringify([row.policy_ocid,row.internal_id,row.statement_text]);
  const policyPath = row => [row.compartment_path,row.policy_name].filter(Boolean).join(' :: ');
  function clearSelection() { selected = null; $('testFull').disabled = $('testAtom').disabled = true; $('evidence').hidden = true; }
  function pick(row, tr) {
    selected = row;
    document.querySelectorAll('#evidenceTable tr.selected').forEach(node => node.classList.remove('selected'));
    tr.classList.add('selected');
    $('testFull').disabled = !row.conditions;
    $('testAtom').disabled = tab !== 'conditions' || !row.tag_expression;
    $('coverage').textContent = (row.tag_context_warnings || []).join(' • ') || 'Review the complete condition; tag catalog coverage may be incomplete.';
  }
  function render() {
    clearSelection();
    const needle = $('search').value.trim().toLowerCase();
    const atoms = inventory.conditions.filter(row => (!$('scope').value || row.tag_scope === $('scope').value) && [['namespace','tag_namespace'],['key','tag_key'],['value','tag_value']].every(([id,key]) => text(row[key]).toLowerCase().includes($(id).value.trim().toLowerCase())) && (!needle || text(row).toLowerCase().includes(needle)));
    const sources = new Set(atoms.map(identity));
    const statements = inventory.statements.filter(row => sources.has(identity(row)));
    const rows = tab === 'statements' ? statements : tab === 'conditions' ? atoms : inventory.catalog.filter(row => !needle || text(row).toLowerCase().includes(needle));
    const columns = tab === 'statements' ? [['Policy Path',policyPath],['Effective Path',row=>row.effective_path],['Statement',row=>row.statement_text]] : tab === 'conditions' ? [['Policy Path',policyPath],['Tag Applies To',row=>scopes[row.tag_scope] || row.tag_scope],['Namespace',row=>row.tag_namespace],['Key',row=>row.tag_key],['Operator',row=>row.tag_operator],['Value / Variable',row=>row.tag_value],['Parse Status',row=>row.tag_parse_status],['Tag Predicate',row=>row.tag_expression]] : [['Namespace',row=>row.namespace],['Key',row=>row.key],['Allowed Values',row=>row.values],['Compartment',row=>row.path]];
    const head = $('evidenceTable').tHead, body = $('evidenceTable').tBodies[0]; head.replaceChildren(); body.replaceChildren();
    const header = head.insertRow(); columns.forEach(([name]) => { const th = document.createElement('th'); th.textContent = name; header.appendChild(th); });
    rows.forEach(row => {
      const tr = body.insertRow(); tr.tabIndex = 0; if(row.valid === false) tr.classList.add('invalid');
      columns.forEach(([,value]) => { const td = tr.insertCell(); td.textContent = text(value(row)); });
      tr.addEventListener('click', () => pick(row,tr));
      const inspect = () => { pick(row,tr); $('detailRows').innerHTML = tab === 'catalog' ? '' : window.renderPolicyStatementInspectorRows(row); $('rawDetail').textContent = JSON.stringify(row,null,2); $('evidence').hidden = false; };
      tr.addEventListener('contextmenu',event => { event.preventDefault(); inspect(); });
      tr.addEventListener('keydown',event => { if(event.key === 'Enter') inspect(); });
    });
    $('status').textContent = `${statements.length} / ${inventory.statements.length} tag-qualified statements · ${atoms.length} predicates/references · ${inventory.namespace_count || 0} parsed namespaces. Catalog is snapshot reference data.`;
  }
  async function load() {
    const current = ++generation; clearSelection(); $('status').textContent = 'Loading snapshot evidence…';
    try { const response = await fetch('/analysis/tag-based'); const payload = await response.json(); if(!response.ok) throw new Error(payload.detail || 'Could not load tag evidence'); if(current !== generation) return; inventory = payload; render(); }
    catch(error) { if(current === generation) $('status').textContent = error.message; }
  }
  ['search','scope','namespace','key','value'].forEach(id => $(id).addEventListener('input',render));
  ['statements','conditions','catalog'].forEach(name => $(name+'Tab').addEventListener('click',()=>{tab=name;['statements','conditions','catalog'].forEach(key=>$(key+'Tab').setAttribute('aria-selected',String(key===name)));render();}));
  $('reset').addEventListener('click',()=>{['search','scope','namespace','key','value'].forEach(id=>$(id).value='');render();});
  $('refresh').addEventListener('click',load);
  const test = atom => { const clause = atom ? selected?.tag_expression : selected?.conditions; if(clause) { sessionStorage.setItem('ociConditionTesterClause',clause); location.href='/condition-tester.html?from=tag-based-policies'; } };
  $('testFull').addEventListener('click',()=>test(false)); $('testAtom').addEventListener('click',()=>test(true)); $('closeDetails').addEventListener('click',()=>$('evidence').hidden=true);
  load();
})();
