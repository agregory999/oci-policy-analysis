# Copilot Instructions for OCI Policy Analysis

## Project Overview

OCI Policy Analysis is a Python desktop application and MCP server for analyzing Oracle Cloud Infrastructure (OCI) IAM policies, identity domains, and dynamic groups. It helps administrators understand, audit, and manage OCI access policies.

## Technology Stack

- **Python 3.12+** - Required minimum version
- **Tkinter** - Desktop UI framework (standard library)
- **OCI SDK** (`oci`) - Oracle Cloud Infrastructure SDK for Python
- **FastMCP** - Model Context Protocol server implementation
- **DeepDiff** - For comparing policy changes over time
- **Ruff** - Linting and code formatting
- **PyInstaller** - For building standalone executables

## Project Structure

```
src/oci_policy_analysis/
├── __init__.py          # Package exports
├── main.py              # Main Tkinter application entry point
├── cli.py               # Command-line interface
├── mcp_server.py        # MCP server implementation
├── common/              # Shared utilities
│   ├── caching.py       # Cache management
│   ├── config.py        # Configuration handling
│   ├── helpers.py       # Helper functions
│   ├── logger.py        # Logging setup
│   └── models.py        # Data models
├── logic/               # Business logic
│   ├── ai_repo.py       # AI/GenAI integration
│   ├── data_repo.py     # Policy data repository
│   ├── diff_utils.py    # Diff utilities
│   ├── permissions/     # Permission reference data
│   └── reference_data_repo.py
└── ui/                  # Tkinter UI components
    ├── *_tab.py         # Individual tab implementations
    └── data_table.py    # Reusable table widget
```

## Coding Standards

### Code Style
- **Line length**: 120 characters maximum
- **Quote style**: Single quotes for strings
- **Indentation**: 4 spaces (no tabs)
- **Imports**: Organized with `isort` style (stdlib, third-party, local)

### Linting
- Use **Ruff** for linting: `ruff check src`
- Use **Ruff** for formatting: `ruff format src`
- Configuration is in `ruff.toml`
- Selected rule sets: E, W, F, I, B, C, UP

### Docstrings
- Use docstrings for all public classes and functions
- Follow Google-style docstring format
- Include type hints in function signatures

### Type Hints
- Use type hints for function parameters and return values
- Use `typing` module for complex types
- Prefer `| None` syntax over `Optional[]` (Python 3.10+)

## Development Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e .

# Run the application
python -m oci_policy_analysis
```

## Running Linters

```bash
# Check for issues
ruff check src

# Auto-fix issues
ruff check src --fix

# Format code
ruff format src
```

## Key Patterns

### Tkinter UI
- Each tab is a separate class inheriting from `ttk.Frame`
- Tabs are added to a `ttk.Notebook` widget
- Use `self.after()` for thread-safe UI updates
- Long-running operations should use `threading.Thread`

### Async Operations
- Use `asyncio` for async operations in MCP server
- UI operations must happen on the main thread
- Use `queue.Queue` for thread communication

### OCI SDK
- Authentication supports: config file profiles, instance principals, session tokens
- Always handle OCI service errors gracefully
- Cache API responses to avoid rate limiting

### Logging
- Use `from oci_policy_analysis.common.logger import get_logger`
- Create component-specific loggers: `logger = get_logger(component='module_name')`
- Log levels: DEBUG, INFO, WARNING, ERROR

## Build Process

The project uses GitHub Actions for CI/CD:
- **semantic-release** for versioning
- **PyInstaller** for creating standalone executables
- Builds are created for Linux, macOS, and Windows

## Important Notes

- This is a desktop application with no web framework
- OCI credentials are handled via the OCI SDK's standard config mechanisms
- Policy data can be cached locally as JSON files
- The MCP server allows AI assistants to query policy data
- Always consider that this tool handles sensitive IAM policy data
