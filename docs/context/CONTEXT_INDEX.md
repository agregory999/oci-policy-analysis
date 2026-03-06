# Context Files Index for OCI Policy Analysis

This directory organizes foundational **context files** to enforce and document standards, best practices, and history for this project and for general OCI/Python applications.

---

## Directory Structure

- `generic/`: Generic, reusable standards for any similar "OCI App" or Python/Oci project
- `project/`: Project-specific guidelines, history, and conventions unique to **this** repository

---

## Usage Instructions (for Cline & Contributors)

1. **Consult `generic/` first** for universal patterns:
   - Coding standards
   - UI/logic patterns
   - Lint & commit strategies (e.g., Ruff, pre-commit, semantic versioning)
2. **Then overlay with `project/` context** for repository-specific requirements:
   - Folder structure, file conventions, custom hooks, etc.
3. **If there is any discrepancy, favor `project/` conventions.**
4. **Keep both sets up to date; escalate to maintainers if you’re unsure.**

---

## Index

**Generic context:**
- [GENERIC_README.md](generic/GENERIC_README.md)
- [GENERIC_UI_GUIDELINES.md](generic/GENERIC_UI_GUIDELINES.md)
- [GENERIC_CODING_STANDARDS.md](generic/GENERIC_CODING_STANDARDS.md)

**Project-specific context:**
- [CONTEXT_logic.md](project/CONTEXT_logic.md)
- [CONTEXT_ui.md](project/CONTEXT_ui.md)
- [CONTEXT_config.md](project/CONTEXT_config.md)
- [CONTEXT_docs.md](project/CONTEXT_docs.md)
- [CONTEXT_tests.md](project/CONTEXT_tests.md)
- [CONTEXT_simulation_engine.md](project/CONTEXT_simulation_engine.md)

---

## Cline Agent Usage

When generating, modifying, or reviewing code:
- **Read the relevant GENERIC file.**
- **Read the relevant PROJECT file.**
- Merge requirements, then proceed with implementation or review.

Example:
> "Adding a new UI tab? First review GENERIC_UI_GUIDELINES, then CONTEXT_ui.md for project specifics. Follow project overrides where they exist."
