from logging import getLogger, StreamHandler, DEBUG

_handler = StreamHandler()
_handler.setLevel(DEBUG)
logger = getLogger(__name__)
logger.setLevel(DEBUG)
logger.addHandler(_handler)
logger.propagate = False
