import logging


class RichHandler(logging.StreamHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def emit(self, record):
        super().emit(record)
