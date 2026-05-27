from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta
import random


# ---------------------------------------------------------------------------
# Custom User Model
# ---------------------------------------------------------------------------

class User(AbstractUser):
    """Custom user model with role-based authentication."""
    is_admin = models.BooleanField(default=False)
    is_user = models.BooleanField(default=False)
    is_driver = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=15, unique=True)
    profile_pic = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

class Pricing(models.Model):
    """Per-vehicle pricing configuration."""
    VEHICLE_TYPE_CHOICES = [
        ('mini', 'Mini'),
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('hatchback', 'Hatchback'),
        ('luxury', 'Luxury'),
    ]

    name = models.CharField(max_length=100)
    vehicle_type = models.CharField(
        max_length=20, choices=VEHICLE_TYPE_CHOICES, default='sedan'
    )
    base_fare = models.DecimalField(max_digits=10, decimal_places=2)
    per_km_rate = models.DecimalField(max_digits=10, decimal_places=2)
    per_minute_rate = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.vehicle_type})"


# ---------------------------------------------------------------------------
# Driver Profile (location + availability)
# ---------------------------------------------------------------------------

class Driver(models.Model):
    """
    Extended driver profile storing real-time location and availability.
    Linked 1-to-1 with a User that has is_driver=True.
    """
    VEHICLE_TYPE_CHOICES = [
        ('mini', 'Mini'),
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('hatchback', 'Hatchback'),
        ('luxury', 'Luxury'),
    ]

    STATUS_CHOICES = [
        ('available', 'Available'),
        ('busy', 'Busy'),
        ('offline', 'Offline'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='driver_profile'
    )
    vehicle_type = models.CharField(
        max_length=20, choices=VEHICLE_TYPE_CHOICES, default='sedan'
    )
    latitude = models.FloatField(default=0.0)
    longitude = models.FloatField(default=0.0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='available'
    )
    is_available = models.BooleanField(default=True)

    # Ratings snapshot (updated after each ride)
    average_rating = models.FloatField(default=0.0)
    total_rides = models.IntegerField(default=0)
    
    # Penalties tracking
    cancellation_count = models.IntegerField(default=0)
    low_rating_count = models.IntegerField(default=0)
    suspended_until = models.DateTimeField(null=True, blank=True)

    # New verification fields
    license_card = models.ImageField(upload_to='verification/license/', null=True, blank=True)
    rc_book = models.ImageField(upload_to='verification/rc_book/', null=True, blank=True)

    VERIFICATION_STATUS = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    verification_status = models.CharField(
        max_length=20, choices=VERIFICATION_STATUS, default='pending'
    )
    upi_id = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} [{self.get_status_display()}]"

    def set_available(self):
        self.status = 'available'
        self.is_available = True
        self.save(update_fields=['status', 'is_available'])

    def set_busy(self):
        self.status = 'busy'
        self.is_available = False
        self.save(update_fields=['status', 'is_available'])

    def set_offline(self):
        self.status = 'offline'
        self.is_available = False
        self.save(update_fields=['status', 'is_available'])


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class SubscriptionPlan(models.Model):
    """Subscription plans for drivers."""
    DURATION_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ]

    name = models.CharField(max_length=100)
    duration_type = models.CharField(max_length=20, choices=DURATION_CHOICES)
    duration_days = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    daily_ride_limit = models.IntegerField()
    daily_km_limit = models.IntegerField(default=100)  # Default 100km per day
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.duration_type}"


class DriverSubscription(models.Model):
    """A driver's active subscription."""
    driver = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='subscription'
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.SET_NULL, null=True
    )
    start_date = models.DateField()
    end_date = models.DateField()
    rides_used_today = models.IntegerField(default=0)
    km_used_today = models.FloatField(default=0.0)
    last_reset_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_expired(self):
        return self.end_date < timezone.now().date()

    @property
    def days_left(self):
        if self.is_expired:
            return 0
        delta = self.end_date - timezone.now().date()
        return delta.days

    def __str__(self):
        return f"{self.driver.username} - {self.plan.name if self.plan else 'No Plan'}"

    def can_accept_ride(self):
        if not self.is_active:
            return False, "Subscription is inactive."
        if not self.plan:
            return False, "No active plan."
        if self.end_date < timezone.now().date():
            return False, "Subscription expired."
        
        # Calculate total KM limit (Base Plan + Active Add-Ons)
        total_limit = float(self.plan.daily_km_limit)
        
        active_addons = DriverAddOn.objects.filter(
            driver=self.driver,
            is_active=True,
            expiry_date__gt=timezone.now()
        )
        for addon in active_addons:
            total_limit += float(addon.km_limit)
            
        if self.km_used_today >= total_limit:
            return False, f"Total daily limit ({total_limit}km) reached."
            
        return True, "Authorized"

    def increment_rides(self):
        self.rides_used_today += 1
        self.save(update_fields=['rides_used_today'])

    def reset_daily_rides(self):
        today = timezone.now().date()
        if self.last_reset_date != today:
            self.rides_used_today = 0
            self.km_used_today = 0.0
            self.last_reset_date = today
            self.save(update_fields=['rides_used_today', 'km_used_today', 'last_reset_date'])

    def increment_km(self, km):
        self.km_used_today += float(km)
        self.save(update_fields=['km_used_today'])


class SubscriptionPayment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    driver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscription_payments')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Sub Payment #{self.id} - {self.driver.username} - {self.amount}"

    def complete_payment(self, payment_id, signature):
        self.status = 'completed'
        self.razorpay_payment_id = payment_id
        self.razorpay_signature = signature
        self.save()

    @property
    def end_date_calc(self):
        """Returns end_date or calculates it based on plan duration from created_at."""
        if self.end_date:
            return self.end_date
        if self.plan and self.created_at:
            local_created = timezone.localtime(self.created_at)
            return (local_created + timedelta(days=self.plan.duration_days)).date()
        return None

    @property
    def start_date_calc(self):
        """Returns start_date or falls back to created_at date."""
        if self.start_date:
            return self.start_date
        if self.created_at:
            return timezone.localtime(self.created_at).date()
        return None


# ---------------------------------------------------------------------------
# Add-On Module
# ---------------------------------------------------------------------------

class AddOnPlan(models.Model):
    """Add-on plans for drivers when daily limit is reached."""
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    ride_limit = models.IntegerField(default=0)
    km_limit = models.IntegerField(default=0, help_text="Extra KM quota granted by this add-on (0 = no KM boost)")
    validity_days = models.IntegerField(default=1)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class DriverAddOn(models.Model):
    """An add-on purchased by a driver."""
    driver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='add_ons')
    plan = models.ForeignKey(AddOnPlan, on_delete=models.SET_NULL, null=True)
    purchase_date = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField()
    rides_limit = models.IntegerField(default=0)
    rides_used = models.IntegerField(default=0)
    km_limit = models.IntegerField(default=0)
    km_used = models.FloatField(default=0.0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.driver.username} - {self.plan.name if self.plan else 'Unknown'}"


class AddOnPayment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    driver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addon_payments')
    plan = models.ForeignKey(AddOnPlan, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Add-On Payment #{self.id} - {self.driver.username}"


# ---------------------------------------------------------------------------
# Taxi (vehicle registration)
# ---------------------------------------------------------------------------

class Taxi(models.Model):
    TAXI_TYPES = [
        ('mini', 'Mini'),
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('hatchback', 'Hatchback'),
        ('luxury', 'Luxury'),
    ]

    driver = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='taxi'
    )
    model_name = models.CharField(max_length=100)
    plate_number = models.CharField(max_length=20, unique=True)
    taxi_type = models.CharField(max_length=20, choices=TAXI_TYPES)
    capacity = models.IntegerField(default=4)
    color = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.model_name} ({self.plate_number})"


# ---------------------------------------------------------------------------
# Ride
# ---------------------------------------------------------------------------

class Ride(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('mini', 'Mini'),
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('hatchback', 'Hatchback'),
        ('luxury', 'Luxury'),
    ]

    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('accepted', 'Accepted'),
        ('arrived', 'Arrived'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
    ]

    rider = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='rides'
    )
    driver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='driver_rides'
    )

    # Locations
    pickup_location = models.CharField(max_length=255, blank=True, null=True)
    pickup_lat = models.FloatField(default=0.0)
    pickup_lng = models.FloatField(default=0.0)
    drop_address = models.CharField(max_length=255, blank=True, null=True)
    drop_lat = models.FloatField(default=0.0)
    drop_lng = models.FloatField(default=0.0)

    # Vehicle type requested by the user
    vehicle_type = models.CharField(
        max_length=20, choices=VEHICLE_TYPE_CHOICES, default='sedan'
    )

    # Matching metadata
    matched_distance_km = models.FloatField(
        null=True, blank=True,
        help_text="Distance (km) between pickup and the matched driver at time of matching"
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='requested'
    )

    otp = models.CharField(max_length=6, null=True, blank=True)
    is_paid = models.BooleanField(default=False)

    distance_km = models.FloatField(null=True, blank=True)
    estimated_fare = models.FloatField(null=True, blank=True)
    actual_fare = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField(blank=True)

    requested_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ride #{self.id} — {self.rider.username} [{self.status}]"

    def get_driver_taxi(self):
        if self.driver and hasattr(self.driver, 'taxi'):
            return self.driver.taxi
        return None

    def generate_otp(self):
        self.otp = str(random.randint(1000, 9999))
        self.save(update_fields=['otp'])
        return self.otp

    def calculate_estimated_fare(self, pricing):
        """Calculate fare using the pricing object for the requested vehicle type."""
        if pricing and self.distance_km:
            base = float(pricing.base_fare)
            km_rate = float(pricing.per_km_rate)
            self.estimated_fare = round(base + float(self.distance_km) * km_rate, 2)
            self.save(update_fields=['estimated_fare'])
            return self.estimated_fare
        return 0


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class Payment(models.Model):
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('upi', 'UPI'),
        ('paypal', 'PayPal'),
        ('credit_card', 'Credit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('razorpay', 'Razorpay'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    transaction_id = models.CharField(max_length=100, blank=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending'
    )
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment #{self.id} — {self.amount}"

    def complete_payment(self, transaction_id=None):
        self.status = 'completed'
        self.is_paid = True
        if transaction_id:
            self.transaction_id = transaction_id
        self.save()


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------

class Rating(models.Model):
    RATING_CHOICES = [(i, f'{i} Star{"s" if i > 1 else ""}') for i in range(1, 6)]

    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name='ratings')
    rider = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='ratings_given'
    )
    driver = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='ratings_received'
    )
    rating = models.IntegerField(choices=RATING_CHOICES)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rating {self.rating}★ by {self.rider.username} → {self.driver.username}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update driver profile average rating snapshot
        try:
            dp = self.driver.driver_profile
            all_ratings = Rating.objects.filter(driver=self.driver)
            avg = all_ratings.aggregate(models.Avg('rating'))['rating__avg'] or 0
            dp.average_rating = round(avg, 2)
            dp.total_rides = all_ratings.count()
            
            # Sub-3.5 average rating suspension (New Rule)
            # Only trigger after multiple rides (e.g., at least 5 ratings)
            if dp.total_rides >= 5 and dp.average_rating < 3.50:
                self.driver.is_active = False
                self.driver.save(update_fields=['is_active'])
                dp.suspended_until = timezone.now() + timedelta(days=2)
            
            # Single low rating tracking (Already exists)
            if self.rating < 3.5:
                dp.low_rating_count += 1
                if dp.low_rating_count >= 3:
                    self.driver.is_active = False
                    self.driver.save(update_fields=['is_active'])
            
            dp.save(update_fields=['average_rating', 'total_rides', 'low_rating_count', 'suspended_until'])
        except Driver.DoesNotExist:
            pass


# ---------------------------------------------------------------------------
# Ride Request tracking
# ---------------------------------------------------------------------------

class RideRequest(models.Model):
    """Track individual driver responses to a ride."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]

    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name='requests')
    driver = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='ride_requests'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"RideRequest — {self.driver.username} for Ride #{self.ride.id}"


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------

class Earning(models.Model):
    driver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earnings')
    ride = models.OneToOneField(Ride, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Earning #{self.id} — {self.driver.username}: ₹{self.amount}"
