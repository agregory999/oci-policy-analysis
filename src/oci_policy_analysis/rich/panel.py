class Panel:
    def __init__(self, renderable=None, *args, **kwargs):
        self.renderable = renderable

    def __str__(self):
        return str(self.renderable) if self.renderable is not None else ''
