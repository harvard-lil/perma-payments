from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string


def send_admin_email(title, from_address, request, template="email/default.txt", context={}):
    """
    Send a message on behalf of a user to the admins.
    Use reply-to for the user address so we can use email services that require authenticated from addresses.
    """
    EmailMessage(
        title,
        render_to_string(template, context=context, request=request),
        settings.DEFAULT_FROM_EMAIL,
        [settings.DEFAULT_FROM_EMAIL],
        reply_to=[from_address]
    ).send(fail_silently=False)
