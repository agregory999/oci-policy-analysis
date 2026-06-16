(() => {
  function esc(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function defaultGetRowValue(row, key) {
    if (key === 'invalid_reasons') {
      const reasons = row?.invalid_reasons;
      if (Array.isArray(reasons) && reasons.length) return reasons;
      const legacy = row?.invalid_reason;
      if (Array.isArray(legacy)) return legacy;
      if (legacy !== undefined && legacy !== null && String(legacy).trim() !== '') return [String(legacy)];
    }
    if (key === 'confidence') {
      return row?.confidence ?? row?.Confidence ?? row?.match_confidence ?? row?.['Match Confidence'] ?? '';
    }
    if (key === 'match_confidence') {
      return row?.match_confidence ?? row?.['Match Confidence'] ?? row?.confidence ?? row?.Confidence ?? '';
    }
    const titleKey = String(key || '')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
    return row?.[key] ?? row?.[titleKey] ?? '';
  }

  function defaultFormatValue(key, value) {
    if (value === null || value === undefined || value === '') return '-';

    if (key === 'principals' && Array.isArray(value)) {
      if (!value.length) return '-';
      return value
        .map((principal) => {
          if (!principal || typeof principal !== 'object') return String(principal);
          const principalType = principal.principal_type || 'principal';
          const principalDisplay =
            principal.display_name ||
            [principal.domain_name, principal.name].filter(Boolean).join('/') ||
            principal.ocid ||
            principal.principal_key ||
            JSON.stringify(principal);
          return `${principalType}: ${principalDisplay}`;
        })
        .join('\n');
    }

    if (Array.isArray(value)) {
      return value
        .map((item) => {
          if (item === null || item === undefined) return '';
          if (typeof item === 'object') return JSON.stringify(item);
          return String(item);
        })
        .filter((item) => item !== '')
        .join('\n');
    }

    if (typeof value === 'object') {
      return JSON.stringify(value, null, 2);
    }

    return String(value);
  }

  const FIELD_LABELS = {
    action: 'Action',
    compartment_ocid: 'Compartment OCID',
    compartment_path: 'Policy Compartment',
    conditions_where_clause: 'Conditions (Where Clause)',
    conditions_parsed_structure: 'Parsed Structure',
    condition_atoms: 'Condition Elements',
    effective_path: 'Effective Path',
    internal_id: 'Internal ID',
    invalid: 'Invalid',
    invalid_reasons: 'Invalid Reasons',
    location_type: 'Location Type',
    match_confidence: 'Match Confidence',
    match_confidence_reason: 'Match Confidence Reason',
    parsing_notes: 'Parsing Notes',
    policy_compartment: 'Policy Compartment',
    policy_name: 'Policy Name',
    policy_ocid: 'Policy OCID',
    policy_path: 'Policy Path',
    principal_keys: 'Principal Keys',
    statement_text: 'Statement Text',
    subject_type: 'Subject Type',
  };

  const DEFAULT_BASIC_FIELD_ORDER = [
    'policy_compartment',
    'compartment_path',
    'policy_path',
    'policy_name',
    'policy_ocid',
    'compartment_ocid',
    'internal_id',
    'effective_path',
    'statement_text',
    'creation_time',
    'invalid',
    'invalid_reasons',
    'parsed',
    'confidence',
  ];

  const DEFAULT_PARSED_FIELD_ORDER = [
    'action',
    'subject_type',
    'subject',
    'principals',
    'principal_keys',
    'verb',
    'resource',
    'permission',
    'location_type',
    'location',
    'comments',
    'parsing_notes',
    'conditions_where_clause',
  ];

  const CONDITION_RAW_KEYS = [
    'conditions_where_clause',
    'Conditions (where clause)',
    'Conditions (Where Clause)',
    'conditions',
    'Conditions',
    'Where Clause',
  ];
  const CONDITION_STRUCTURE_KEYS = [
    'conditions_parsed_structure',
    'Conditions (parsed structure)',
    'Conditions (Parsed Structure)',
    'where_structure',
    'Where Structure',
  ];
  const CONDITION_ATOM_KEYS = ['condition_atoms'];
  const CONDITION_ELEMENT_FALLBACK_KEYS = [
    'conditions_elements',
    'condition_elements',
    'Conditions (elements)',
    'Conditions (Elements)',
  ];
  const CONDITION_STRUCTURE_OBJECT_KEYS = ['where_clause_structure', 'where_clause', 'Where Clause Structure'];
  const MATCH_CONFIDENCE_KEYS = ['match_confidence', 'Match Confidence', 'confidence', 'Confidence'];
  const MATCH_REASON_KEYS = ['match_confidence_reason', 'Match Confidence Reason'];
  const PRINCIPAL_EVIDENCE_KEYS = ['principal_evidence', 'Principal Evidence'];
  const RESIDUAL_CONDITION_KEYS = ['residual_conditions', 'Residual Conditions'];
  const DEFAULT_EXCLUDED_FIELDS = [
    '_row_id',
    'internal_id',
    'Internal ID',
    'effective_compartment_ocid',
    'conditions',
    'Conditions',
    'conditions_where_clause',
    'Conditions (where clause)',
    'Conditions (Where Clause)',
    'conditions_parsed_structure',
    'Conditions (parsed structure)',
    'Conditions (Parsed Structure)',
    'conditions_elements',
    'condition_elements',
    'Conditions (elements)',
    'Conditions (Elements)',
    'condition_atoms',
    'where_clause',
    'where_clause_structure',
    'where_structure',
    'Where Clause Structure',
    'Where Structure',
    'principal_evidence',
    'Principal Evidence',
    'residual_conditions',
    'Residual Conditions',
    'match_confidence_reason',
    'Match Confidence Reason',
  ];

  function defaultLabelForKey(key) {
    if (FIELD_LABELS[key]) return FIELD_LABELS[key];
    return String(key || '')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function hasDisplayValue(value) {
    if (value === null || value === undefined) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value).length > 0;
    return String(value).trim() !== '';
  }

  function unique(values) {
    const seen = new Set();
    const output = [];
    values.forEach((value) => {
      const key = canonicalFieldKey(value);
      if (!key || seen.has(key)) return;
      seen.add(key);
      output.push(key);
    });
    return output;
  }

  function canonicalFieldKey(key) {
    const raw = String(key || '').trim();
    const normalized = raw.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    if (!raw) return '';
    if (normalized === 'valid') return 'invalid';
    if (normalized === 'invalid_reasons' || normalized === 'invalid_reason') return 'invalid_reasons';
    if (normalized === 'parsed') return 'parsed';
    if (CONDITION_RAW_KEYS.includes(raw) || normalized === 'conditions_where_clause' || normalized === 'conditions') {
      return 'conditions_where_clause';
    }
    if (CONDITION_STRUCTURE_KEYS.includes(raw) || normalized === 'conditions_parsed_structure') {
      return 'conditions_parsed_structure';
    }
    if (
      CONDITION_ATOM_KEYS.includes(raw) ||
      CONDITION_ELEMENT_FALLBACK_KEYS.includes(raw) ||
      normalized === 'condition_atoms' ||
      normalized === 'conditions_elements' ||
      normalized === 'condition_elements'
    ) {
      return 'condition_atoms';
    }
    if (
      CONDITION_STRUCTURE_OBJECT_KEYS.includes(raw) ||
      normalized === 'where_clause' ||
      normalized === 'where_clause_structure' ||
      normalized === 'where_structure'
    ) {
      return 'where_clause_structure';
    }
    return raw;
  }

  function readFirst(row, keys, getRowValue) {
    for (const key of keys) {
      const value = getRowValue(row, key);
      if (hasDisplayValue(value)) return value;
    }
    return '';
  }

  function parseBool(value) {
    if (typeof value === 'boolean') return value;
    const text = String(value ?? '').trim().toLowerCase();
    if (['true', 'yes', '1'].includes(text)) return true;
    if (['false', 'no', '0'].includes(text)) return false;
    return null;
  }

  function invalidReasonsValue(row, getRowValue) {
    return readFirst(row, ['invalid_reasons', 'Invalid Reasons', 'invalid_reason', 'Invalid Reason'], getRowValue);
  }

  function invalidValue(row, getRowValue) {
    const explicit = readFirst(row, ['invalid', 'Invalid'], getRowValue);
    if (hasDisplayValue(explicit)) return explicit;

    const valid = readFirst(row, ['valid', 'Valid'], getRowValue);
    const parsed = parseBool(valid);
    if (parsed !== null) return !parsed;

    const reasons = invalidReasonsValue(row, getRowValue);
    if (hasDisplayValue(reasons)) return true;
    return '';
  }

  function conditionRawValue(row, getRowValue) {
    return readFirst(row, CONDITION_RAW_KEYS, getRowValue);
  }

  function structureObjectValue(row, getRowValue) {
    return readFirst(row, CONDITION_STRUCTURE_OBJECT_KEYS, getRowValue);
  }

  function conditionStructureValue(row, getRowValue) {
    const summary = readFirst(row, CONDITION_STRUCTURE_KEYS, getRowValue);
    if (hasDisplayValue(summary)) return summary;

    const structure = structureObjectValue(row, getRowValue);
    if (!structure || typeof structure !== 'object') return '';
    const status = String(structure.parse_status || '').trim();
    const label = String(structure.structure || '').trim();
    const atoms = Array.isArray(structure.atoms) ? structure.atoms.length : 0;
    if (status && label && atoms) return `${status}: ${label} (${atoms} atom${atoms === 1 ? '' : 's'})`;
    if (status && label) return `${status}: ${label}`;
    return status || label;
  }

  function parseJsonArray(value) {
    if (Array.isArray(value)) return value;
    if (typeof value !== 'string') return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_err) {
      return [];
    }
  }

  function conditionAtomsValue(row, getRowValue) {
    const direct = readFirst(row, CONDITION_ATOM_KEYS, getRowValue);
    const directAtoms = parseJsonArray(direct);
    if (directAtoms.length) return directAtoms;

    const structure = structureObjectValue(row, getRowValue);
    if (structure && typeof structure === 'object' && Array.isArray(structure.atoms)) return structure.atoms;
    return [];
  }

  function conditionElementsFallbackValue(row, getRowValue) {
    return readFirst(row, CONDITION_ELEMENT_FALLBACK_KEYS, getRowValue);
  }

  function matchConfidenceValue(row, getRowValue) {
    return readFirst(row, MATCH_CONFIDENCE_KEYS, getRowValue);
  }

  function matchReasonValue(row, getRowValue) {
    return readFirst(row, MATCH_REASON_KEYS, getRowValue);
  }

  function principalEvidenceValue(row, getRowValue) {
    const value = readFirst(row, PRINCIPAL_EVIDENCE_KEYS, getRowValue);
    const parsed = parseJsonArray(value);
    if (parsed.length) return parsed;
    return Array.isArray(value) ? value : [];
  }

  function residualConditionsValue(row, getRowValue) {
    const value = readFirst(row, RESIDUAL_CONDITION_KEYS, getRowValue);
    const parsed = parseJsonArray(value);
    if (parsed.length) return parsed;
    return Array.isArray(value) ? value : [];
  }

  function fieldValue(row, key, getRowValue) {
    if (key === 'invalid') return invalidValue(row, getRowValue);
    if (key === 'invalid_reasons') return invalidReasonsValue(row, getRowValue);
    return getRowValue(row, key);
  }

  function shouldShowBasicField(row, key, value, getRowValue) {
    if (key === 'invalid') {
      return hasDisplayValue(value) || hasDisplayValue(readFirst(row, ['valid', 'Valid'], getRowValue));
    }
    if (key === 'invalid_reasons') {
      return hasDisplayValue(value) || parseBool(invalidValue(row, getRowValue)) === true;
    }
    if (key === 'parsed') return hasDisplayValue(value);
    return hasDisplayValue(value);
  }

  function buildBasicFieldOrder(config) {
    const configuredPrimary = Array.isArray(config.primaryFieldOrder) ? config.primaryFieldOrder : [];
    return unique([...configuredPrimary, ...DEFAULT_BASIC_FIELD_ORDER]).filter(
      (key) =>
        ![
          'conditions_where_clause',
          'conditions_parsed_structure',
          'condition_atoms',
          'where_clause_structure',
          ...DEFAULT_PARSED_FIELD_ORDER.filter((field) => field !== 'conditions_where_clause'),
        ].includes(key)
    );
  }

  function buildParsedFieldOrder(config) {
    const configuredParsed = Array.isArray(config.parsedFieldOrder) ? config.parsedFieldOrder : [];
    return unique([...DEFAULT_PARSED_FIELD_ORDER, ...configuredParsed]).filter(
      (key) =>
        ![
          'invalid',
          'invalid_reasons',
          'parsed',
          'conditions_parsed_structure',
          'condition_atoms',
          'where_clause_structure',
        ].includes(key)
    );
  }

  function formatScalar(value) {
    if (value === null || value === undefined) return '';
    if (Array.isArray(value) || typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function atomSummary(atom) {
    if (!atom || typeof atom !== 'object') return String(atom ?? '');
    const atomId = String(atom.id || '').trim();
    const left = String(atom.left || '').trim();
    const operator = String(atom.operator || '').trim();
    const right = String(atom.right || '').trim();
    const subexpression = String(atom.subexpression || '').trim();
    const evidenceKind = String(atom.evidence_kind || '').trim();
    const expression = [left, operator, right].filter(Boolean).join(' ');
    const prefix = atomId ? `${atomId}: ` : '';
    const suffix = evidenceKind ? ` [${evidenceKind}]` : '';
    return `${prefix}${expression || subexpression || JSON.stringify(atom)}${suffix}`;
  }

  function atomMeta(atom) {
    if (!atom || typeof atom !== 'object') return '';
    const skipped = new Set(['id', 'left', 'operator', 'right', 'evidence_kind']);
    return Object.entries(atom)
      .filter(([key, value]) => !skipped.has(key) && hasDisplayValue(value))
      .map(([key, value]) => `${defaultLabelForKey(key)}: ${formatScalar(value)}`)
      .join('; ');
  }

  function conditionElementsHtml(atoms, fallback) {
    if (Array.isArray(atoms) && atoms.length) {
      return `<ul class="condition-elements-list">${atoms
        .map((atom) => {
          const meta = atomMeta(atom);
          return `<li><span>${esc(atomSummary(atom))}</span>${meta ? `<div class="condition-element-meta">${esc(meta)}</div>` : ''}</li>`;
        })
        .join('')}</ul>`;
    }

    const fallbackLines = String(fallback || '')
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (fallbackLines.length) {
      return `<ul class="condition-elements-list">${fallbackLines.map((line) => `<li><span>${esc(line)}</span></li>`).join('')}</ul>`;
    }
    return '-';
  }

  function separatorRow(label) {
    return `<tr class="inspector-separator"><th colspan="2">${esc(label)}</th></tr>`;
  }

  function valueRow(label, key, value, row, formatValue) {
    return `<tr><th>${esc(label)}</th><td>${esc(formatValue(key, value, row))}</td></tr>`;
  }

  function htmlRow(label, html) {
    return `<tr><th>${esc(label)}</th><td>${html}</td></tr>`;
  }

  function renderInspectorRows(row, options = {}) {
    const getRowValue = options.getRowValue || defaultGetRowValue;
    const formatValue = options.formatValue || defaultFormatValue;
    const labelForKey = options.labelForKey || defaultLabelForKey;
    const config = options.config || {};
    const excludedFields = new Set([...(Array.isArray(config.excludedFields) ? config.excludedFields : DEFAULT_EXCLUDED_FIELDS)]);
    const basicHeader = config.basicSeparatorText || '- Basic Details -';
    const parsedHeader = config.separatorText || '- Parsed Details -';
    const conditionHeader = config.conditionSeparatorText || '- Condition Details -';
    const workloadHeader = config.workloadSeparatorText || '- Workload Principal Match -';

    const rows = [separatorRow(basicHeader)];
    buildBasicFieldOrder(config).forEach((key) => {
      if (excludedFields.has(key)) return;
      const value = fieldValue(row, key, getRowValue);
      if (!shouldShowBasicField(row, key, value, getRowValue)) return;
      rows.push(valueRow(labelForKey(key), key, value, row, formatValue));
    });

    const rawCondition = conditionRawValue(row, getRowValue);
    rows.push(separatorRow(parsedHeader));
    buildParsedFieldOrder(config).forEach((key) => {
      if (excludedFields.has(key) && key !== 'conditions_where_clause') return;
      const value = key === 'conditions_where_clause' ? rawCondition : fieldValue(row, key, getRowValue);
      if (key !== 'conditions_where_clause' && !hasDisplayValue(value)) return;
      const label = key === 'conditions_where_clause' ? 'Conditions (Where Clause)' : labelForKey(key);
      rows.push(valueRow(label, key, value, row, formatValue));
    });

    if (String(rawCondition || '').trim()) {
      rows.push(separatorRow(conditionHeader));
      rows.push(valueRow('Raw Text', 'conditions_where_clause', rawCondition, row, formatValue));
      rows.push(valueRow('Parsed Structure', 'conditions_parsed_structure', conditionStructureValue(row, getRowValue), row, formatValue));
      rows.push(
        htmlRow(
          'Condition Elements',
          conditionElementsHtml(conditionAtomsValue(row, getRowValue), conditionElementsFallbackValue(row, getRowValue))
        )
      );
    }

    const matchConfidence = matchConfidenceValue(row, getRowValue);
    if (hasDisplayValue(matchConfidence)) {
      rows.push(separatorRow(workloadHeader));
      rows.push(valueRow('Match Confidence', 'match_confidence', matchConfidence, row, formatValue));
      const reason = matchReasonValue(row, getRowValue);
      if (hasDisplayValue(reason)) rows.push(valueRow('Reason', 'match_confidence_reason', reason, row, formatValue));
      rows.push(htmlRow('Principal Evidence', conditionElementsHtml(principalEvidenceValue(row, getRowValue), '')));
      rows.push(htmlRow('Residual Conditions', conditionElementsHtml(residualConditionsValue(row, getRowValue), '')));
    }

    return rows.join('');
  }

  const DYNAMIC_GROUP_BASIC_FIELDS = [
    ['Domain', ['Domain', 'domain_name']],
    ['DG Name', ['DG Name', 'dynamic_group_name']],
    ['Description', ['Description', 'description']],
    ['In Use', ['In Use', 'in_use']],
    ['DG OCID', ['DG OCID', 'dynamic_group_ocid']],
    ['DG ID', ['DG ID', 'dynamic_group_id']],
    ['Domain OCID', ['Domain OCID', 'domain_ocid']],
    ['Creation Time', ['Creation Time', 'creation_time']],
    ['Created By', ['Created By', 'created_by_name']],
    ['Created By OCID', ['Created By OCID', 'created_by_ocid']],
  ];
  const DYNAMIC_GROUP_RULE_RAW_KEYS = ['Matching Rule', 'matching_rule'];
  const DYNAMIC_GROUP_RULE_STRUCTURE_KEYS = [
    'Matching Rule (parsed structure)',
    'matching_rule_parsed_structure',
    'Rule Structure',
  ];
  const DYNAMIC_GROUP_RULE_OBJECT_KEYS = ['matching_rule_structure', 'Matching Rule Structure'];
  const DYNAMIC_GROUP_RULE_ELEMENT_KEYS = ['Matching Rule (elements)', 'matching_rule_elements'];

  function dynamicGroupRuleStructureObject(row, getRowValue) {
    return readFirst(row, DYNAMIC_GROUP_RULE_OBJECT_KEYS, getRowValue);
  }

  function dynamicGroupRuleStructureValue(row, getRowValue) {
    const summary = readFirst(row, DYNAMIC_GROUP_RULE_STRUCTURE_KEYS, getRowValue);
    if (hasDisplayValue(summary)) return summary;

    const structure = dynamicGroupRuleStructureObject(row, getRowValue);
    if (!structure || typeof structure !== 'object') return '';
    const status = String(structure.parse_status || '').trim();
    const label = String(structure.structure || '').trim();
    const atoms = Array.isArray(structure.atoms) ? structure.atoms.length : 0;
    if (status && label && atoms) return `${status}: ${label} (${atoms} atom${atoms === 1 ? '' : 's'})`;
    if (status && label) return `${status}: ${label}`;
    return status || label;
  }

  function dynamicGroupRuleAtomsValue(row, getRowValue) {
    const structure = dynamicGroupRuleStructureObject(row, getRowValue);
    if (structure && typeof structure === 'object' && Array.isArray(structure.atoms)) return structure.atoms;
    const direct = readFirst(row, ['rule_atoms', 'matching_rule_atoms'], getRowValue);
    return parseJsonArray(direct);
  }

  function dynamicGroupRuleElementsFallbackValue(row, getRowValue) {
    return readFirst(row, DYNAMIC_GROUP_RULE_ELEMENT_KEYS, getRowValue);
  }

  function renderDynamicGroupInspectorRows(row, options = {}) {
    const getRowValue = options.getRowValue || defaultGetRowValue;
    const formatValue = options.formatValue || defaultFormatValue;
    const basicHeader = options.basicSeparatorText || '- Basic Details -';
    const parsedHeader = options.parsedSeparatorText || '- Parsed Rules -';

    const rows = [separatorRow(basicHeader)];
    DYNAMIC_GROUP_BASIC_FIELDS.forEach(([label, keys]) => {
      const value = readFirst(row, keys, getRowValue);
      if (!hasDisplayValue(value)) return;
      rows.push(valueRow(label, keys[0], value, row, formatValue));
    });

    rows.push(separatorRow(parsedHeader));
    rows.push(valueRow('Matching Rule', 'matching_rule', readFirst(row, DYNAMIC_GROUP_RULE_RAW_KEYS, getRowValue), row, formatValue));
    rows.push(valueRow('Parsed Structure', 'matching_rule_structure', dynamicGroupRuleStructureValue(row, getRowValue), row, formatValue));
    rows.push(
      htmlRow(
        'Rule Conditions (atoms)',
        conditionElementsHtml(
          dynamicGroupRuleAtomsValue(row, getRowValue),
          dynamicGroupRuleElementsFallbackValue(row, getRowValue)
        )
      )
    );

    return rows.join('');
  }

  window.renderPolicyStatementInspectorRows = renderInspectorRows;
  window.renderDynamicGroupInspectorRows = renderDynamicGroupInspectorRows;

  window.createPolicyStatementInspector = function createPolicyStatementInspector(options = {}) {
    const {
      panel,
      titleEl,
      subtitleEl,
      emptyEl,
      tableEl,
      tableBodyEl,
      layoutEl,
      rowSelector = '#resultsTable tbody tr',
      rowIdAttr = 'rowId',
      rowIdGetter,
      getRowValue = defaultGetRowValue,
      formatValue = defaultFormatValue,
      labelForKey = defaultLabelForKey,
      config = {},
      onSelectionChange,
      copyConfig = {},
    } = options;

    let selectedRow = null;

    function rowIdFor(row) {
      if (!row) return '';
      if (typeof rowIdGetter === 'function') return String(rowIdGetter(row) ?? '');
      return String(row?._row_id ?? '');
    }

    function syncActiveRows(row) {
      const selectedId = rowIdFor(row);
      document.querySelectorAll(rowSelector).forEach((tr) => {
        const id = String(tr?.dataset?.[rowIdAttr] ?? '');
        tr.classList.toggle('active-row', Boolean(selectedId) && id === selectedId);
      });
    }

    function render(row) {
      if (!tableBodyEl || !tableEl || !panel || !emptyEl) return;

      if (!row) {
        panel.classList.remove('open');
        if (layoutEl) layoutEl.classList.remove('has-selection');
        emptyEl.style.display = 'block';
        tableEl.style.display = 'none';
        return;
      }

      panel.classList.add('open');
      if (layoutEl) layoutEl.classList.add('has-selection');
      emptyEl.style.display = 'none';
      tableEl.style.display = 'table';

      if (titleEl && config.titleWhenSelected) {
        titleEl.textContent = String(config.titleWhenSelected);
      }
      if (subtitleEl && config.subtitleWhenSelected) {
        subtitleEl.textContent = String(config.subtitleWhenSelected);
      }

      tableBodyEl.innerHTML = renderInspectorRows(row, {
        getRowValue,
        formatValue,
        labelForKey,
        config,
      });
    }

    function setInspector(row) {
      selectedRow = row || null;
      syncActiveRows(selectedRow);
      render(selectedRow);
      if (typeof onSelectionChange === 'function') onSelectionChange(selectedRow);
    }

    function clear() {
      setInspector(null);
    }

    function getSelectedRow() {
      return selectedRow;
    }

    async function copyStatement() {
      if (!selectedRow) return false;
      const key = String(copyConfig.statementKey || 'statement_text');
      const text = String(getRowValue(selectedRow, key) || '');
      if (!text.trim()) return false;
      await navigator.clipboard.writeText(text);
      return true;
    }

    async function copySummary() {
      if (!selectedRow) return false;
      const fields = Array.isArray(copyConfig.summaryFields) && copyConfig.summaryFields.length
        ? copyConfig.summaryFields
        : [
            ['Policy', 'policy_name'],
            ['Verb', 'verb'],
            ['Resource', 'resource'],
            ['Compartment', 'compartment_path'],
            ['Statement', 'statement_text'],
          ];
      const text = fields
        .map(([label, key]) => `${label}: ${String(getRowValue(selectedRow, key) || '-')}`)
        .join('\n');
      await navigator.clipboard.writeText(text);
      return true;
    }

    return {
      setInspector,
      clear,
      getSelectedRow,
      getRowValue,
      copyStatement,
      copySummary,
    };
  };
})();
