/* Shared table behaviors for static pages.
 * - Opt-in per table
 * - Column drag resize via header handles
 * - Optional localStorage persistence
 */
(function initSharedTable(globalScope) {
  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function makeStorageKey(table, key) {
    if (key) return `oci-table-widths:${key}`;
    if (table?.id) return `oci-table-widths:${table.id}`;
    return '';
  }

  function readPersistedWidths(storageKey) {
    if (!storageKey) return null;
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch {
      return null;
    }
  }

  function writePersistedWidths(storageKey, widths) {
    if (!storageKey) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(widths || {}));
    } catch {
      // no-op
    }
  }

  function enableResizableColumns(table, opts = {}) {
    if (!table || table.dataset.resizableColumnsBound === 'true') return null;

    const minWidth = Number(opts.minWidth ?? 90);
    const maxWidth = Number(opts.maxWidth ?? 1200);
    const persist = opts.persist !== false;
    const storageKey = persist ? makeStorageKey(table, opts.storageKey) : '';
    const thead = table.tHead;
    const firstHeadRow = thead?.rows?.[0];
    if (!firstHeadRow) return null;

    table.classList.add('resizable-table-enabled');

    const ths = [...firstHeadRow.cells];
    const widths = {};

    const persisted = readPersistedWidths(storageKey) || {};
    ths.forEach((th, idx) => {
      const key = String(idx);
      const currentRectWidth = Math.round(th.getBoundingClientRect().width || th.offsetWidth || minWidth);
      const initial = clamp(Number(persisted[key] || currentRectWidth), minWidth, maxWidth);
      th.style.width = `${initial}px`;
      th.style.minWidth = `${minWidth}px`;
      th.style.maxWidth = `${maxWidth}px`;
      widths[key] = initial;

      const handle = document.createElement('span');
      handle.className = 'table-col-resize-handle';
      handle.setAttribute('role', 'separator');
      handle.setAttribute('aria-orientation', 'vertical');
      handle.setAttribute('aria-label', `Resize column ${th.textContent?.trim() || idx + 1}`);
      th.classList.add('resizable-th');
      th.appendChild(handle);

      let startX = 0;
      let startW = 0;
      let dragging = false;
      const onMove = (evt) => {
        if (!dragging) return;
        const delta = evt.clientX - startX;
        const next = clamp(Math.round(startW + delta), minWidth, maxWidth);
        th.style.width = `${next}px`;
        widths[key] = next;
      };
      const onUp = () => {
        dragging = false;
        document.body.classList.remove('col-resize-active');
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        writePersistedWidths(storageKey, widths);
      };

      handle.addEventListener('pointerdown', (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        dragging = true;
        startX = evt.clientX;
        startW = Math.round(th.getBoundingClientRect().width || th.offsetWidth || minWidth);
        document.body.classList.add('col-resize-active');
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
      });

      // Fallback for environments where Pointer Events are limited.
      handle.addEventListener('mousedown', (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        dragging = true;
        startX = evt.clientX;
        startW = Math.round(th.getBoundingClientRect().width || th.offsetWidth || minWidth);
        document.body.classList.add('col-resize-active');
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      });

      handle.addEventListener('dblclick', () => {
        delete widths[key];
        th.style.width = '';
        writePersistedWidths(storageKey, widths);
      });

      handle.addEventListener('click', (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
      });
    });

    table.dataset.resizableColumnsBound = 'true';
    table.dataset.resizableColumnsReady = 'true';
    return {
      reset() {
        ths.forEach((th) => {
          th.style.width = '';
        });
        if (storageKey) {
          try {
            window.localStorage.removeItem(storageKey);
          } catch {
            // no-op
          }
        }
      },
    };
  }

  globalScope.SharedTable = {
    enableResizableColumns,
  };
})(window);
