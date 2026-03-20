# Generic Context: Documentation

This file defines **project-wide documentation strategies, file conventions, and coding/documentation best practices** for this repository. All contributors should ensure code, features, and modules are documented according to these standards.

---

## 1. Documentation Strategy Overview

### Types of Documentation
- **Markdown docs** under `docs/source/` for conceptual information, overviews, usage guides, and UI/architecture explanations.
- **API Reference** documentation generated using [Sphinx](https://www.sphinx-doc.org) (reStructuredText, `index.rst`, `.rst` for modules/classes), automatically pulled from inline docstrings.
- **Context Files**: Every key technical area, domain, or project-specific feature gets its own CONTEXT or GENERIC markdown explainer for background, design rationales, and nuanced guideposts.

### Organization
- All user-facing features and docs must be **discoverable and linked** from `docs/source/index.rst`.
- Use [relative references](https://www.sphinx-doc.org/en/master/usage/restructuredtext/roles.html#ref-role) and explicit cross-links, for example:  
  ```
  See [Generic Coding Standards](GENERIC_CODING_STANDARDS.md)
  ```
- Visual aids, diagrams, or extra materials should go in `docs/source/` or `docs/source/_static/` as appropriate.

---

## 2. Building and Evolving Documentation

- **Every major feature or refactor must include/update context files, usage guides, and index links.**
- Document revision history is cross-referenced in `CHANGELOG.md` and in doc comments where appropriate.
- All architecture or UI diagrams must be kept updated after structural changes.

---

## 3. Sphinx & API Reference Practices

- **Sphinx** builds API docs: use reStructuredText (`.rst`) for module/class documentation; `index.rst` acts as a top-level table of contents.
- **Docstring Style:** Use [Google-style docstrings](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html) (Napoleon-compatible).
- **Location:** Every *public class, function, or module* must have a clear docstring. Internal/private APIs may summarize or reference the public interface.
- **Napoleon Extension:** `conf.py` must enable Napoleon to interpret both Google and NumPy style docstrings seamlessly.

---

## 4. Context File Patterns

- Each major code, UX, or logic domain should have a `CONTEXT_*.md` file (for project-specifics) or `GENERIC_*.md` (for general patterns) under `docs/source/context/`.
- Contents to include:
  - Motivation and background
  - Key conventions and reasoning
  - Cross-links to API/reference/entry points
  - Special cases or explicit deviations from global standards

---

## 5. Self-Documenting Code & Organization Patterns

- **Google-style docstrings** for every class, function, and module. Eg:
  ```python
  def foo(x):
      """
      Short summary.

      Args:
          x (int): the foo argument

      Returns:
          int: description of the return value
      """
  ```
- **Function & Class Organization**
  - Group related functionality into packages (`src/oci_policy_analysis/[domain]/`)
  - Use `__init__.py` in every package. Only expose intended public APIs in `__init__.py` to maintain encapsulation.
- **Public API Control:**  
  - Limit `from <module> import *` usage; define `__all__` where appropriate.
  - Keep the top-level `__init__.py` descriptive and minimal, aggregating only canonical APIs.
- **Imports & Style:**  
  - [Follow generic coding standards →](GENERIC_CODING_STANDARDS.md)
  - Organize imports logically: stdlib, third-party, intra-repo.
- **Ease of Navigation:**  
  - Maintain clear navigation/routing in Sphinx index and API docs.
  - Ensure all users can locate how-to guides, references, and rationale docs from the main doc site.

---

## 6. Best Practices Summary

- Prefer writing for future teammates—document *why* as well as *what/how*.
- Regularly review and update documentation for correctness after code or UI changes.
- Use explicit type hints in code to help auto-generators (Sphinx, IDE help, CI validation).
- Document edge cases and limitations at both code and documentation level.
- All new code must be accompanied by appropriate documentation and references in relevant context files.

---

_See also: [Generic Coding Standards](GENERIC_CODING_STANDARDS.md) and [README.md](../../../../README.md) for further guidance._