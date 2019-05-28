from django.conf import settings
from django.core.mail import EmailMessage
from django.template import RequestContext, engines


def send_self_email(title, request, template="email/default.txt", context={}, devs_only=True):
    """
        Send a message to ourselves. By default, sends only to settings.ADMINS.
        To contact the main Perma email address, set devs_only=False
    """
    # load the django template engine directly, so that we can
    # pass in a Context/RequestContext object with autocomplete=False
    # https://docs.djangoproject.com/en/1.11/topics/templates/#django.template.loader.engines
    #
    # (though render and render_to_string take a "context" kwarg of type dict,
    #  that dict cannot be used to configure autoescape, but only to pass keys/values to the template)
    engine = engines['django'].engine
    email_text = engine.get_template(template).render(RequestContext(request, context, autoescape=False))

    if devs_only:
        EmailMessage(
            title,
            email_text,
            settings.DEFAULT_FROM_EMAIL,
            [admin[1] for admin in settings.ADMINS]
        ).send(fail_silently=False)
    else:
        # Use a special reply-to address to avoid Freshdesk's filters: a ticket will be opened.
        EmailMessage(
            title,
            email_text,
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_FROM_EMAIL],
            reply_to=[settings.DEFAULT_REPLYTO_EMAIL]
        ).send(fail_silently=False)
