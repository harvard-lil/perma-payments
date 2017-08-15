from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^subscribe/$', views.subscribe, name='subscribe'),
    url(r'^cybersource-callback/$', views.cybersource_callback, name='cybersource_callback'),
    url(r'^current/$', views.current, name='current'),
    url(r'^cancel-request/$', views.cancel_request, name='cancel_request'),
    url(r'^perma-spoof/$', views.perma_spoof, name='perma_spoof'),
    url(r'^perma-spoof-current/$', views.perma_spoof_is_current, name='perma_spoof_is_current'),
    url(r'^perma-spoof-cancel/$', views.perma_spoof_cancel_confirm, name='perma_spoof_cancel_confirm'),
    url(r'^perma-spoof-cancelled/$', views.perma_spoof_after_cancellation, name='perma_spoof_after_cancellation'),

]
