from .settings_base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'k2#@_q=1$(__n7#(zax6#46fu)x=3&^lz&bwb8ol-_097k_rj5'

# CyberSource creds
CS_ACCESS_KEY = 'test'
CS_PROFILE_ID = 'test'
CS_SECRET_KEY = 'a-really-long-test-string'

# Our encryption key for storing full responses from CyberSource
# generated using perma_payments.security.generate_public_private_keys
# SECURITY WARNING: keep the production vault public key secret!
# SECURITY WARNING: keep the production vault secret key offline!
STORAGE_ENCRYPTION_KEYS = {
    'id': 3,
    'vault_secret_key': 'Ey7hEYgLIkSDvxww/dAZqI97gP2FxCHJbxOwlvhZp9Y=',
    'vault_public_key': 'vTbhNI1CtazbldwuOj14aGK9rHd41RdHii+p9TibcFU=',
}


# Encryption keys for communicating with Perma.cc
# generated using perma_payments.security.generate_public_private_keys
# SECURITY WARNING: keep the production secret key secret!
PERMA_ENCRYPTION_KEYS = {
    'id': 3,
    'perma_payments_secret_key': 'N+Yj7wjkq8Ejacy0uQJ8F+SM1w4UbleWcbyZtfEzGEE=',
    'perma_payments_public_key': 'DG8o9cS5Lgeuu7XAF08sw0aOX7mJFu9TVEtdrrBQHDY=',
    'perma_public_key': 'ZmkWU6AdQlNrDCLNI154HSGH96jjs21UA3K+YpqezWg=',
}
PERMA_TIMESTAMP_MAX_AGE_SECONDS = 120

ADMINS = (
    ("Admin's Name", 'admin@example.com'),
)
