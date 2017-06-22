# set up Django
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
try:
    django.setup()
except Exception as e:
    print("WARNING: Can't configure Django -- tasks depending on Django will fail:\n%s" % e)

from django.contrib.auth.models import User
from fabric.api import run, local
from fabric.decorators import task

@task(alias='run')
def run_django():
    local("python3 manage.py runserver 0.0.0.0:8000")

@task
def test():
    local("pytest")

@task
def init_db():
    """
        Set up new dev database.
    """
    local("python3 manage.py migrate")
    print("Creating DEV admin user:")
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
