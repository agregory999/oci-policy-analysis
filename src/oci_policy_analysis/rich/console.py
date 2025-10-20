class Console:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        print(*args)

    def log(self, *args, **kwargs):
        print(*args)

    def rule(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Group(list):
    def __init__(self, *items):
        super().__init__(items)

    def __str__(self):
        return '\n'.join(str(i) for i in self)
