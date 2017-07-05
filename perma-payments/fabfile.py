# set up Django
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
try:
    django.setup()
except Exception as e:
    print("WARNING: Can't configure Django -- tasks depending on Django will fail:\n%s" % e)

from fabric.api import local
from fabric.decorators import task
from django.conf import settings

@task(alias='run')
def run_django():
    local("python3 manage.py runserver 0.0.0.0:80")

@task
def test():
    local("pytest --cov --cov-report= --ds=config.settings.settings_testing")


@task
def init_db():
    """
        Set up a new dev database.
    """
    local("python3 manage.py migrate")
    if settings.ADMIN_ENABLED:
        print("Creating dev admin user.")
        from django.contrib.auth.models import User #noqa
        User.objects.create_superuser('admin', 'admin@example.com', 'admin')
