"""Maintained Tkinter desktop application for the 7.0 release line."""


def main() -> None:
    """Launch the Tkinter desktop application."""
    from .main import main as run

    run()


def __getattr__(name: str):
    """Load the Tk application lazily for compatibility with headless imports."""
    if name == 'App':
        from .main import App

        return App
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = ['App', 'main']
