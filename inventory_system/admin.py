from django.contrib import admin
from .models import (
    State, Region, Manager, County, Employee, Week,
    WeeklyPayroll, WeeklySignoff, Item, FoodCode,
    CountyCategory, CountyItem, Inventory, Invoice,
    InvoiceLineItem, Meal, CountyMeal, DailySale,
)

admin.site.register(State)
admin.site.register(Region)
admin.site.register(Manager)
admin.site.register(County)
admin.site.register(Employee)
admin.site.register(Week)
admin.site.register(WeeklyPayroll)
admin.site.register(WeeklySignoff)
admin.site.register(Item)
admin.site.register(FoodCode)
admin.site.register(CountyCategory)
admin.site.register(CountyItem)
admin.site.register(Inventory)
admin.site.register(Invoice)
admin.site.register(InvoiceLineItem)
admin.site.register(Meal)
admin.site.register(CountyMeal)
admin.site.register(DailySale)