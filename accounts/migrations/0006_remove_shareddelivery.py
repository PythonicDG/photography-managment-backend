from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('accounts', '0005_quote_versions')]

    operations = [
        migrations.DeleteModel(name='SharedDelivery'),
    ]
