from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0007_add_payment_receipt'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='bonus_applied',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Company bonus debited from remaining balance (not added to total_paid)',
                max_digits=10,
            ),
        ),
    ]

