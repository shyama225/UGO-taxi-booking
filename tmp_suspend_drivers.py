import os
import django
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ugoproject.settings')
django.setup()

from rides.models import Driver
from django.utils import timezone

# Find drivers with average rating < 3.5 and total rides >= 5 who are still active
drivers = Driver.objects.filter(
    total_rides__gte=5, 
    average_rating__lt=3.5, 
    user__is_active=True
)

count = 0
for d in drivers:
    # Deactivate User account
    user = d.user
    user.is_active = False
    user.save(update_fields=['is_active'])
    
    # Set suspension period in Driver profile
    d.suspended_until = timezone.now() + timedelta(days=2)
    d.save(update_fields=['suspended_until'])
    
    print(f"Driver '{user.username}' (Rating: {d.average_rating}) has been suspended until {d.suspended_until}")
    count += 1

print(f"\nDone. Total drivers suspended: {count}")
