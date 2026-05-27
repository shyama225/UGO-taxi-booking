import os
import django
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ugoproject.settings')
django.setup()

from rides.models import User, Driver, Taxi, SubscriptionPlan, DriverSubscription

def setup_demo_drivers():
    drivers = User.objects.filter(is_driver=True)
    plan = SubscriptionPlan.objects.first()
    
    if not plan:
        plan = SubscriptionPlan.objects.create(
            name='Demo Plan',
            duration_type='monthly',
            duration_days=30,
            price=0,
            daily_ride_limit=10,
            daily_km_limit=100
        )

    # Base coords (roughly center of India or common test point)
    base_lat = 20.5937
    base_lng = 78.9629

    for i, user in enumerate(drivers):
        # 1. Ensure Driver Profile
        dp, created = Driver.objects.get_or_create(user=user)
        dp.status = 'available'
        dp.is_available = True
        dp.vehicle_type = 'sedan'
        # Scatter drivers slightly
        dp.latitude = base_lat + (i * 0.01)
        dp.longitude = base_lng + (i * 0.01)
        dp.save()
        
        # 2. Ensure Taxi
        if not hasattr(user, 'taxi'):
            Taxi.objects.create(
                driver=user,
                model_name=f'Demo Car {i+1}',
                plate_number=f'KL-01-AB-{1000+i}',
                taxi_type='sedan',
                color='White'
            )
            print(f"Created taxi for {user.username}")

        # 3. Ensure Subscription
        if not hasattr(user, 'subscription'):
            DriverSubscription.objects.create(
                driver=user,
                plan=plan,
                start_date=timezone.now().date(),
                end_date=timezone.now().date() + timedelta(days=30),
                is_active=True
            )
            print(f"Created subscription for {user.username}")
        
    print("Demo setup complete. Drivers are now online and available.")

if __name__ == '__main__':
    setup_demo_drivers()
