# Generated manually to add nominee KYC fields
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_kyc_bank_passbook'),
    ]

    operations = [
        migrations.AddField(
            model_name='nominee',
            name='kyc_status',
            field=models.CharField(default='pending', max_length=10),
        ),
        migrations.AddField(
            model_name='nominee',
            name='kyc_submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='nominee',
            name='kyc_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='nominee',
            name='kyc_verified_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='nominee_verified_by', to='users.user'),
        ),
        migrations.AddField(
            model_name='nominee',
            name='kyc_rejection_reason',
            field=models.TextField(blank=True),
        ),
    ]
