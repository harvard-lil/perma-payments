# copied to settings.py by .travis.yml:

from .settings_testing import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'travisci',
        'USER': 'postgres',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '',
    }
}

# disable ssl to avoid postgres connection error for pytest
DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS']['sslmode'] = 'disable'
