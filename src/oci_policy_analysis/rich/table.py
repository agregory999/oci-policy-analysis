class Table:
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def grid(cls, *args, **kwargs):
        """Return a dummy Table for Rich Table.grid() calls."""
        return cls()

    def add_column(self, *args, **kwargs):
        pass

    def add_row(self, *args, **kwargs):
        pass

    def __str__(self):
        return ''
