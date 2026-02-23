from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0008_booking_bonus_applied'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='deductions_applied',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Non-cash credits (TDS/extra deductions from commission earnings) debited from remaining balance',
                max_digits=10,
            ),
        ),
    ]

