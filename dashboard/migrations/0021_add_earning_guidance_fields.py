from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0019_add_industry_valuation_and_dynamic_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='industryvaluation',
            name='median_de',
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name='stockdata',
            name='annual_profit_plan',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='stockdata',
            name='current_ytd_profit',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='stockdata',
            name='profit_plan_completion',
            field=models.FloatField(null=True, blank=True),
        ),
    ]
