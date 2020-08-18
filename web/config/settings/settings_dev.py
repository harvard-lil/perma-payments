from .settings_base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'k2#@_q=1$(__n7#(zax6#46fu)x=3&^lz&bwb8ol-_097k_rj5'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

ADMIN_ENABLED = True
ADMIN_URL = 'admin/'

PERMA_URL = 'http://perma.test:8000'
PERMA_SUBSCRIPTION_CANCELED_REDIRECT_URL = 'http://perma.test:8000/settings/subscription/'

# This key is just for local development, and is safe to commit to the repo
STORAGE_ENCRYPTION_KEYS = {
    'id': 1,
    'vault_public_key': 'BfRkGEQ8j02ItW4wXtNbuWb+l75e5gHlaq75/9ZyXm8='
}

# These keys are just for local development, and are safe to commit to the repo
PERMA_ENCRYPTION_KEYS = {
    'id': 1,
    'perma_payments_secret_key': "aZl8CDslsIkIF9IAO6KKk5LyGzSXKZ+Vhs2ck+lXKKA=",
    'perma_payments_public_key': "FhfWRc3QmLzG9SY+QwvTNMT9vcACNzpcMyvNSxKg0jA=",
    'perma_public_key': "+Y3Kni4Pm+5kWFJgsBL28TyKcgciQdPofRsTwUKaVSE="
}
# matching keys for use by the local instance of Perma
# PERMA_PAYMENTS_ENCRYPTION_KEYS = {
#     'id': 1,
#     'perma_secret_key': "hneZHHft4QieiNmyVPfyYFJs3toRgixbiTqSQKJ1r2E=",
#     'perma_public_key': "+Y3Kni4Pm+5kWFJgsBL28TyKcgciQdPofRsTwUKaVSE=",
#     'perma_payments_public_key': "FhfWRc3QmLzG9SY+QwvTNMT9vcACNzpcMyvNSxKg0jA="
# }


# CyberSource creds
CS_ACCESS_KEY = 'fake'
CS_PROFILE_ID = 'fake'
CS_SECRET_KEY = 'a-really-long-fake-string'
