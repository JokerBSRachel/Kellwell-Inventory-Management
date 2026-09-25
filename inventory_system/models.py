from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

import re

def _normalize_name(text):
    """Collapses all whitespace and lowercases, for exact-match comparison
    that ignores case and spacing differences (e.g. 'Cup Cake' == 'cupcake')."""
    return re.sub(r"\s+", "", text or "").lower()


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
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_profile",
    )
    manager_name = models.CharField(max_length=100)
    manager_title = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "manager_name"]

    def __str__(self):
        return self.manager_name

    def clean(self):
        if self.user_id and hasattr(self.user, "county_login"):
            raise ValidationError("This user is already linked to a County login and cannot also be a Manager.")


class County(models.Model):
    county_name = models.CharField(max_length=100)
    # Preserve historical records if a state, region, or manager is deactivated
    state = models.ForeignKey(State, on_delete=models.PROTECT) 
    region = models.ForeignKey(Region, on_delete=models.PROTECT, null=True, blank=True)
    manager = models.ForeignKey(Manager, on_delete=models.PROTECT, null=True, blank=True) 
    login_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="county_login", verbose_name="Employee user account",
    )
    tracking_start_date = models.DateField(null=True, blank=True)
        # The Friday end-date of this county's first real tracked week.
        # The "initial" bootstrap week is always 7 days before this.
    is_template = models.BooleanField(default=False)
        # True for counties used only as setup templates, not real operating counties.
        # Hides rollover, previous-week editing, and reporting links in the app.
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Counties"
        constraints = [
            models.UniqueConstraint(fields=["county_name", "state"], condition=models.Q(is_active=True), name="unique_county_name_per_state")
        ]
        ordering = ["-is_active", "county_name", "state__state_abbreviation"]

    def __str__(self):
        if not self.is_template:
            return self.county_name + " County, " + self.state.state_abbreviation
        else:
            return self.county_name


class Employee(models.Model):
    county = models.ForeignKey(County, on_delete=models.PROTECT)
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
    regular_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
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

    @classmethod
    def find_exact_match(cls, name):
        target = _normalize_name(name)
        for item in cls.objects.all():
            if _normalize_name(item.item_name) == target:
                return item
        return None

    @classmethod
    def get_or_create_matching(cls, name):
        existing = cls.find_exact_match(name)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.save()
            return existing
        return cls.objects.create(item_name=name.strip(), is_active=True)


class Unit(models.Model):
    unit_name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "unit_name"]

    def __str__(self):
        return self.unit_name

    @classmethod
    def find_exact_match(cls, name):
        target = _normalize_name(name)
        for unit in cls.objects.all():
            if _normalize_name(unit.unit_name) == target:
                return unit
        return None

    @classmethod
    def get_or_create_matching(cls, name):
        existing = cls.find_exact_match(name)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.save()
            return existing
        return cls.objects.create(unit_name=name.strip(), is_active=True)


class Vendor(models.Model):
    vendor_name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "vendor_name"]

    def __str__(self):
        return self.vendor_name

    @classmethod
    def find_exact_match(cls, name):
        target = _normalize_name(name)
        for vendor in cls.objects.all():
            if _normalize_name(vendor.vendor_name) == target:
                return vendor
        return None

    @classmethod
    def get_or_create_matching(cls, name):
        existing = cls.find_exact_match(name)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.save()
            return existing
        return cls.objects.create(vendor_name=name.strip(), is_active=True)


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
            models.UniqueConstraint(fields=["county", "code", "subcategory_id"], condition=models.Q(is_active=True), name="unique_county_code_subcategory")
        ]
        ordering = ["-is_active", "county__county_name", "code__code_number", "subcategory_id"]

    def __str__(self):
        return str(self.county) + " - " + str(self.code.code_number) + "-" + str(self.subcategory_id)


class CountyItem(models.Model):
    """Categorizes items for a county within its specific categories."""
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    category = models.ForeignKey(CountyCategory, on_delete=models.PROTECT)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True)
    display_name = models.CharField(max_length=100, blank=True)
        # Optional county-specific override of item.item_name (e.g. "Green Peas" vs "Peas").
        # Never modifies the shared Item row, so other counties are unaffected.
    sort_order = models.IntegerField(default=0)
        # Allows the user to rearrange the items in the sheet view.
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "County items"
        constraints = [
            models.UniqueConstraint(fields=["item", "category", "unit"], condition=models.Q(is_active=True), name="unique_item_category_unit")
        ]
        ordering = ["-is_active", "category__county__county_name", "category__county__state__state_abbreviation", "category__code__code_number", "category__subcategory_id", "display_name"]

    def __str__(self):
        return str(self.category) + " - " + self.display + " - " + str(self.unit)

    @property
    def display(self):
        return self.display_name or self.item.item_name


class Inventory(models.Model):
    """Each instance represents the inventory of an item in a county within one week"""
    county_item = models.ForeignKey(CountyItem, on_delete=models.PROTECT)
    week = models.ForeignKey(Week, on_delete=models.PROTECT)
    end_price = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00")) # price per unit
    end_received_1 = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00")) # shipment(s) during the week
    end_received_2 = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    end_inventory = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    deep_dive = models.TextField(blank=True)
    is_new_item = models.BooleanField(default=False) 

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
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    invoice_number = models.CharField(max_length=100)
    tax = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-week__end_date", "week__county__county_name", "week__county__state__state_abbreviation", "vendor__vendor_name", "invoice_number"]

    def __str__(self):
        return str(self.vendor) + " - " + str(self.week)


class InvoiceLineItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT)
    code = models.ForeignKey(FoodCode, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invoice", "code"], name="unique_invoice_code")
        ]
        ordering = ["-invoice__week__end_date", "invoice__week__county__county_name", "invoice__week__county__state__state_abbreviation", "invoice__vendor__vendor_name", "code__code_number"]

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
            models.UniqueConstraint(fields=["county", "meal"], condition=models.Q(is_active=True), name="unique_county_meal")
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


class RecipeCode(models.Model):
    recipe_code = models.CharField(max_length=10, unique=True)
    recipe_code_name = models.CharField(max_length=100)

    class Meta:
        ordering = ["recipe_code"]

    def __str__(self):
        return self.recipe_code + " - " + self.recipe_code_name


class Recipe(models.Model):
    PORTIONS = 0
    SHEETPANS = 1
    serving_unit_options = {
        PORTIONS: "Portions",
        SHEETPANS: "Sheetpans",
    }

    recipe_code = models.ForeignKey(RecipeCode, on_delete=models.PROTECT)
    recipe_name = models.CharField(max_length=100)
    recipe_size = models.CharField(max_length=100)
    instructions = models.TextField(blank=True)
    serving_unit = models.IntegerField(choices=serving_unit_options, default=0)
        # Portions: ingredient amounts are per 100 servings, so the entered
        # count is divided by 100 before scaling. Sheetpans: amounts are per
        # 1 sheetpan, so the entered value multiplies directly, no division —
        # this is the distinction the client's spreadsheet doesn't make
        # explicit, which is why portion recipes require dividing by 100 by
        # hand today (same underlying math as sheetpans, applied inconsistently).

    class Meta:
        ordering = ["recipe_code__recipe_code", "recipe_name"]

    def __str__(self):
        return str(self.recipe_code.recipe_code) + " - " + self.recipe_name


class RecipeIngredient(models.Model):
    """ingredient_amt is the quantity required for 100 servings (or per 1 sheetpan,
    for Recipe.SHEETPANS recipes); the app scales this at display time based on
    the employee's entered amount."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient_name = models.CharField(max_length=100)
        # Doubles as the heading text when is_label is True (e.g. "Topping").
    ingredient_amt = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
        # Null for label rows (nothing to scale); required otherwise — see clean().
    ingredient_unit = models.CharField(max_length=50, blank=True)
    is_label = models.BooleanField(default=False)
        # True renders this row as a bold subheading (e.g. "Topping") instead
        # of an ingredient — no amount/unit, not included in the scaling math.
        # Where it appears in the list is controlled by sort_order, same as
        # any ingredient, so a recipe can have several labelled sections.
    sort_order = models.IntegerField(default=0)
        # Display order within the recipe (same pattern as CountyItem.sort_order).
        # Without this, ingredient order within one recipe isn't guaranteed —
        # Meta.ordering below only sorts by which recipe a row belongs to.

    class Meta:
        ordering = ["recipe__recipe_code__recipe_code", "recipe__recipe_name", "sort_order"]

    def __str__(self):
        return self.ingredient_name + " - " + str(self.recipe)

    def clean(self):
        if self.is_label:
            if self.ingredient_amt is not None or self.ingredient_unit:
                raise ValidationError("A label row shouldn't have an amount or unit.")
        elif self.ingredient_amt is None:
            raise ValidationError("Amount is required unless this is a label row.")


class CountyRecipe(models.Model):
    """Links a county to a recipe it uses, with a county-specific number within the
    recipe's code and an optional display name override (see CountyItem.display_name)."""
    county = models.ForeignKey(County, on_delete=models.PROTECT)
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE)
    recipe_number = models.CharField(max_length=10)
        # Text, not int: some codes number recipes "1A"/"1B". Zero-padded by
        # convention (e.g. "01") so plain alphabetical sort orders correctly.
    display_name = models.CharField(max_length=100, blank=True)
        # Optional county-specific override of recipe.recipe_name, same pattern
        # as CountyItem.display_name (e.g. two counties share a recipe *name*
        # in the app but it maps to a different underlying Recipe per county).
    last_servings = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
        # Autosaved from the servings/sheetpans input on the recipe view, so
        # the scaled amounts survive a refresh instead of resetting. Decimal
        # (not integer) because sheetpan-type recipes take fractional values
        # (e.g. 1.45) — the same field holds a whole-number portion count
        # just as validly. Left null until first saved; save() below fills in
        # a type-appropriate default (100 for portions, 1 for sheetpans) the
        # first time, since a single static default can't be right for both.
        # Shared county-wide state (employees share a per-county login, so
        # there's no per-person value to keep separately).

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["county", "recipe"], name="unique_county_recipe")
        ]
        ordering = ["county__county_name", "county__state__state_abbreviation", "recipe__recipe_code__recipe_code", "recipe_number"]

    def __str__(self):
        return str(self.county) + " - " + self.display

    @property
    def display(self):
        return self.display_name or self.recipe.recipe_name

    def clean(self):
        # recipe_number must be unique per county within a recipe code, but that
        # code lives on Recipe (one join away), so it can't be a DB constraint.
        if self.county_id and self.recipe_id and self.recipe_number:
            conflict = CountyRecipe.objects.filter(
                county_id=self.county_id,
                recipe__recipe_code_id=self.recipe.recipe_code_id,
                recipe_number=self.recipe_number,
            ).exclude(pk=self.pk)
            if conflict.exists():
                raise ValidationError(
                    f"Recipe number '{self.recipe_number}' is already used in this recipe code for this county."
                )

    def save(self, *args, **kwargs):
        if self.last_servings is None:
            self.last_servings = 100 if self.recipe.serving_unit == Recipe.PORTIONS else 1
        super().save(*args, **kwargs)