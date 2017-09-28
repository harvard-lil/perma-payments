
# API endpoints from "CyberSource Secure Acceptance Web/Mobile Configuration Guide"
# dated "June 2017"
# http://apps.cybersource.com/library/documentation/dev_guides/Secure_Acceptance_WM/Secure_Acceptance_WM.pdf

# "Process Transaction Endpoints"
#
# Supported transaction types :
# - authorization
# - authorization,create_payment_token
# - authorization,update_payment_token
# - sale
# - sale,create_payment_token
# - sale,update_payment_token
CS_PAYMENT_URL = {
    'test': 'https://testsecureacceptance.cybersource.com/pay',
    'prod': 'https://secureacceptance.cybersource.com/pay'
}

# "Create Payment Token Endpoints"
#
# Supported transaction type:
# - create_payment_token
CS_TOKEN_URL = {
    'test': 'https://testsecureacceptance.cybersource.com/token/create',
    'prod': 'https://secureacceptance.cybersource.com/token/create'
}

# "Update Payment Token Endpoints"
#
# Supported transaction type:
# - update_payment_token
#
# You can update all fields except:
# recurring_frequency, recurring_start_date, recurring_number_of_payments
CS_TOKEN_UPDATE_URL = {
    'test': 'https://testsecureacceptance.cybersource.com/token/update',
    'prod': 'https://secureacceptance.cybersource.com/token/update'
}

# URL in the Business Center to find subscriptions
CS_SUBSCRIPTION_SEARCH_URL = {
    'test': 'https://ebctest.cybersource.com/ebctest/subscriptions/SubscriptionSearchLoad.do',
    'prod': ''
}

CS_CARD_TYPE = {
    'visa': '001',
    'mastercard': '002',
    'american_express': '003',
    'discover': '004',
    # Diners Club: cards starting with 54 or 55 are rejected.
    'diners_club': '005',
    'carte_blanche': '006',
    'jcb': '007',
    'enroute': '014',
    'jal': '021',
    'maestro_uk_domestic': '024',
    'delta': '031',
    'visa_electron': '033',
    'dankort': '034',
    'carte_bleue': '036',
    'carta_si': '037',
    'maestro_international': '042',
    'ge_money_uk_card': '043',
    # Hipercard (sale only)
    'hipercard': '050',
    'elo': '054',
}

# "Types of Notifications" (= decisions)
CS_DECISIONS = {
    # CyberSource Hosted Page: Accept
    'ACCEPT': "Successful transaction. Reason codes 100 and 110.",
    # CyberSource Hosted Page: Accept (is this a problem for us???)
    'REVIEW': "Authorization was declined; however, the capture may still be possible. " +
              "Review payment details. See reason codes 200, 201, 230, and 520.",
    # CyberSource Hosted Page: Decline
    'DECLINE': "Transaction was declined. See reason codes 102, 200, 202, 203, 204, " +
               "205, 207, 208, 210, 211, 221, 222, 230, 231, " +
               "232, 233, 234, 236, 240, 475, 476, and 481.",
    # CyberSource Hosted Page: Error
    'ERROR': "Access denied, page not found, or internal server error. " +
             "See reason codes 102, 104, 150, 151 and 152.",
    # CyberSource Hosted Page: Cancel
    'CANCEL': "The customer did not accept the service fee conditions, " +
              "or the customer cancelled the transaction."
}

# "Reason Codes" (payer_authentication_reason_code)
# from http://apps.cybersource.com/library/documentation/dev_guides/Secure_Acceptance_WM/Secure_Acceptance_WM.pdf
# Because CyberSource may add reply fields and reason codes at any time,
# proceed as follows:
# - Your error handler should use the decision field to determine the
# transaction result if it receives a reason code that it does not recognize.
CS_ERROR_CODES = {
    '100': "Successful transaction.",
    # 101 is absent from the most recent versions of the docs
    # '101': "The request is missing one or more required fields",
    '102': "One or more fields in the request contain invalid data. " +
           "Possible action: see the reply field invalid_fields to ascertain which fields are invalid. " +
           "Resend the request with the correct information.",
    # 104 is a recent addition to the docs
    '104': "The access_key and transaction_uuid fields for this authorization request " +
           "match the access_key and transaction_uuid fields of another authorization request that " +
           "you sent within the past 15 minutes. " +
           "Possible action: resend the request with unique access_key and transaction_uuid fields. " +
           "A duplicate transaction was detected. The transaction may have already been processed. " +
           "Possible action: before resubmitting the transaction, use the single transaction query " +
           "or search for the transaction using the Business Center to " +
           "confirm that the transaction has not yet been processed.",
    '110': "Only a partial amount was approved",
    '150': "General system failure. Possible action: wait a few minutes and resend the request.",
    # NB: Possible actions for 151 differ in available docs. Alternate:
    #     "Possible Action – to avoid duplicating the transaction, do not resend the request " +
    #     "until you have reviewed the transaction status in the Enterprise Business Centre."
    '151': "The request was received but there was a server timeout." +
           "This error does not include timeouts between the client and the server. " +
           "Possible Action – wait a few minutes and resend the request.",
    # NB: Alternate for 152:
    #     "The request was received, but a service did not finish running in time. " +
    #     "Possible Action – to avoid duplicating the transaction, do not resend the request until you have reviewed the transaction status in the Enterprise Business Centre.",
    '152': "The request was received, but a service timeout occurred. " +
           "Possible action: wait a few minutes and resend the request.",
    '200': "The authorisation request was approved by the issuing bank " +
           "but declined by CyberSource because it did not pass the Address Verification System (AVS) check " +
           "Possible Action – you can capture the authorisation, but consider reviewing the order for the possibility of fraud",
    '201': "The issuing bank has questions about the request. You do not receive an authorisation code programmatically, " +
           "but you might receive one verbally by calling the processor. " +
           "Possible Action – call your processor to possibly receive a verbal authorisation. " +
           "For contact phone numbers,  refer to your merchant bank information.",
    '202': "Expired card. You might also receive this if the expiration date you provided " +
           "does not match the date the issuing bank has on file. " +
           "Possible Action – request a different card or other form of payment",
    '203': "General decline of the card. No other information was provided by the issuing bank. " +
           "Possible Action – request a different card or other form of payment",
    '204': "Insufficient funds in the account. Possible Action – request a different card or other form of payment",
    '205': "Stolen or lost card. Possible Action – review this transaction manually to ensure that you submitted the correct information.",
    '207': "Issuing bank unavailable. Possible Action – wait a few minutes and resend the request",
    '208': "Inactive card or card not authorised for card-not-present transactions. " +
           "Possible Action – request a different card or other form of payment.",
    # 209 is absent from most recent version of the docs
    # '209': "American Express Card Identification Digits (CID) did not match. " +
    #        "Possible Action – request a different card or other form of payment",
    '210': "The card has reached the credit limit. " +
           "Possible Action – request a different card or other form of payment.",
    '211': "Invalid CVN. Possible Action – request a different card or other form of payment.",
    '221': "The customer matched an entry on the processor’s negative file. " +
           "Possible Action – review the order and contact the payment processor",
    '230': "The authorisation request was approved by the issuing bank " +
           "but declined by CyberSource because it did not pass the CVN check. " +
           "Possible Action – you can capture the authorisation, but consider reviewing the order for the possibility of fraud.",
    '231': "Invalid account number. Possible Action – request a different card or other form of payment.",
    '232': "The card type is not accepted by the payment processor. " +
           "Possible Action – contact your merchant bank to confirm that merchant account is setup to receive the card in question",
    '233': "General decline by the processor. Possible Action – request a different card or other form of payment",
    '234': "There is a problem with the information in your CyberSource account. " +
           "Possible Action – do not resend the request. Contact Network International to correct the information in your account",
    '235': "The requested capture amount exceeds the originally authorised amount. " +
           "Possible Action – issue a new authorisation and capture request for the new amount",
    '236': "Processor failure. Possible Action – wait a few minutes and resend the request",
    # 237-239 are absent from the most recent version of the docs
    # '237': "The authorisation has already been reversed. Possible Action – no action required",
    # '238': "The authorisation has already been captured. Possible Action – no action required",
    # '239': "The requested transaction amount must match the previous transaction amount. " +
    #        "Possible Action – correct the amount and resend the request.",
    '240': "The card type send is invalid or does not correlate with the credit card number. " +
           "Possible Action – confirm that the card type correlates with the credit card number specified in the request, then resend the request.",
    # 241-400 are absent from the most recent version of the docs
    # '241': "The request ID is invalid. Possible Action – request a new authorisation, and if successful, proceed with the capture.",
    # '242': "You requested a capture, but there is no corresponding, unused authorisation record. " +
    #        "Occurs if there was not a previously successful authorisation request or if the " +
    #        "previously successfully authorisation has already been used by another capture request. " +
    #        "Possible Action – request a new authorisation, and if successful, proceed with the capture.",
    # '243': "The transaction has already been settled or reversed. Possible Action – no action required",
    # '246': "One of the following: " +
    #        "a) The capture or credit is not voidable because the capture or credit information has already been submitted to your processor " +
    #        "b) You requested a void for a type of transaction that cannot be voided. " +
    #        "Possible Action – no action required",
    # '250': "The request was received, but there was a timeout at the payment processor. " +
    #        "Possible Action – to avoid duplicating the transaction, do not resend the request " +
    #        "until you have reviewed the transaction status in the Enterprise Business Centre",
    # '254': "Stand-alone credits are not allowed. " +
    #        "Possible Action – submit a follow-on credit by including a request ID in the credit request. " +
    #        "A follow-on credit must be requested within 60 days of the authorisation. To process stand-alone credits, " +
    #        "contact Network International account manager to find out if this is supported for your account.",
    # '400': "The fraud score exceeds Network International threshold. Possible Action – review the customer’s order",
    # 475 is a recent addition to the docs
    '475': "The cardholder is enrolled for payer authentication. " +
           "Possible action: authenticate cardholder before proceeding.",
    '476': "The customer cannot be authenticated. Possible Action – review the customer’s order.",
    # 480 is absent from the most recent version of the docs
    # '480': "The order is marked for review by Decision Manager. " +
    #        "Possible Action – Hold the customer’s order and contact Network International for further guidance.",
    # NB: Alternate for 481:
    #     "The order is rejected by Decision Manager " +
    #     "Possible Action – do not proceed with customer’s order.",
    '481': "Transaction declined based on your payment settings for the profile. " +
           "Possible action: review the risk score settings for the profile. ",
    # 520 is a recent addition to the docs
    '520': "The authorization request was approved by the issuing bank but " +
           "declined by CyberSource based on your legacy Smart Authorization settings. " +
           "Possible action: review the authorization request.",
}

# AVS Codes (auth_avs_code)
#
# An issuing bank uses the AVS code to confirm that your customer is providing the correct
# billing address. If the customer provides incorrect data, the transaction might be
# fraudulent.
#
# NB: When you populate billing street address 1 and billing street address 2,
# CyberSource through VisaNet concatenates the two values. If the
# concatenated value exceeds 40 characters, CyberSource through VisaNet
# truncates the value at 40 characters before sending it to Visa and the issuing
# bank. Truncating this value affects AVS results and therefore might also affect
# risk decisions and chargebacks.

# US Domestic AVS Codes
CS_DOMESTIC_AVS_CODES = {
    'A': "Partial match: Street address matches, but five-digit and nine-digit postal " +
         "codes do not match. ",
    'B': "Partial match: Street address matches, but postal code is not verified.",
    'C': "No match: Street address and postal code do not match.",
    'D': "Match: Street address and postal code match. ",
    'E': "Invalid: AVS data is invalid or AVS is not allowed for this card type",
    'F': "Partial match: Card member’s name does not match, " +
         "but billing postal code matches. " +
         "Returned only for the American Express card type",
    'H': "Partial match: Card member’s name does not match, " +
         "but street address and postal code match. " +
         "Returned only for the American Express card type.",
    'I': "No match: Address not verified.",
    'J': "Match: Card member’s name, billing address, and postal code match. " +
         "Shipping information verified and chargeback protection " +
         "guaranteed through the Fraud Protection Program. Returned " +
         "only if you are signed up to use AAV+ with the American " +
         "Express Phoenix processor.",
    'K': "Partial match: Card member’s name matches, but billing address and billing " +
         "postal code do not match. Returned only for the American " +
         "Express card type.",
    'L': "Partial match: Card member’s name and billing postal code match, but billing " +
         "address does not match. Returned only for the American " +
         "Express card type.",
    'M': "Match: Street address and postal code match.",
    'N': "No match: One of the following: a) Street address and postal code do not match." +
         "b) Card member’s name, street address, and postal code do not match." +
         "Returned only for the American Express card type.",
    'O': "Partial match: Card member’s name and billing address match, but billing " +
         "postal code does not match. Returned only for the American Express card type",
    'P': "Partial match: Postal code matches, but street address not verified.",
    'Q': "Match: Card member’s name, billing address, and postal code match. " +
         "Shipping information verified but chargeback protection not " +
         "guaranteed (Standard program). Returned only if you are signed " +
         "to use AAV+ with the American Express Phoenix processor.",
    'R': "System unavailable: System unavailable.",
    'S': "Not supported: U.S.-issuing bank does not support AVS.",
    'T': "Partial match: Card member's name does not match, but street address matches. " +
         "Returned only for the American Express card type.",
    'U': "System unavailable: Address information unavailable for one of these reasons: " +
         "a) The U.S. bank does not support non-U.S. AVS. " +
         "b) The AVS in a U.S. bank is not functioning properly",
    'V': "Match: Card member’s name, billing address, and billing postal code match. " +
         "Returned only for the American Express card type.",
    'W': "Partial match: Street address does not match, but nine-digit postal code matches.",
    'X': "Match: Street address and nine-digit postal code match.",
    'Y': "Match: Street address and five-digit postal code match.",
    'Z': "Partial match: Street address does not match, but five-digit postal code matches.",
    '1': "Not supported: AVS is not supported for this processor or card type.",
    '2': "Unrecognized:  The processor returned an unrecognized value for the AVS response.",
    '3': "Match: Address is confirmed. Returned only for PayPal Express Checkout.",
    '4': "No match: Address is not confirmed. Returned only for PayPal Express Checkout.",
}

# International AVS Codes
# These codes are returned only for Visa cards issued outside the U.S.
CS_INTERNATIONAL_AVS_CODES = {
    'B': "Partial match: Street address matches, but postal code is not verified.",
    'C': "No match: Street address and postal code do not match.",
    'D': "Match: Street address and postal code match.",
    'I': "No match: Address not verified.",
    'M': "Match: Street address and postal code match.",
    'P': "Partial match: Postal code matches, but street address not verified."
}

# "CVN Codes"
# The Card Verification Number (CVN) is a three- or four-digit number that helps
# ensure that the customer has possession of the card at the time of the
# transaction.
CS_CVN_CODES = {
    'D': "The transaction was considered to be suspicious by the issuing bank.",
    'I': "The CVN failed the processor's data validation.",
    'M': "The CVN matched.",
    'N': "The CVN did not match.",
    'P': "The CVN was not processed by the processor for an unspecified reason.",
    'S': "The CVN is on the card but was not included in the request.",
    'U': "Card verification is not supported by the issuing bank.",
    'X': "Card verification is not supported by the card association.",
    '1': "Card verification is not supported for this processor or card type.",
    '2': "An unrecognized result code was returned by the processor for the card verification response.",
    '3': "No result code was returned by the processor."
}

# from http://apps.cybersource.com/library/documentation/dev_guides/Secure_Acceptance_WM/Secure_Acceptance_WM.pdf
CS_TEST_CUSTOMER = {
    'first_name': "noreal",
    'last_name': "name",
    'street1': "1295 Charleston Road",
    'city': "Mountain View",
    'state': "CA",
    'postal_code': "94043",
    'country': "US",
    'email': "null@cybersource.com",

}

CS_TEST_CARD = {
    'visa': {
        'card_cvn': '500',
        'card_expiry_date': '12-2022',
        'card_number': '4111111111111111',
        'card_type': '001'
    },
    # 'mastercard': '5555555555554444',
    # 'american_express': '378282246310005',
    # 'discover': '6011111111111117',
    # 'jcb': '3566111111111113',
    # 'diners_club': '38000000000006',
    # 'maestro_international': '6000340000009859',
    # 'maestro_uk_domestic': '6759180000005546'
}
