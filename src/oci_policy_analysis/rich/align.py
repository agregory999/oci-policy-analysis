class Align:
    def __init__(self, renderable=None, *args, **kwargs):
        self.renderable = renderable

    def __str__(self):
        return str(self.renderable) if self.renderable is not None else ''

    @classmethod
    def center(cls, renderable=None, *args, **kwargs):
        """Mimic Rich Align.center classmethod."""
        return cls(renderable)
