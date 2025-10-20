class Text(str):
    """Simplified stand-in for rich.text.Text"""

    def __new__(cls, content='', *args, **kwargs):
        return str.__new__(cls, content)
