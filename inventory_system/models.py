from django.db import models


class State(models.Model):
    state_name = models.CharField(max_length=100)
    state_abbreviation = models.CharField(max_length=2, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "state_name"]

    def __str__(self):
        return self.state_name


class Region(models.Model):
    region_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "region_name"]

    def __str__(self):
        return self.region_name


class Manager(models.Model):
    manager_name = models.CharField(max_length=100)
    manager_title = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "manager_name"]

    def __str__(self):
        return self.manager_name


class County(models.Model):
    county_name = models.CharField(max_length=100)
    # Preserve historical records if a state, region, or manager is deactivated
    state = models.ForeignKey(State, on_delete=models.PROTECT) 
    region = models.ForeignKey(Region, on_delete=models.PROTECT, null=True, blank=True)
    manager = models.ForeignKey(Manager, on_delete=models.PROTECT, null=True, blank=True) 
    tracking_start_date = models.DateField(null=True, blank=True)
        # The Friday end-date of this county's first real tracked week.
        # The "initial" bootstrap week is always 7 days before this.
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Counties"
        constraints = [
            models.UniqueConstraint(fields=["county_name", "state"], name="unique_county_name_per_state")
        ]
        ordering = ["-is_active", "county_name", "state__state_abbreviation"]

    def __str__(self):
        return self.county_name + " County, " + self.state.state_abbreviation


class Employee(models.Model):
    county = models.ForeignKey(County, on_delete=models.PROTECT) # Preserve historical records
    employee_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "employee_name"]

    def __str__(self):
        return self.employee_name


class Week(models.Model):
    status_options = {
        0: "Open",
        1: "Admin Editable", # Only admin can edit previous week's data
        2: "Locked", # All data is permanently locked after 2 weeks
    }

    county = models.ForeignKey(County, on_delete=models.PROTECT) 
    end_date = models.DateField() # Ending date of the week
    status = models.IntegerField(choices=status_options, default=0)
    is_initial = models.BooleanField(default=False)  # True only for the auto-created bootstrap week

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["county", "end_date"], name="unique_county_end_date")
        ]
        ordering = ["-end_date", "county__county_name", "county__state__state_abbreviation"]


    def __str__(self):
        return "Week ending on " + str(self.end_date) + " for " + str(self.county) + " (" + self.status_options[self.status] + ")"


class WeeklyPayroll(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT) # Preserve historical records
    week = models.ForeignKey(Week, on_delete=models.PROTECT)
    regular_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    overtime_explanation = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Weekly payroll"
        constraints = [
            models.UniqueConstraint(fields=["employee", "week"], name="unique_employee_week")
        ]
        ordering = ["-week__end_date", "employee__employee_name", "employee__county__county_name", "employee__county__state__state_abbreviation"]

    def __str__(self):
        return self.employee.employee_name + " - " + str(self.week.county) + " - " + str(self.week.end_date)


class WeeklySignoff(models.Model):
    week = models.ForeignKey(Week, on_delete=models.PROTECT)
    manager = models.ForeignKey(Manager, on_delete=models.PROTECT)
    signed_at = models.DateTimeField(auto_now_add=True) # Set the timestamp when the record is created

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["week"], name="unique_week_signoff")
        ]
        ordering = ["-week__end_date", "-signed_at", "week__county__county_name", "week__county__state__state_abbreviation"]

    def __str__(self):
        return str(self.week.end_date) + " - " + str(self.week.county) + " - signed off by " + str(self.manager)


class Item(models.Model):
    item_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "item_name"]

    def __str__(self):
        return self.item_name


class FoodCode(models.Model):
    code_number = models.PositiveSmallIntegerField(unique=True) 
    code_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "code_number"]

    def __str__(self):
        return str(self.code_number) + " - " + self.code_name


class CountyCategory(models.Model):
    """Links a county to a food code, with a county-specific subcategory number."""
    county = models.ForeignKey(County, on_delete=models.PROTECT)
    code = models.ForeignKey(FoodCode, on_delete=models.PROTECT)
    subcategory_id = models.PositiveSmallIntegerField() # The number after the dash that follows the food code
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "County categories"
        constraints = [
            models.UniqueConstraint(fields=["county", "code", "subcategory_id"], name="unique_county_code_subcategory")
        ]
        ordering = ["-is_active", "county__county_name", "code__code_number", "subcategory_id"]

    def __str__(self):
        return str(self.county) + " - " + str(self.code.code_number) + "-" + str(self.subcategory_id)


class CountyItem(models.Model):
    """Categorizes items for a county within its specific categories."""
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    category = models.ForeignKey(CountyCategory, on_delete=models.PROTECT)
    item_unit = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "County items"
        constraints = [
            models.UniqueConstraint(fields=["item", "category"], name="unique_item_category")
        ]
        ordering = ["-is_active", "category__county__county_name", "category__county__state__state_abbreviation", "category__code__code_number", "category__subcategory_id", "item__item_name"]

    def __str__(self):
        return str(self.category) + " - " + str(self.item)


class Inventory(models.Model):
    """Each instance represents the inventory of an item in a county within one week"""
    county_item = models.ForeignKey(CountyItem, on_delete=models.PROTECT)
    week = models.ForeignKey(Week, on_delete=models.PROTECT)
    end_price = models.DecimalField(max_digits=6, decimal_places=2, default=0.00) # price per unit
    end_received_1 = models.DecimalField(max_digits=6, decimal_places=2, default=0.00) # shipment(s) during the week
    end_received_2 = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    end_inventory = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    deep_dive = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Inventory"
        constraints = [
            models.UniqueConstraint(fields=["county_item", "week"], name="unique_county_item_week")
        ]
        ordering = ["-week__end_date", "county_item__category__county__county_name", "county_item__category__county__state__state_abbreviation", "county_item__category__code__code_number", "county_item__category__subcategory_id", "county_item__item__item_name"]

    def __str__(self):
        return str(self.week.end_date) + " - " + str(self.county_item)

class Invoice(models.Model):
    week = models.ForeignKey(Week, on_delete=models.PROTECT)
    vendor_name = models.CharField(max_length=100)
    invoice_number = models.CharField(max_length=100)
    tax = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    class Meta:
        ordering = ["-week__end_date", "week__county__county_name", "week__county__state__state_abbreviation", "vendor_name", "invoice_number"]

    def __str__(self):
        return str(self.vendor_name) + " - " + str(self.week)


class InvoiceLineItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT)
    code = models.ForeignKey(FoodCode, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invoice", "code"], name="unique_invoice_code")
        ]
        ordering = ["-invoice__week__end_date", "invoice__week__county__county_name", "invoice__week__county__state__state_abbreviation", "invoice__vendor_name", "code__code_number"]

    def __str__(self):
        return str(self.invoice) + " - " + str(self.code)


class Meal(models.Model):
    meal_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "meal_name"]

    def __str__(self):
        return self.meal_name


class CountyMeal(models.Model):
    county = models.ForeignKey(County, on_delete=models.PROTECT)
    meal = models.ForeignKey(Meal, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["county", "meal"], name="unique_county_meal")
        ]
        ordering = ["-is_active", "county__county_name", "county__state__state_abbreviation", "meal__meal_name"]

    def __str__(self):
        return str(self.county) + " - " + str(self.meal)


class DailySale(models.Model):
    county_meal = models.ForeignKey(CountyMeal, on_delete=models.PROTECT)
    week = models.ForeignKey(Week, on_delete=models.PROTECT)
    sale_date = models.DateField()
    sale_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["county_meal", "week", "sale_date"], name="unique_county_meal_week_sale_date")
        ]
        ordering = ["-week__end_date", "county_meal__county__county_name", "county_meal__county__state__state_abbreviation", "county_meal__meal__meal_name", "-sale_date"]

    def __str__(self):
        return str(self.county_meal) + " - " + str(self.sale_date)

