from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string


def send_self_email(title, request, template="email/default.txt", context={}, devs_only=True):
    """
        Send a message to ourselves. By default, sends only to settings.ADMINS.
        To contact the main Perma email address, set devs_only=False
    """
    if devs_only:
        EmailMessage(
            title,
            render_to_string(template, context=context, request=request, using="AUTOESCAPE_OFF"),
            settings.DEFAULT_FROM_EMAIL,
            [admin[1] for admin in settings.ADMINS]
        ).send(fail_silently=False)
    else:
        # Use a special reply-to address to avoid Freshdesk's filters: a ticket will be opened.
        EmailMessage(
            title,
            render_to_string(template, context=context, request=request, using="AUTOESCAPE_OFF"),
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_FROM_EMAIL],
            reply_to=[settings.DEFAULT_REPLYTO_EMAIL]
        ).send(fail_silently=False)
