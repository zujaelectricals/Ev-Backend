# Generated for Active Buyer pairing rule: pair 5+ only use nodes placed after active_buyer_since
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0011_make_nominee_email_mobile_optional'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='active_buyer_since',
            field=models.DateTimeField(
                blank=True,
                help_text='When the user first became an Active Buyer (total paid >= activation_amount). Used so pair 5+ only use nodes placed after this time.',
                null=True
            ),
        ),
    ]
