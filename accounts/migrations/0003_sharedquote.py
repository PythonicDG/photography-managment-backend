import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_studio')]

    operations = [
        migrations.CreateModel(
            name='SharedQuote',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('local_id', models.CharField(max_length=100)),
                ('snapshot', models.JSONField()),
                ('status', models.CharField(choices=[('Pending', 'Pending'), ('Accepted', 'Accepted'), ('Rejected', 'Rejected')], default='Pending', max_length=10)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('studio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shared_quotes', to='accounts.studio')),
            ],
        ),
        migrations.AddConstraint(model_name='sharedquote', constraint=models.UniqueConstraint(fields=('studio', 'local_id'), name='unique_studio_local_quote')),
    ]
