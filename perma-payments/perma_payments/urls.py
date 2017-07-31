from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^subscribe/$', views.subscribe, name='subscribe'),
    url(r'^perma-spoof/$', views.perma_spoof, name='perma_spoof'),
]
