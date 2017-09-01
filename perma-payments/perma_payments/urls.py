from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^subscribe/$', views.subscribe, name='subscribe'),
    url(r'^cybersource-callback/$', views.cybersource_callback, name='cybersource_callback'),
    url(r'^status/$', views.status, name='status'),
    url(r'^cancel-request/$', views.cancel_request, name='cancel_request'),
    url(r'^update/$', views.update, name='update'),
    url(r'^update-statuses/$', views.update_statuses, name='update_statuses'),
]

