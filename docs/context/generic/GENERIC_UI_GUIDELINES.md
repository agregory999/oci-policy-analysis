# Generic UI Guidelines for OCI/Python Applications

This document defines architectural and style guidelines for building high-quality, maintainable user interface components and tabs in any Python analytical/"OCI App" application.

---

## Folder and Module Structure

- Place all UI-related modules in a dedicated top-level folder, e.g., `src/[app_name]/ui/`
- Each screen/tab should use its own module, typically `X_tab.py` or in a subpackage for complex views
- Shared UI helpers and widgets belong in a `ui/common/` or similar

## Naming Conventions

- UI modules and their main classes/functions should match the tab name (`ResourcePrincipalsTab`, `PolicyOverlapTab`, etc.)
- Names should be descriptive and consistent — align with project or app domain language

## Interaction Patterns

- State should be clearly separated: business logic in logic modules, rendering in UI modules
- Pass data through clear APIs, not direct imports from business logic modules
- Use dependency injection or patterns that enable testing and reusability

## Code Review Checklist for New Tabs

- [ ] Module placed in correct UI package
- [ ] Descriptive, consistent naming
- [ ] Document any user-facing features or flows
- [ ] All user-interactions trigger testable, decoupled logic (not hard-coded side effects)
- [ ] Passes lint and formatting via Ruff and pre-commit
- [ ] Links (or references) in docs/context/project/CONTEXT_ui.md for any project-specific rules

---

Consult [GENERIC_README.md](GENERIC_README.md) for general project organization, and [docs/context/project/CONTEXT_ui.md](../project/CONTEXT_ui.md) for repository-specific UI rules and overrides.
