# Generic Coding Standards and Quality Automation

This document establishes universal Python coding standards and quality automation practices for all OCI App and analytical Python projects derived from this repository’s ecosystem.

---

## Python Code Style

- Use PEP8 as a base with project-specific overrides (see Ruff config)
- 4-space indentation, max line length 120
- Descriptive names for all classes, functions, and variables
- Document all public APIs and complex logic paths
- Type annotations are strongly encouraged for all functions and methods

---

## Class and Function Organization Standard

To maximize clarity, consistency, and maintainability, adhere to the following class and method ordering and docstring standards in all Python code.

### Ordering and Layout

- **Imports:** All imports at the very top of the file (group standard library, third-party, and local/project imports).
- **Module docstring:** If present, goes before imports.
- **Constants/globals:** After imports.
- **Class definitions:** See "Class Structure" below.
- **Main/application code:** If present, place under `if __name__ == "__main__":` at end of file.

#### Class Structure

Every class should follow this canonical order:

1. **Class-level docstring:** Required (Google/Napoleon style), describing class purpose, __init__ args, and usage.
2. **`__init__` method:** Always the first method in the class.
3. **Public methods:** All public methods (no underscore prefix), ordered logically.
4. **Private methods:** (Start with single underscore) After public methods, grouped under a section comment.
5. **Section headers:** Use clearly marked comments to separate main sections for readability, e.g.,
   - `# --- Public Methods ---`
   - `# --- Private Methods ---`

#### Docstring Requirements

All public classes and functions must have complete docstrings using Google/Napoleon style.

**Class docstring example:**
```python
class Example:
    """Summary line for Example class.

    Detailed class docstring describing purpose and usage.

    Attributes:
        foo (str): Description of foo.
        bar (int): Description of bar.
    """

    def __init__(self, foo: str, bar: int) -> None:
        """Initializes Example.

        Args:
            foo (str): Description.
            bar (int): Description.
        """
        self.foo = foo
        self.bar = bar

    # --- Public Methods ---

    def do_something(self, baz: float) -> bool:
        """Does something important.

        Args:
            baz (float): The input value.
        Returns:
            bool: True if operation succeeded, False otherwise.
        """

    # --- Private Methods ---

    def _helper(self) -> None:
        """Helper for internal use."""
```

#### Checklist for Organization/Documentation (to be used alongside code reviews and cleaning)

- [ ] All imports at top, grouped correctly
- [ ] Module and class docstrings present and in Google/Napoleon style
- [ ] `__init__` is always the first method in each class
- [ ] Public methods before private methods
- [ ] Section headers separate public/private methods in multi-method classes
- [ ] Type annotations and descriptive names throughout
- [ ] All public APIs have substantive docstrings
- [ ] Passes Ruff and pre-commit checks

---

## Automated Linting and Formatting

- **Ruff**: All code must pass lint and autoformat checks via Ruff, using project/configured rules (see `ruff.toml`)
- Add Ruff as a pre-commit hook
- No code is merged unless it passes full lint suite

---

## Pre-commit Hooks

- Use `.pre-commit-config.yaml` to enforce:
    - Ruff lint/format
    - Remove trailing whitespace
    - Validate commit message style (see below)
- All contributors must install pre-commit, run `pre-commit install`, and locally fix issues before push

---

## Commit Messages and Semantic Versioning

- Enforce [Conventional Commits](https://www.conventionalcommits.org/) (e.g., `feat:`, `fix:`, `chore:`, `docs:`)
- Each merge to main branch updates the `CHANGELOG.md` and uses [semantic-release](https://semantic-release.gitbook.io/) (auto or manual) to bump version and publish

---

## Checklist for New Code

- [ ] Follows all above style/lint/commit message rules
- [ ] Follows class/function ordering and documentation standards
- [ ] Has docstrings for all public classes, functions, and methods (Google/Napoleon style)
- [ ] Passes pre-commit hooks
- [ ] Described in CHANGELOG with proper message

---

See also: [GENERIC_README.md](GENERIC_README.md) and local project overrides in [../project/CONTEXT_config.md](../project/CONTEXT_config.md).
