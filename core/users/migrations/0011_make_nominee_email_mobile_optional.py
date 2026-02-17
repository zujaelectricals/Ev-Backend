# Generated manually to make nominee email and mobile optional
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0010_add_user_pan_card'),
    ]

    operations = [
        migrations.AlterField(
            model_name='nominee',
            name='mobile',
            field=models.CharField(blank=True, max_length=15, null=True),
        ),
        migrations.AlterField(
            model_name='nominee',
            name='email',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]

