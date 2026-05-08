/* Shared display helpers for static analysis pages. */
(function initSharedFormatters(globalScope) {
  function formatMatchingRuleByComma(value) {
    const raw = String(value ?? '').trim();
    if (!raw) return '';
    return raw
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
      .join(',\n');
  }

  globalScope.SharedFormatters = {
    formatMatchingRuleByComma,
  };
})(window);
