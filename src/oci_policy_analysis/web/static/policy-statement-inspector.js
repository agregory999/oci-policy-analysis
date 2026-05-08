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

  function defaultLabelForKey(key) {
    return String(key || '')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function buildOrderedKeys(row, config) {
    const primaryFieldOrder = Array.isArray(config.primaryFieldOrder)
      ? config.primaryFieldOrder
      : ['compartment_path', 'policy_name', 'policy_ocid', 'effective_path', 'statement_text'];
    const parsedFieldOrder = Array.isArray(config.parsedFieldOrder)
      ? config.parsedFieldOrder
      : [
          'action',
          'subject_type',
          'subject',
          'principals',
          'verb',
          'resource',
          'permission',
          'location',
          'conditions',
          'valid',
          'invalid_reasons',
          'parsed',
          'comments',
        ];

    const excludedFields = new Set(Array.isArray(config.excludedFields) ? config.excludedFields : ['_row_id', 'internal_id', 'effective_compartment_ocid']);
    const keySet = new Set([...primaryFieldOrder, ...parsedFieldOrder]);
    Object.keys(row || {}).forEach((key) => {
      if (!excludedFields.has(key)) keySet.add(key);
    });

    const orderedPrimary = primaryFieldOrder.filter((key) => keySet.has(key));
    const orderedParsed = parsedFieldOrder.filter((key) => keySet.has(key));
    const orderedOther = [
      ...Array.from(keySet)
        .filter((key) => !primaryFieldOrder.includes(key) && !parsedFieldOrder.includes(key))
        .sort((a, b) => a.localeCompare(b)),
    ];

    const includeSeparator = config.includeParsedSeparator !== false;
    if (!includeSeparator) return [...orderedPrimary, ...orderedParsed, ...orderedOther];
    return [...orderedPrimary, '__separator_parsed__', ...orderedParsed, ...orderedOther];
  }

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

      const orderedKeys = buildOrderedKeys(row, config);
      const separatorText = config.separatorText || '- Parsed Details -';
      tableBodyEl.innerHTML = orderedKeys
        .map((key) => {
          if (key === '__separator_parsed__') {
            return `<tr class="inspector-separator"><th colspan="2">${esc(separatorText)}</th></tr>`;
          }
          const rawValue = getRowValue(row, key);
          const formatted = formatValue(key, rawValue, row);
          return `<tr><th>${esc(labelForKey(key))}</th><td>${esc(formatted)}</td></tr>`;
        })
        .join('');
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