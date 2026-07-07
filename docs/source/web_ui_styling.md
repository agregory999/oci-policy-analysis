# Web UI Styling Guide

This page defines practical styling/documentation conventions for static web UI pages in:

- `src/oci_policy_analysis/web/static/*.html`
- `src/oci_policy_analysis/web/static/app.css`

It complements Sphinx/Python docs by documenting how HTML/CSS should be written so pages are self-explanatory and easy to maintain.

## Goals

- Keep styling and page structure **predictable** across analysis pages.
- Make HTML and CSS **self-documenting** with readable comment landmarks.
- Reuse shared classes from `app.css` rather than introducing one-off styles.

## CSS documentation conventions

Use layered comments in `app.css`:

1. **File header**: scope, source-of-truth statement, and naming conventions.
2. **Section banners**: major blocks (tokens, forms, layout, inspector, responsive).
3. **Component contracts**: short comments above reusable classes describing purpose and expected usage.

Example:

```text
/* Card container used by all pages. Expected children: title/body/actions. */
.card {
  ...
}
```

## HTML documentation conventions

For each page, add structural comments that mirror the visual hierarchy:

- `<!-- Masthead + Context Help -->`
- `<!-- Main Workspace -->`
- `<!-- Left: Data Operations -->`
- `<!-- Right Rail: Status + Navigation -->`
- `<!-- Page Script: state, API calls, event wiring -->`

Use these comments as navigation landmarks for future maintainers.

## Naming conventions

- Prefer semantic names: `*-grid`, `*-row`, `*-panel`, `*-title`, `*-meta`.
- Avoid purely visual names tied to color/position.
- Keep IDs for JavaScript hooks; keep classes for presentation.

## Reuse-first rules

- Reuse `app.css` patterns first (`.card`, `.layout-*`, `.status-*`, `.progress-widget`, etc.).
- Add new classes to `app.css` only when a pattern is reusable or clearly scoped.
- Avoid inline `style=` and page-local `<style>` for shared UI behavior.

## Context help pattern

Interactive controls should provide contextual guidance through data attributes:

```html
<button
  data-help-title="Load from Tenancy"
  data-help-body="Runs tenancy load with selected profile and options."
>
  Load from Tenancy
</button>
```

Use one page-level helper to bind hover/focus events and update a shared help card.

## Recommended checklist for new pages

1. Start from a template (`template-single-column.html`, `template-two-column.html`, or `template-three-column.html`).
2. Add structural HTML comments for major sections.
3. Reuse existing `app.css` classes.
4. Add `data-help-title` / `data-help-body` for primary controls.
5. If new reusable styles are needed, add them to `app.css` with section and component comments.
