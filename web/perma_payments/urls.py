from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^cancel-request/$', views.cancel_request, name='cancel_request'),
    url(r'^cybersource-callback/$', views.cybersource_callback, name='cybersource_callback'),
    url(r'^purchase/$', views.purchase, name='purchase'),
    url(r'^acknowledge-purchase/$', views.acknowledge_purchase, name='acknowledge_purchase'),
    url(r'^purchase-history/$', views.purchase_history, name='purchase_history'),
    url(r'^subscribe/$', views.subscribe, name='subscribe'),
    url(r'^subscription/$', views.subscription, name='subscription'),
    url(r'^update-statuses/$', views.update_statuses, name='update_statuses'),
    url(r'^update/$', views.update, name='update'),
    url(r'^change/$', views.change, name='change'),
]

