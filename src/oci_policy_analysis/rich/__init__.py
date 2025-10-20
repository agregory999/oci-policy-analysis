# minimal Rich replacement so FastMCP can import without Rich installed
from .align import Align  # noqa: F401
from .console import Console, Group  # noqa: F401
from .logging import RichHandler  # noqa: F401
from .panel import Panel  # noqa: F401
from .table import Table  # noqa: F401
from .text import Text  # noqa: F401


def get_console(*args, **kwargs) -> Console:
    return Console()


def print(*args, **kwargs):
    __builtins__['print'](*args, **kwargs)
