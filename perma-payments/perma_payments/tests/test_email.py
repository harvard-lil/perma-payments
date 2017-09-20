from django.http import HttpRequest

import pytest

from perma_payments.email import *

@pytest.fixture()
def email():
    return {
       'subject': 'the subject',
       'message': 'the message',
       'from': 'from@example.com'
    }

def test_send_admin_email(email, mailoutbox):
    send_admin_email(email['subject'], email['from'], HttpRequest(), context={'message': email['message']})
    assert len(mailoutbox) == 1
    m = mailoutbox[0]
    assert m.subject == email['subject']
    assert m.body == email['message'] + "\n"
    assert m.from_email == settings.DEFAULT_FROM_EMAIL
    assert m.reply_to == [email['from']]


def test_send_admin_email_template(email, mocker):
    stringified = mocker.patch('perma_payments.email.render_to_string', autospec=True)
    request = HttpRequest()
    send_admin_email(email['subject'], email['from'], request, template="test")
    stringified.assert_called_once_with("test", context={}, request=request)
