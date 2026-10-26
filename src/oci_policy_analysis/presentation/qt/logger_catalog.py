"""Discover application logger declarations without importing optional interfaces."""

import ast
import logging
from functools import lru_cache
from pathlib import Path

from oci_policy_analysis.application.services.logging_service import CANONICAL_COMPONENT_ALIASES


@lru_cache(maxsize=1)
def declared_components() -> frozenset[str]:
    """Find literal get_logger declarations in installed Python package sources.

    Returns:
        frozenset[str]: Application components, including unloaded Tk/web/MCP
        modules. Reading source avoids importing their optional dependencies.
    """
    components = {alias for aliases in CANONICAL_COMPONENT_ALIASES.values() for alias in aliases}
    root = Path(__file__).parents[2]
    for path in root.rglob('*.py'):
        if {'generated', 'condition_parser', 'policy_parser'} & set(path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'get_logger':
                continue
            argument = next(
                (kw.value for kw in node.keywords if kw.arg == 'component'), node.args[0] if node.args else None
            )
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                components.add(argument.value)
    return frozenset(components)


def available_components(settings: dict) -> list[str]:
    """Merge declared, persisted, and currently registered component names.

    Args:
        settings: Effective logging configuration with canonical component keys.

    Returns:
        list[str]: Sorted logger names; application names omit the common prefix.
    """
    prefix = 'oci-policy-analysis.'
    components = set(declared_components()) | set(settings.get('log_levels') or {})
    for name, logger in list(logging.root.manager.loggerDict.items()):
        if isinstance(logger, logging.Logger):
            components.add(name.removeprefix(prefix) if name.startswith(prefix) else name)
    return sorted(components)
