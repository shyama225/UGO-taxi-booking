#!/usr/bin/env python
"""Create initial data for UGo application"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ugoproject.settings')
django.setup()

from rides.models import Pricing, SubscriptionPlan

# Create default pricing
if not Pricing.objects.exists():
    Pricing.objects.create(
        name='Standard',
        base_fare=2.50,
        per_km_rate=1.50,
        per_minute_rate=0.25
    )
    print("Created default pricing")

# Create subscription plans
if not SubscriptionPlan.objects.exists():
    SubscriptionPlan.objects.create(
        name='Daily Basic',
        duration_type='daily',
        duration_days=1,
        price=5.00,
        daily_ride_limit=5,
        description='Perfect for part-time drivers'
    )
    SubscriptionPlan.objects.create(
        name='Weekly Pro',
        duration_type='weekly',
        duration_days=7,
        price=29.99,
        daily_ride_limit=15,
        description='Great for regular drivers'
    )
    SubscriptionPlan.objects.create(
        name='Monthly Elite',
        duration_type='monthly',
        duration_days=30,
        price=99.99,
        daily_ride_limit=25,
        description='Best for full-time drivers'
    )
    SubscriptionPlan.objects.create(
        name='Yearly Ultimate',
        duration_type='yearly',
        duration_days=365,
        price=899.99,
        daily_ride_limit=30,
        description='Maximum benefits for professional drivers'
    )
    print("Created subscription plans")

print("Initial data created successfully!")
