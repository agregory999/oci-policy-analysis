/* Shared display helpers for static analysis pages. */
(function initSharedFormatters(globalScope) {
  function pickFirstNonEmpty(values) {
    for (const value of values || []) {
      const text = String(value ?? '').trim();
      if (text) return text;
    }
    return '';
  }

  function extractPolicyName(row) {
    return pickFirstNonEmpty([
      row?.policy_name,
      row?.['Policy Name'],
      row?.policy,
      row?.name,
    ]);
  }

  function extractCompartmentPath(row) {
    return pickFirstNonEmpty([
      row?.statement_compartment_path,
      row?.compartment_path,
      row?.policy_path,
      row?.compartment,
      row?.['Policy Compartment'],
      row?.['Compartment Path'],
    ]);
  }

  function formatPolicyCompartmentName(row, options = {}) {
    const separator = String(options.separator ?? ' :: ');
    const empty = String(options.empty ?? '-');
    const path = extractCompartmentPath(row);
    const policy = extractPolicyName(row);
    if (path && policy) return `${path}${separator}${policy}`;
    return policy || path || empty;
  }

  function formatMatchingRuleByComma(value) {
    const raw = String(value ?? '').trim();
    if (!raw) return '';
    return raw
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
      .join(',\n');
  }

  function extractVerb(row) {
    return pickFirstNonEmpty([
      row?.verb,
      row?.['Verb'],
    ]);
  }

  function extractResource(row) {
    return pickFirstNonEmpty([
      row?.resource,
      row?.['Resource'],
    ]);
  }

  function extractPermission(row) {
    return pickFirstNonEmpty([
      row?.permission,
      row?.['Permission'],
    ]);
  }

  function formatPermissionList(value, options = {}) {
    const openBrace = String(options.openBrace ?? '{');
    const closeBrace = String(options.closeBrace ?? '}');
    const raw = String(value ?? '').trim();
    if (!raw) return '';
    const parts = raw
      .split(/[|,]/)
      .map((x) => String(x || '').trim())
      .filter(Boolean);
    if (parts.length > 1) {
      return `${openBrace}${parts.join(', ')}${closeBrace}`;
    }
    return raw;
  }

  function formatVerbResourcePermission(row, options = {}) {
    const joiner = String(options.joiner ?? ' / ');
    const empty = String(options.empty ?? '-');
    const verb = extractVerb(row);
    const resource = extractResource(row);
    const permissionRaw = extractPermission(row);
    const permission = formatPermissionList(permissionRaw, options);

    const verbResource = (verb && resource)
      ? `${verb} ${resource}`
      : (verb || resource || '');

    if (verbResource && permission) return `${verbResource}${joiner}${permission}`;
    return verbResource || permission || empty;
  }

  globalScope.SharedFormatters = {
    extractCompartmentPath,
    extractPolicyName,
    extractVerb,
    extractResource,
    extractPermission,
    formatPolicyCompartmentName,
    formatMatchingRuleByComma,
    formatPermissionList,
    formatVerbResourcePermission,
  };
})(window);
