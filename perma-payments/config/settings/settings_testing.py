from .settings_base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'k2#@_q=1$(__n7#(zax6#46fu)x=3&^lz&bwb8ol-_097k_rj5'

# CyberSource creds
CS_ACCESS_KEY = 'test'
CS_PROFILE_ID = 'test'
CS_SECRET_KEY = 'a-really-long-test-string'
CS_PAYMENT_URL = 'https://testsecureacceptance.cybersource.com/pay'

# Our encryption key for storing full responses from CyberSource
# generated using perma_payments.security.generate_public_private_keys
# SECURITY WARNING: keep the production app secret key secret!
# SECURITY WARNING: keep the production vault secret key offline!
STORAGE_SECRET_KEY = {
    'id': 3,
    'app_secret_key': b'\xf8O\xbe\x18Y\xd0f\xd0\xe1\xcc\xd1\x07\xc9\xdd\x18]p\xc9\xae\xfd\xe6\x91\xf6\xf76\x8ae\x84\x991\xad\x9e',
    'vault_secret_key': b'\x13.\xe1\x11\x88\x0b"D\x83\xbf\x1c0\xfd\xd0\x19\xa8\x8f{\x80\xfd\x85\xc4!\xc9o\x13\xb0\x96\xf8Y\xa7\xd6',
    'app_public_key': b'V\xbc\xc4>\x00\x99\x93\x14\xe1E\x0c]\xfc\x1e\xaf\xb4|s\xec\xee\xfcG\xd6\xae?^E\xee\xe3Zp2',
    'vault_public_key': b'\xbd6\xe14\x8dB\xb5\xac\xdb\x95\xdc.:=xhb\xbd\xacwx\xd5\x17G\x8a/\xa9\xf58\x9bpU',
}
