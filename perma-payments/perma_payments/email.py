from django.conf import settings
from django.core.mail import EmailMessage, send_mail
from django.template.loader import render_to_string


def send_user_email(to_address, template, context):
    email_text = render_to_string(template, context)
    title, email_text = email_text.split("\n\n", 1)
    title = title.split("TITLE: ")[-1]
    success_count = send_mail(
        title,
        email_text,
        settings.DEFAULT_FROM_EMAIL,
        [to_address],
        fail_silently=False
    )
    return success_count


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
        headers={'Reply-To': from_address}
    ).send(fail_silently=False)
