# Project-Specific Context: Testing

This file outlines the rules, recommendations, and history for test coverage and test development in this repository. Use it to verify all new or changed logic is backed by robust, appropriate tests and follows local conventions.

---

## 1. Area Overview

All automated tests live in `src/test/` and are organized by major feature or module. Tests include:
- Unit tests for logic modules
- Integration/system tests for critical flows or cross-module behavior
- (Add UI or API tests here if/when added in the future)

---

## 2. Test Practices and Evolution

- All new modules must include matching or updated tests in `src/test/`
- Historical test focus: policy parsing, statement normalization, core analytical engines
- Test framework(s) used: `pytest`, (expand if new ones are added)

---

## 3. Local Testing Rules

- PRs are **blocked** unless new code is fully tested or is accompanied by a written justification (document here if exception made)
- Test classes/functions follow `test_*` naming where applicable
- Pytest fixtures, mocks, and coverage requirements are documented as new modules/features are added

---

## 4. Differences from Generic Guidelines

- Project may add coverage thresholds, stricter test naming, or mandate integration test for certain packages; always update this file with such changes
- Any CI/CD hooks for tests (or extra test stages in pre-commit/push hooks) are described here

---

For universal patterns and checklist, see [../generic/GENERIC_CODING_STANDARDS.md](../generic/GENERIC_CODING_STANDARDS.md).
