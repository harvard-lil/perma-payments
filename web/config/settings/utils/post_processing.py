### settings post-checks
# here we do stuff that should be checked or fixed after ALL settings from any source are loaded
# this is called by __init__.py


def post_process_settings(settings):

    # check secret key
    assert 'SECRET_KEY' in settings and settings['SECRET_KEY'] is not None, "Set DJANGO__SECRET_KEY env var!"
