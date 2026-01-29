from django.urls import path, re_path

from . import views

urlpatterns = [
    re_path(r'^$', views.index, name='index'),
    re_path(r'^cancel-request/$', views.cancel_request, name='cancel_request'),
    
    # Legacy CyberSource callback (keep for backward compatibility)
    re_path(r'^cybersource-callback/$', views.cybersource_callback, name='cybersource_callback'),
    
    # Generic provider callback endpoints
    path('callback/<str:provider_name>/', views.payment_callback, name='payment_callback'),
    
    # Stripe webhook endpoint
    path('webhook/stripe/', views.stripe_webhook, name='stripe_webhook'),
    
    re_path(r'^purchase/$', views.purchase, name='purchase'),
    re_path(r'^acknowledge-purchase/$', views.acknowledge_purchase, name='acknowledge_purchase'),
    re_path(r'^purchase-history/$', views.purchase_history, name='purchase_history'),
    re_path(r'^subscribe/$', views.subscribe, name='subscribe'),
    re_path(r'^subscription/$', views.subscription, name='subscription'),
    re_path(r'^update-statuses/$', views.update_statuses, name='update_statuses'),
    re_path(r'^update/$', views.update, name='update'),
    re_path(r'^change/$', views.change, name='change'),
]

