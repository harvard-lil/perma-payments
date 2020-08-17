from .settings_base import *

DEBUG = False

LOGGING['loggers'] = {
    '': {
        'handlers': ['file'],
        'level': 'INFO',
        'propagate': True,
    },
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST = 'smtp.example.com'
EMAIL_HOST_USER = 'smtpuser'
EMAIL_HOST_PASSWORD = 'smtppw'
