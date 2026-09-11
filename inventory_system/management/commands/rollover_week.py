from django.core.management.base import BaseCommand, CommandError
from datetime import timedelta
from inventory_system.models import Week, County, CountyItem, Inventory, CountyMeal, DailySale#, WeeklySignoff


class Command(BaseCommand):
    help = "Rolls over a specific county's current open week into a new week."

    def add_arguments(self, parser):
        parser.add_argument("county_id", type=int, help="The ID of the county to roll over")

    def handle(self, *args, **options):
        county_id = options["county_id"]

        try:
            county = County.objects.get(id=county_id)
        except County.DoesNotExist:
            raise CommandError(f"No county found with id {county_id}")

        try:
            old_week = Week.objects.get(county=county, status=0)
        except Week.DoesNotExist:
            raise CommandError(f"No open week found for {county}. Cannot roll over.")
        except Week.MultipleObjectsReturned:
            raise CommandError(f"Multiple open weeks found for {county}. Fix data before rolling over.")

        # Require signoff before allowing rollover
        # if not WeeklySignoff.objects.filter(week=old_week).exists():
        #     raise CommandError(f"{old_week} has not been signed off. Cannot roll over.")

        # Create the new week
        new_end_date = old_week.end_date + timedelta(days=7)
        new_week = Week.objects.create(county=county, end_date=new_end_date, status=0)
        self.stdout.write(f"Created new week ending {new_end_date} for {county}")

        # Update statuses, scoped to this county
        Week.objects.filter(county=county, status=1).update(status=2)
        old_week.status = 1
        old_week.save()

        # Roll forward Inventory for this county's active CountyItems
        county_items = CountyItem.objects.filter(
            category__county=county, is_active=True
        )
        for county_item in county_items:
            old_inventory = Inventory.objects.filter(county_item=county_item, week=old_week).first()
            Inventory.objects.create(
                county_item=county_item,
                week=new_week,
                end_price=old_inventory.end_price if old_inventory else 0,
                end_inventory=old_inventory.end_inventory if old_inventory else 0,
                end_received_1=0,
                end_received_2=0,
            )

        # Create DailySale rows for this county's active CountyMeals
        county_meals = CountyMeal.objects.filter(county=county, is_active=True)
        for county_meal in county_meals:
            for i in range(7):
                sale_date = new_end_date - timedelta(days=6 - i)
                DailySale.objects.create(
                    county_meal=county_meal,
                    week=new_week,
                    sale_date=sale_date,
                    sale_count=0,
                )

        self.stdout.write(self.style.SUCCESS(f"Rollover complete: {new_week}"))