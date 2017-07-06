
# from http://apps.cybersource.com/library/documentation/dev_guides/Secure_Acceptance_WM/Secure_Acceptance_WM.pdf
CS_ERROR_CODES = {
    '100': "Successful transaction.",
    '101': "The request is missing one or more required fields",
    '102': "One or more fields in the request contains invalid data",
    '110': "Only a partial amount was approved",
    '150': "General system failure",
    '151': "The request was received but there was a server timeout." +
           "This error does not include timeouts between the client and the server. " +
           "Possible Action – to avoid duplicating the transaction, do not resend the request " +
           "until you have reviewed the transaction status in the Enterprise Business Centre.",
    '152': "The request was received, but a service did not finish running in time. " +
           "Possible Action – to avoid duplicating the transaction, do not resend the request until you have reviewed the transaction status in the Enterprise Business Centre.",
    '200': "The authorisation request was approved by the issuing bank " +
           "but declined by CyberSource because it did not pass the Address Verification System (AVS) check " +
           "Possible Action – you can capture the authorisation, but consider reviewing the order for the possibility of fraud",
    '201': "The issuing bank has questions about the request. You do not receive an authorisation code programmatically, " +
           "but you might receive one verbally by calling the processor. " +
           "Possible Action – call your processor to possibly receive a verbal authorisation. " +
           "For contact phone numbers, refer to Network International.",
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
    '209': "American Express Card Identification Digits (CID) did not match. " +
           "Possible Action – request a different card or other form of payment",
    '210': "The card has reached the credit limit. " +
           "Possible Action – request a different card or other form of payment.",
    '211': "Invalid CVN. Possible Action – request a different card or other form of payment.",
    '221': "The customer matched an entry on the processor’s negative file. " +
           "Possible Action – review the order and contact Network International",
    '230': "The authorisation request was approved by the issuing bank " +
           "but declined by CyberSource because it did not pass the CVN check. " +
           "Possible Action – you can capture the authorisation, but consider reviewing the order for the possibility of fraud.",
    '231': "Invalid account number. Possible Action – request a different card or other form of payment.",
    '232': "The card type is not accepted by the payment processor. " +
           "Possible Action – contact Network International to confirm that merchant account is setup to receive the card in question",
    '233': "General decline by the processor. Possible Action – request a different card or other form of payment",
    '234': "There is a problem with the information in your CyberSource account. " +
           "Possible Action – do not resend the request. Contact Network International to correct the information in your account",
    '235': "The requested capture amount exceeds the originally authorised amount. " +
           "Possible Action – issue a new authorisation and capture request for the new amount",
    '236': "Processor failure. Possible Action – wait a few minutes and resend the request",
    '237': "The authorisation has already been reversed. Possible Action – no action required",
    '238': "The authorisation has already been captured. Possible Action – no action required",
    '239': "The requested transaction amount must match the previous transaction amount. " +
           "Possible Action – correct the amount and resend the request.",
    '240': "The card type send is invalid or does not correlate with the credit card number. " +
           "Possible Action – confirm that the card type correlates with the credit card number specified in the request, then resend the request.",
    '241': "The request ID is invalid. Possible Action – request a new authorisation, and if successful, proceed with the capture.",
    '242': "You requested a capture, but there is no corresponding, unused authorisation record. " +
           "Occurs if there was not a previously successful authorisation request or if the " +
           "previously successfully authorisation has already been used by another capture request. " +
           "Possible Action – request a new authorisation, and if successful, proceed with the capture.",
    '243': "The transaction has already been settled or reversed. Possible Action – no action required",
    '246': "One of the following: " +
           "a) The capture or credit is not voidable because the capture or credit information has already been submitted to your processor " +
           "b) You requested a void for a type of transaction that cannot be voided. " +
           "Possible Action – no action required",
    '250': "The request was received, but there was a timeout at the payment processor. " +
           "Possible Action – to avoid duplicating the transaction, do not resend the request " +
           "until you have reviewed the transaction status in the Enterprise Business Centre",
    '254': "Stand-alone credits are not allowed. " +
           "Possible Action – submit a follow-on credit by including a request ID in the credit request. " +
           "A follow-on credit must be requested within 60 days of the authorisation. To process stand-alone credits, " +
           "contact Network International account manager to find out if this is supported for your account.",
    '400': "The fraud score exceeds Network International threshold. Possible Action – review the customer’s order",
    '476': "The customer cannot be authenticated. Possible Action – review the customer’s order.",
    '480': "The order is marked for review by Decision Manager. " +
           "Possible Action – Hold the customer’s order and contact Network International for further guidance.",
    '481': "The order is rejected by Decision Manager " +
           "Possible Action – do not proceed with customer’s order."
}
