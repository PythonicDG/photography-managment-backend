import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('accounts', '0003_sharedquote')]

    operations = [
        migrations.CreateModel(
            name='SharedDelivery',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('local_id', models.CharField(max_length=100)),
                ('snapshot', models.JSONField()),
                ('status', models.CharField(choices=[('Awaiting approval', 'Awaiting approval'), ('Approved', 'Approved')], default='Awaiting approval', max_length=20)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('studio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shared_deliveries', to='accounts.studio')),
            ],
        ),
        migrations.AddConstraint(model_name='shareddelivery', constraint=models.UniqueConstraint(fields=('studio', 'local_id'), name='unique_studio_local_delivery')),
    ]
