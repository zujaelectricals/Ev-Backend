# Generated migration to add Razorpay charges tracking fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_add_webhook_event_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='net_amount',
            field=models.IntegerField(blank=True, help_text='Net amount in paise after gateway charges', null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='gateway_charges',
            field=models.IntegerField(blank=True, help_text='Gateway charges in paise (2.36% of gross amount)', null=True),
        ),
    ]

