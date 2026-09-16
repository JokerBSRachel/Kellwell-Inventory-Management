from django.db import migrations

def copy_units_back(apps, schema_editor):
    CountyItem = apps.get_model("inventory_system", "CountyItem")
    Inventory = apps.get_model("inventory_system", "Inventory")

    for county_item in CountyItem.objects.all():
        inv = Inventory.objects.filter(county_item=county_item, unit__isnull=False).first()
        if inv:
            county_item.unit = inv.unit
            county_item.save()

class Migration(migrations.Migration):
    dependencies = [("inventory_system", "0010_countyitem_unit")]
    operations = [migrations.RunPython(copy_units_back, migrations.RunPython.noop)]