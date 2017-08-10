from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^subscribe/$', views.subscribe, name='subscribe'),
    url(r'^cybersource-callback/$', views.cybersource_callback, name='cybersource_callback'),
    url(r'^current/$', views.current, name='current'),
    url(r'^perma-spoof/$', views.perma_spoof, name='perma_spoof'),
    url(r'^perma-spoof-current/$', views.perma_spoof_is_current, name='perma_spoof_is_current'),
]
