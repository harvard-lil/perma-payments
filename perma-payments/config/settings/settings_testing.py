from .settings_base import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'k2#@_q=1$(__n7#(zax6#46fu)x=3&^lz&bwb8ol-_097k_rj5'

# CyberSource creds
CS_ACCESS_KEY = 'test'
CS_PROFILE_ID = 'test'
CS_SECRET_KEY = 'a-really-long-test-string'
CS_PAYMENT_URL = 'https://testsecureacceptance.cybersource.com/pay'

# from http://apps.cybersource.com/library/documentation/dev_guides/Secure_Acceptance_WM/Secure_Acceptance_WM.pdf
CS_TEST_CUSTOMER = {
    'first_name': "noreal",
    'last_name': "name",
    'street1': "1295 Charleston Road",
    'city': "Mountain View",
    'state': "CA",
    'postal_code': "94043",
    'country': "US",
    'email': "null@cybersource.com"
}

CS_TEST_CARD = {
    'visa': '4111111111111111',
    'mastercard': '5555555555554444',
    'american_express': '378282246310005',
    'discover': '6011111111111117',
    'jcb': '3566111111111113',
    'diners_club': '38000000000006',
    'maestro_international': '6000340000009859',
    'maestro_uk_domestic': '6759180000005546'
}
