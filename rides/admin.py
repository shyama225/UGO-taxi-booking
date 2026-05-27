from django.contrib import admin
from .models import (
    User, Pricing, SubscriptionPlan, DriverSubscription, Taxi, Ride, Payment,
    Rating, AddOnPlan, DriverAddOn, AddOnPayment
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active')
    search_fields = ('username', 'email')

@admin.register(Pricing)
class PricingAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_fare', 'per_km_rate', 'per_minute_rate', 'created_at')
    search_fields = ('name',)

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_type', 'duration_days', 'price', 'daily_ride_limit', 'is_active')
    list_filter = ('duration_type', 'is_active')
    search_fields = ('name',)

@admin.register(DriverSubscription)
class DriverSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('driver', 'plan', 'start_date', 'end_date', 'rides_used_today', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('driver__username',)

@admin.register(Taxi)
class TaxiAdmin(admin.ModelAdmin):
    list_display = ('driver', 'model_name', 'plate_number', 'taxi_type', 'color', 'is_active')
    list_filter = ('taxi_type', 'is_active')
    search_fields = ('driver__username', 'plate_number', 'model_name')

@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    # list_display = ('id', 'rider', 'driver', 'pickup_location', 'dropoff_location', 'status', 'requested_at', 'completed_at')
    list_display = ('id', 'rider', 'driver', 'status')

    list_filter = ('status', 'requested_at')
    search_fields = ('rider__username', 'driver__username', 'pickup_location', 'dropoff_location')
    date_hierarchy = 'requested_at'

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('ride', 'amount', 'payment_method', 'status', 'created_at')
    list_filter = ('payment_method', 'status', 'created_at')
    search_fields = ('ride__rider__username', 'transaction_id')

@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('ride', 'rider', 'driver', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('rider__username', 'driver__username')


@admin.register(AddOnPlan)
class AddOnPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'ride_limit', 'validity_days', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)

@admin.register(DriverAddOn)
class DriverAddOnAdmin(admin.ModelAdmin):
    list_display = ('driver', 'plan', 'expiry_date', 'rides_limit', 'rides_used', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('driver__username',)

@admin.register(AddOnPayment)
class AddOnPaymentAdmin(admin.ModelAdmin):
    list_display = ('driver', 'plan', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('driver__username', 'razorpay_order_id')
