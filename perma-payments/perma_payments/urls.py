from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^payment-form/$', views.payment_form, name='payment-form'),
]
