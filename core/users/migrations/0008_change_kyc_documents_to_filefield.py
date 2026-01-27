# Generated manually to change ImageField to FileField for KYC documents

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_add_distributor_terms_accepted'),
    ]

    operations = [
        migrations.AlterField(
            model_name='kyc',
            name='pan_document',
            field=models.FileField(blank=True, null=True, upload_to='kyc/pan/'),
        ),
        migrations.AlterField(
            model_name='kyc',
            name='aadhaar_front',
            field=models.FileField(blank=True, null=True, upload_to='kyc/aadhaar/'),
        ),
        migrations.AlterField(
            model_name='kyc',
            name='aadhaar_back',
            field=models.FileField(blank=True, null=True, upload_to='kyc/aadhaar/'),
        ),
        migrations.AlterField(
            model_name='kyc',
            name='bank_passbook',
            field=models.FileField(blank=True, null=True, upload_to='kyc/bank_passbook/'),
        ),
    ]

