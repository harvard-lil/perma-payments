from django.conf import settings
from django.http import HttpRequest
from django.test.utils import override_settings

import pytest

from perma_payments.email import send_self_email

@pytest.fixture()
def email():
    return {
       'subject': 'the subject',
       'message': 'the message'
    }

def test_send_self_email(email, mailoutbox):
    send_self_email(email['subject'], HttpRequest(), context={'message': email['message']})
    assert len(mailoutbox) == 1
    m = mailoutbox[0]
    assert m.subject == email['subject']
    assert m.body == email['message'] + "\n"
    assert m.from_email == settings.DEFAULT_FROM_EMAIL
    assert m.to == [settings.ADMINS[0][1]]

@override_settings(DEFAULT_REPLYTO_EMAIL='from@example.com')
def test_send_self_email_everybody(email, mailoutbox):
    send_self_email(email['subject'], HttpRequest(), context={'message': email['message']}, devs_only=False)
    assert len(mailoutbox) == 1
    m = mailoutbox[0]
    assert m.subject == email['subject']
    assert m.body == email['message'] + "\n"
    assert m.from_email == settings.DEFAULT_FROM_EMAIL
    assert m.to == [settings.DEFAULT_FROM_EMAIL]
    assert m.reply_to == ['from@example.com']


def test_send_self_email_template(email, mocker):
    stringified = mocker.patch('perma_payments.email.render_to_string', autospec=True)
    request = HttpRequest()
    send_self_email(email['subject'], request, template="test")
    stringified.assert_called_once_with("test", context={}, request=request)
