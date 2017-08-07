from .settings_base import *

DEBUG = False

LOGGING['loggers'] = {
    '': {
        'handlers': ['file'],
        'level': 'INFO',
        'propagate': True,
    },
}
