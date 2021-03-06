# -*- coding: utf-8 -*-
# Generated by Django 1.11.2 on 2017-09-26 20:51
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('perma_payments', '0007_auto_20170926_2048'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subscriptionrequest',
            name='recurring_frequency',
            field=models.CharField(choices=[('weekly', 'weekly'), ('bi-weekly', 'bi-weekly (every 2 weeks)'), ('quad-weekly', 'quad-weekly (every 4 weeks)'), ('monthly', 'monthly'), ('semi-monthly', 'semi-monthly (1st and 15th of each month)'), ('quarterly', 'quarterly'), ('semi-annually', 'semi-annually (twice every year)'), ('annually', 'annually')], max_length=20),
        ),
    ]
