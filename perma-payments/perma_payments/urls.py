from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('cancel-request/', views.cancel_request, name='cancel_request'),
    path('cybersource-callback/', views.cybersource_callback, name='cybersource_callback'),
    path('subscribe/', views.subscribe, name='subscribe'),
    path('subscription/', views.subscription, name='subscription'),
    path('update-statuses/', views.update_statuses, name='update_statuses'),
    path('update/', views.update, name='update'),
    path('change/', views.change, name='change'),
]

