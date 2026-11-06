from django.db import migrations, models


def backfill_roots(apps, schema_editor):
    SharedQuote = apps.get_model('accounts', 'SharedQuote')
    for quote in SharedQuote.objects.all():
        quote.root_local_id = quote.local_id
        quote.save(update_fields=['root_local_id'])


class Migration(migrations.Migration):
    dependencies = [('accounts', '0004_shareddelivery')]
    operations = [
        migrations.AddField(model_name='sharedquote', name='root_local_id', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='sharedquote', name='version', field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name='sharedquote', name='feedback', field=models.TextField(blank=True)),
        migrations.AlterField(model_name='sharedquote', name='status', field=models.CharField(choices=[('Pending', 'Pending'), ('Accepted', 'Accepted'), ('Rejected', 'Rejected'), ('Changes requested', 'Changes requested'), ('Superseded', 'Superseded')], default='Pending', max_length=20)),
        migrations.RunPython(backfill_roots, migrations.RunPython.noop),
    ]
