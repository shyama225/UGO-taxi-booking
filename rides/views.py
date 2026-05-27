from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta
import random
from decimal import Decimal
import razorpay
from django.conf import settings
import json
import csv
import json
from io import BytesIO
from xhtml2pdf import pisa
from django.template.loader import get_template
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden

from django.db.models import Avg, Sum

from .models import (
    Driver, Earning, User, Pricing, SubscriptionPlan, DriverSubscription, Taxi, Ride,
    Payment, Rating, AddOnPlan, DriverAddOn, AddOnPayment, SubscriptionPayment, RideRequest
)
from django.contrib import messages
from .utils import haversine
from .matching import match_driver_for_ride, get_nearby_drivers, SEARCH_RADIUS_KM, FALLBACK_RADIUS_KM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Public Views
# ---------------------------------------------------------------------------

def home(request):
    """Home page — redirect authenticated users to their dashboard."""
    if request.user.is_authenticated:
        if request.user.is_admin or request.user.is_superuser:
            return redirect('admin_dashboard')
        elif request.user.is_driver:
            return redirect('driver_dashboard')
        else:
            return redirect('user_dashboard')
    return render(request, 'home.html')


def login_view(request):
    """Login for all user types."""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        # Check for inactive/suspended users before authentication
        try:
            user_check = User.objects.get(username=username)
            if user_check.check_password(password) and not user_check.is_active:
                if user_check.is_driver:
                    try:
                        dp = user_check.driver_profile
                        
                        # Check Verification Status first
                        if dp.verification_status == 'pending':
                            return render(request, 'login.html', {'error': 'Your registration is pending admin approval. Please wait for the confirmation.'})
                        elif dp.verification_status == 'rejected':
                            return render(request, 'login.html', {'error': 'Your registration was rejected. Please contact support for more details.'})

                        # Auto-reactivate if suspension period is over
                        if dp.suspended_until and dp.suspended_until <= timezone.now():
                            user_check.is_active = True
                            user_check.save(update_fields=['is_active'])
                            dp.suspended_until = None
                            # Reset penalty counts upon reactivation
                            dp.cancellation_count = 0
                            dp.low_rating_count = 0
                            dp.save(update_fields=['suspended_until', 'cancellation_count', 'low_rating_count'])
                        else:
                            if dp.average_rating < 3.5:
                                return render(request, 'login.html', {'error': 'your account is suspended for 2 days, due to low rating'})
                            if dp.cancellation_count >= 3:
                                return render(request, 'login.html', {'error': 'You are suspended due to continuous cancellation'})
                            if dp.low_rating_count >= 3:
                                return render(request, 'login.html', {'error': 'You are suspended due to continuous low ratings'})
                    except Driver.DoesNotExist:
                        pass
                if not user_check.is_active:
                    return render(request, 'login.html', {'error': 'Your account has been suspended'})
        except User.DoesNotExist:
            pass

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if user.is_admin or user.is_superuser:
                return redirect('admin_dashboard')
            elif user.is_driver:
                # Check subscription and warn if expired
                try:
                    sub = user.subscription
                    can_accept, message = sub.can_accept_ride()
                    if not can_accept:
                        messages.warning(request, f"Subscription Alert: {message}")
                except DriverSubscription.DoesNotExist:
                    messages.warning(request, "Welcome! Please subscribe to a plan to start accepting rides.")
                return redirect('driver_dashboard')
            else:
                return redirect('user_dashboard')
        else:
            return render(request, 'login.html', {'error': 'Invalid credentials'})
    return render(request, 'login.html')


def signup_view(request):
    """Signup for Admin, User, and Driver."""
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        phone = request.POST.get('phone')
        role = request.POST.get('role')

        if User.objects.filter(username=username).exists():
            return render(request, 'signup.html', {'error': 'Username already exists'})
        
        if User.objects.filter(email=email).exists():
            return render(request, 'signup.html', {'error': 'Email address already exists'})
            
        if User.objects.filter(phone_number=phone).exists():
            return render(request, 'signup.html', {'error': 'Phone number already registered'})

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            phone_number=phone,
            is_admin=(role == 'admin'),
            is_user=(role == 'user'),
            is_driver=(role == 'driver'),
        )

        # Handle Driver Registration Approval Workflow
        if role == 'driver':
            user.is_active = False # Keep inactive until admin approves
            user.save()
            
            Driver.objects.create(
                user=user,
                vehicle_type='sedan',
                latitude=0.0,
                longitude=0.0,
                status='available',
                is_available=True,
                license_card=request.FILES.get('license_card'),
                rc_book=request.FILES.get('rc_book'),
                upi_id=request.POST.get('upi_id'),
                verification_status='pending'
            )
            return render(request, 'login.html', {
                'success': 'Registration successful! Your account is pending admin approval. You will be able to login once approved.'
            })

        # Auto-login for Users and Admins
        login(request, user)
        if role == 'admin':
            return redirect('admin_dashboard')
        else:
            return redirect('user_dashboard')

    return render(request, 'signup.html')


@login_required
def logout_view(request):
    """Logout and redirect to home."""
    logout(request)
    return redirect('home')


# ===========================================================================
# ADMIN DASHBOARD
# ===========================================================================

@login_required
def admin_dashboard(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    context = {
        'total_users': User.objects.filter(is_user=True).count(),
        'total_drivers': User.objects.filter(is_driver=True).count(),
        'total_rides': Ride.objects.count(),
        'today_rides': Ride.objects.filter(requested_at__date=timezone.now().date()).count(),
        'recent_rides': Ride.objects.order_by('-requested_at')[:10],
    }
    return render(request, 'admin/dashboard.html', context)


@login_required
def admin_manage_users(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    users = User.objects.filter(is_user=True)
    
    query = request.GET.get('q')
    status = request.GET.get('status')
    
    if query:
        users = users.filter(username__icontains=query) | users.filter(email__icontains=query) | users.filter(phone_number__icontains=query)
    
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'suspended':
        users = users.filter(is_active=False)
        
    return render(request, 'admin/manage_users.html', {
        'users': users,
        'query': query,
        'status': status
    })


@login_required
def admin_delete_user(request, user_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    user = get_object_or_404(User, id=user_id, is_user=True)
    user.delete()
    messages.success(request, "User account has been permanently deleted.")
    return redirect('admin_manage_users')


@login_required
def admin_toggle_user_status(request, user_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    user = get_object_or_404(User, id=user_id, is_user=True)
    user.is_active = not user.is_active
    user.save()
    status = "activated" if user.is_active else "suspended"
    messages.info(request, f"User account has been {status}.")
    return redirect('admin_manage_users')


@login_required
def admin_manage_drivers(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    drivers = User.objects.filter(is_driver=True).select_related('subscription__plan', 'driver_profile')
    
    query = request.GET.get('q')
    status = request.GET.get('status')
    plan_id = request.GET.get('plan')
    
    if query:
        drivers = drivers.filter(username__icontains=query) | drivers.filter(email__icontains=query) | drivers.filter(phone_number__icontains=query)
    
    if status:
        drivers = drivers.filter(driver_profile__verification_status=status)

    if plan_id:
        drivers = drivers.filter(subscription__plan_id=plan_id)
        
    plans = SubscriptionPlan.objects.filter(is_active=True)
        
    return render(request, 'admin/manage_drivers.html', {
        'drivers': drivers,
        'query': query,
        'status': status,
        'plan_id': plan_id,
        'plans': plans
    })


@login_required
def admin_register_driver(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        password = request.POST.get('password')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return render(request, 'admin/register_driver.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email address already exists")
            return render(request, 'admin/register_driver.html')

        if User.objects.filter(phone_number=phone).exists():
            messages.error(request, "Phone number already registered")
            return render(request, 'admin/register_driver.html')
            
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            phone_number=phone,
            is_driver=True
        )
        
        # Initialize Driver profile
        Driver.objects.create(
            user=user,
            vehicle_type='sedan',
            status='available',
            is_available=True,
            upi_id=request.POST.get('upi_id'),
            verification_status='approved'
        )
        
        messages.success(request, f"Driver {username} registered successfully!")
        return redirect('admin_manage_drivers')
        
    return render(request, 'admin/register_driver.html')


@login_required
def admin_view_driver(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    driver = get_object_or_404(User, id=driver_id, is_driver=True)
    driver_profile = getattr(driver, 'driver_profile', None)
    taxi = getattr(driver, 'taxi', None)
    
    # Get recent rides and earnings
    recent_rides = Ride.objects.filter(driver=driver).select_related('rider').order_by('-requested_at')[:10]
    total_earnings = Earning.objects.filter(driver=driver).aggregate(total=Sum('amount'))['total'] or 0
    total_km_traveled = Ride.objects.filter(driver=driver, status='completed').aggregate(total=Sum('distance_km'))['total'] or 0
    
    # Calculate financials
    platform_commission = 0
    net_earnings = total_earnings
    
    # Calculate subscription usage percentages
    km_usage_percent = 0
    subscription = getattr(driver, 'subscription', None)
    if subscription and subscription.plan:
        if subscription.plan.daily_km_limit > 0:
            km_usage_percent = min(100, (subscription.km_used_today / subscription.plan.daily_km_limit) * 100)
    
    context = {
        'driver': driver,
        'driver_profile': driver_profile,
        'taxi': taxi,
        'recent_rides': recent_rides,
        'total_earnings': total_earnings,
        'platform_commission': platform_commission,
        'net_earnings': net_earnings,
        'km_usage_percent': km_usage_percent,
        'total_km_traveled': total_km_traveled,
    }
    return render(request, 'admin/view_driver.html', context)


@login_required
def admin_delete_driver(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    driver = get_object_or_404(User, id=driver_id, is_driver=True)
    driver.delete()
    return redirect('admin_manage_drivers')


@login_required
def admin_toggle_driver_status(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    driver = get_object_or_404(User, id=driver_id, is_driver=True)
    
    driver.is_active = not driver.is_active
    driver.save()
    
    # If unblocking, reset penalties
    if driver.is_active:
        try:
            dp = driver.driver_profile
            dp.cancellation_count = 0
            dp.low_rating_count = 0
            dp.save(update_fields=['cancellation_count', 'low_rating_count'])
        except Driver.DoesNotExist:
            pass
            
    status = "activated" if driver.is_active else "suspended"
    messages.info(request, f"Driver account has been {status}.")
    return redirect('admin_manage_drivers')


@login_required
def admin_approve_driver(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    driver_user = get_object_or_404(User, id=driver_id, is_driver=True)
    try:
        dp = driver_user.driver_profile
        dp.verification_status = 'approved'
        dp.save()
        
        driver_user.is_active = True
        driver_user.save()
        messages.success(request, f"Driver {driver_user.username} has been approved.")
    except Driver.DoesNotExist:
        messages.error(request, "Driver profile not found.")
        
    return redirect('admin_view_driver', driver_id=driver_id)


@login_required
def admin_send_approval_email(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    driver_user = get_object_or_404(User, id=driver_id, is_driver=True)
    
    try:
        subject = 'UGo Ride — Application Approved!'
        message = (
            f'Hi {driver_user.username},\n\n'
            f'Congratulations! Your application to join UGo Ride as a partner has been approved.\n\n'
            f'Your account is now active, and you can start accepting ride requests immediately. '
            f'Here are a few next steps to get you started:\n'
            f'1. Login to your dashboard using your registered credentials.\n'
            f'2. Ensure your vehicle details are up to date.\n'
            f'3. Check your subscription status to start receiving ride requests.\n\n'
            f'We are excited to have you on board! If you have any questions, please feel free to reach out to our support team.\n\n'
            f'Best regards,\nThe UGo Ride Team'
        )
        recipient_list = [driver_user.email]
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
        messages.success(request, f"Email send to {driver_user.username} sucessfully.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {str(e)}")
        
    return redirect('admin_view_driver', driver_id=driver_id)


@login_required
def admin_send_rejection_email(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    driver_user = get_object_or_404(User, id=driver_id, is_driver=True)
    
    try:
        subject = 'UGo Ride — Application Status Update'
        message = (
            f'Hi {driver_user.username},\n\n'
            f'Thank you for your interest in joining UGo Ride. After reviewing your application and documents, '
            f'we regret to inform you that your application has been rejected at this time due to invalid or '
            f'incomplete documentation.\n\n'
            f'Please ensure all your documents (License, RC Book, etc.) are clear and valid before trying again.\n\n'
            f'Best regards,\nUGo Ride Team'
        )
        recipient_list = [driver_user.email]
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
        messages.success(request, f"Rejection email sent to {driver_user.username} successfully.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {str(e)}")
        
    return redirect('admin_view_driver', driver_id=driver_id)


@login_required
def admin_reject_driver(request, driver_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    driver_user = get_object_or_404(User, id=driver_id, is_driver=True)
    try:
        dp = driver_user.driver_profile
        dp.verification_status = 'rejected'
        dp.save()
        
        driver_user.is_active = False
        driver_user.save()
        
        # Automatically send rejection email
        try:
            subject = 'UGo Ride — Application Status Update'
            message = (
                f'Hi {driver_user.username},\n\n'
                f'Thank you for your interest in joining UGo Ride. After reviewing your application and documents, '
                f'we regret to inform you that your application has been rejected at this time due to invalid or '
                f'incomplete documentation.\n\n'
                f'Please ensure all your documents (License, RC Book, etc.) are clear and valid before trying again.\n\n'
                f'Best regards,\nUGo Ride Team'
            )
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [driver_user.email], fail_silently=True)
        except:
            pass
            
        messages.warning(request, f"Driver {driver_user.username} has been rejected and notified via email.")
    except Driver.DoesNotExist:
        messages.error(request, "Driver profile not found.")
        
    return redirect('admin_view_driver', driver_id=driver_id)


@login_required
def admin_manage_rides(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    rides = Ride.objects.all().select_related('rider', 'driver')
    
    date_filter = request.GET.get('date')
    status = request.GET.get('status')
    query = request.GET.get('q')
    
    if date_filter:
        rides = rides.filter(requested_at__date=date_filter)
    
    if status:
        rides = rides.filter(status=status)
        
    if query:
        rides = rides.filter(rider__username__icontains=query) | rides.filter(driver__username__icontains=query)
        
    rides = rides.order_by('-requested_at')
    
    # Cap non-filtered results to 50 for performance
    if not (date_filter or status or query):
        rides = rides[:50]
        
    return render(request, 'admin/manage_rides.html', {
        'rides': rides, 
        'date_filter': date_filter,
        'status': status,
        'query': query
    })


@login_required
def admin_manage_pricing(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    pricing = Pricing.objects.all()
    return render(request, 'admin/manage_pricing.html', {'pricing': pricing})


@login_required
def admin_add_pricing(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        Pricing.objects.create(
            name=request.POST.get('name'),
            base_fare=request.POST.get('base_fare'),
            per_km_rate=request.POST.get('per_km_rate'),
            per_minute_rate=request.POST.get('per_minute_rate'),
        )
        return redirect('admin_manage_pricing')
    return render(request, 'admin/add_pricing.html')


@login_required
def admin_edit_pricing(request, pricing_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    pricing = get_object_or_404(Pricing, id=pricing_id)
    if request.method == 'POST':
        pricing.name = request.POST.get('name')
        pricing.base_fare = request.POST.get('base_fare')
        pricing.per_km_rate = request.POST.get('per_km_rate')
        pricing.per_minute_rate = request.POST.get('per_minute_rate')
        pricing.save()
        messages.success(request, f"Pricing '{pricing.name}' updated successfully.")
        return redirect('admin_manage_pricing')
    return render(request, 'admin/edit_pricing.html', {'pricing': pricing})


@login_required
def admin_delete_pricing(request, pricing_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    pricing = get_object_or_404(Pricing, id=pricing_id)
    pricing.delete()
    return redirect('admin_manage_pricing')


@login_required
def admin_manage_subscriptions(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    plans = SubscriptionPlan.objects.all()
    return render(request, 'admin/manage_subscriptions.html', {'plans': plans})


@login_required
def admin_add_subscription(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        duration_map = {'daily': 1, 'weekly': 7, 'monthly': 30, 'yearly': 365}
        SubscriptionPlan.objects.create(
            name=request.POST.get('name'),
            duration_type=request.POST.get('duration_type'),
            duration_days=duration_map.get(request.POST.get('duration_type'), 1),
            price=request.POST.get('price'),
            daily_ride_limit=0, # No longer using daily ride limit
            daily_km_limit=request.POST.get('daily_km_limit', 100),
            description=request.POST.get('description'),
        )
        return redirect('admin_manage_subscriptions')
    return render(request, 'admin/add_subscription.html')


@login_required
def admin_edit_subscription(request, plan_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    
    if request.method == 'POST':
        duration_map = {'daily': 1, 'weekly': 7, 'monthly': 30, 'yearly': 365}
        
        plan.name = request.POST.get('name')
        plan.duration_type = request.POST.get('duration_type')
        plan.duration_days = duration_map.get(request.POST.get('duration_type'), 1)
        plan.price = request.POST.get('price')
        plan.daily_ride_limit = 0 # No longer using daily ride limit
        plan.daily_km_limit = request.POST.get('daily_km_limit', 100)
        plan.description = request.POST.get('description')
        plan.save()
        
        return redirect('admin_manage_subscriptions')
        
    return render(request, 'admin/edit_subscription.html', {'plan': plan})


@login_required
def admin_delete_subscription(request, plan_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    plan.delete()
    return redirect('admin_manage_subscriptions')


@login_required
def admin_manage_taxis(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    taxis = Taxi.objects.all()
    return render(request, 'admin/manage_taxis.html', {'taxis': taxis})


@login_required
def admin_add_taxi(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        driver = get_object_or_404(User, id=request.POST.get('driver_id'))
        plate_number = request.POST.get('plate_number')

        if Taxi.objects.filter(plate_number=plate_number).exists():
            messages.error(request, "A vehicle with this plate number is already registered.")
            drivers = User.objects.filter(is_driver=True, taxi__isnull=True)
            return render(request, 'admin/add_taxi.html', {'drivers': drivers})

        Taxi.objects.create(
            driver=driver,
            model_name=request.POST.get('model_name'),
            plate_number=plate_number,
            taxi_type=request.POST.get('taxi_type'),
            capacity=request.POST.get('capacity'),
            color=request.POST.get('color'),
        )
        messages.success(request, "Vehicle assigned to driver successfully.")
        return redirect('admin_manage_taxis')
    drivers = User.objects.filter(is_driver=True, taxi__isnull=True)
    return render(request, 'admin/add_taxi.html', {'drivers': drivers})


@login_required
def admin_delete_taxi(request, taxi_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    taxi = get_object_or_404(Taxi, id=taxi_id)
    taxi.delete()
    return redirect('admin_manage_taxis')


@login_required
def admin_view_ride_requests(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    rides = Ride.objects.filter(status='requested').order_by('-requested_at')
    return render(request, 'admin/ride_requests.html', {'rides': rides})


@login_required
def admin_profile(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    return render(request, 'admin/profile.html')


@login_required
def admin_update_profile(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        user = request.user
        user.email = request.POST.get('email')
        user.phone_number = request.POST.get('phone')
        if 'profile_pic' in request.FILES:
            user.profile_pic = request.FILES['profile_pic']
        user.save()
        return redirect('admin_profile')
    return redirect('admin_profile')


@login_required
def admin_manage_payments(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    payments = Payment.objects.all().select_related('ride', 'ride__rider', 'ride__driver')
    
    status = request.GET.get('status')
    method = request.GET.get('method')
    query = request.GET.get('q')
    
    if status:
        payments = payments.filter(status=status)
    
    if method:
        payments = payments.filter(payment_method=method)
        
    if query:
        payments = payments.filter(ride__rider__username__icontains=query) | payments.filter(ride__driver__username__icontains=query)
        
    payments = payments.order_by('-created_at')
    
    return render(request, 'admin/manage_payments.html', {
        'payments': payments,
        'status': status,
        'method': method,
        'query': query
    })


@login_required
def admin_manage_ratings(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    ratings = Rating.objects.all().order_by('-created_at')
    return render(request, 'admin/manage_ratings.html', {'ratings': ratings})


@login_required
def admin_manage_addon_payments(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    payments = AddOnPayment.objects.all().order_by('-created_at')
    return render(request, 'admin/manage_addon_payments.html', {'payments': payments})


@login_required
def admin_manage_driver_addons(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    addons = DriverAddOn.objects.all().order_by('-purchase_date')
    return render(request, 'admin/manage_driver_addons.html', {'addons': addons})


@login_required
def admin_manage_driver_subscriptions(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    subscriptions = DriverSubscription.objects.all().order_by('-start_date')
    return render(request, 'admin/manage_driver_subscriptions.html', {'subscriptions': subscriptions})


@login_required
def admin_reports(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    return render(request, 'admin/reports.html')


def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html = template.render(context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    return None


@login_required
def admin_download_report(request, report_type):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    
    # Filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status = request.GET.get('status')
    method = request.GET.get('method')
    plan_id = request.GET.get('plan')
    name = request.GET.get('name') or request.GET.get('q')
    report_format = request.GET.get('format', 'csv')

    headers = []
    data = []
    
    if report_type == 'users':
        # ... (no changes here)
        records = User.objects.filter(is_user=True)
        if date_from: records = records.filter(created_at__date__gte=date_from)
        if date_to: records = records.filter(created_at__date__lte=date_to)
        if status == 'active': records = records.filter(is_active=True)
        elif status == 'inactive': records = records.filter(is_active=False)
        if name: records = records.filter(username__icontains=name) | records.filter(first_name__icontains=name) | records.filter(last_name__icontains=name)
        
        headers = ['ID', 'Username', 'Email', 'Phone', 'Active', 'Joined Date']
        for u in records:
            data.append([u.id, u.username, u.email, u.phone_number, 'Yes' if u.is_active else 'No', u.created_at.strftime('%Y-%m-%d %H:%M')])
            
    elif report_type == 'drivers':
        records = User.objects.filter(is_driver=True).select_related('driver_profile', 'subscription__plan')
        if date_from: records = records.filter(created_at__date__gte=date_from)
        if date_to: records = records.filter(created_at__date__lte=date_to)
        if status: records = records.filter(driver_profile__verification_status=status)
        if plan_id: records = records.filter(subscription__plan_id=plan_id)
        if name: records = records.filter(username__icontains=name) | records.filter(first_name__icontains=name) | records.filter(last_name__icontains=name)
        
        headers = ['ID', 'Username', 'Active Plan', 'KM Used (Today)', 'KM Limit', 'Email', 'Phone', 'Status', 'Rating', 'Rides', 'Joined']
        for d in records:
            dp = getattr(d, 'driver_profile', None)
            sub = getattr(d, 'subscription', None)
            data.append([
                d.id, d.username, 
                sub.plan.name if sub and sub.plan else 'FREE TIER',
                sub.km_used_today if sub else 0,
                sub.plan.daily_km_limit if sub and sub.plan else 'N/A',
                d.email, d.phone_number, 
                dp.verification_status.upper() if dp else 'N/A',
                dp.average_rating if dp else 0,
                dp.total_rides if dp else 0,
                d.created_at.strftime('%Y-%m-%d')
            ])
            
    elif report_type == 'rides':
        records = Ride.objects.all().select_related('rider', 'driver')
        if date_from: records = records.filter(requested_at__date__gte=date_from)
        if date_to: records = records.filter(requested_at__date__lte=date_to)
        if status: records = records.filter(status=status)
        if name:
            records = records.filter(rider__username__icontains=name) | records.filter(driver__username__icontains=name)
            
        headers = ['ID', 'Rider', 'Driver', 'Pickup', 'Drop', 'Status', 'Fare', 'Date']
        for r in records:
            data.append([
                r.id, r.rider.username, r.driver.username if r.driver else 'N/A',
                r.pickup_location[:30] + '...' if len(r.pickup_location) > 30 else r.pickup_location, 
                r.drop_address[:30] + '...' if len(r.drop_address) > 30 else r.drop_address, 
                r.status.replace('_', ' ').title(),
                f"INR {r.actual_fare or r.estimated_fare}", 
                r.requested_at.strftime('%Y-%m-%d %H:%M')
            ])
            
    elif report_type == 'payments':
        records = Payment.objects.all().select_related('ride__rider', 'ride__driver')
        if date_from: records = records.filter(created_at__date__gte=date_from)
        if date_to: records = records.filter(created_at__date__lte=date_to)
        if status: records = records.filter(status=status)
        if method: records = records.filter(payment_method=method)
        if name:
            records = records.filter(ride__rider__username__icontains=name) | records.filter(ride__driver__username__icontains=name)
        
        headers = ['Ride ID', 'Rider', 'Driver', 'Amount', 'Method', 'Status', 'Date']
        for p in records:
            data.append([
                f"#RD-{p.ride.id:04d}", 
                p.ride.rider.username,
                p.ride.driver.username if p.ride.driver else 'Not Assigned',
                f"INR {p.amount}",
                p.payment_method.upper(), 
                p.status.upper(), 
                p.created_at.strftime('%Y-%m-%d %H:%M')
            ])

    filename = f"{report_type}_report_{timezone.now().strftime('%Y%m%d')}"

    if report_format == 'pdf':
        response = render_to_pdf('admin/report_pdf_template.html', {
            'title': f"{report_type.replace('_', ' ').title()} Report",
            'headers': headers,
            'data': data,
            'generated_at': timezone.now()
        })
        if response:
            response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
            return response
        return HttpResponse("Error generating PDF", status=500)

    # Default CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in data:
        writer.writerow(row)
    return response


# ===========================================================================
# USER DASHBOARD
# ===========================================================================

@login_required
def user_dashboard(request):
    if not (request.user.is_user or request.user.is_superuser or request.user.is_admin):
        return HttpResponseForbidden("Access denied")

    # Active ride (used to show OTP / ride progress)
    active_ride = Ride.objects.filter(
        rider=request.user,
        status__in=['requested', 'accepted', 'arrived', 'in_progress']
    ).first()

    # Ride history
    rides = Ride.objects.filter(rider=request.user).prefetch_related('ratings', 'payments').order_by('-requested_at')
    
    # Stats
    total_spent = Payment.objects.filter(ride__rider=request.user, status='completed').aggregate(total=Sum('amount'))['total'] or 0
    completed_rides_count = rides.filter(status='completed').count()

    return render(request, 'user/dashboard.html', {
        'active_ride': active_ride,
        'rides': rides,
        'total_spent': total_spent,
        'completed_rides_count': completed_rides_count,
    })


@login_required
def user_profile(request):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")
    return render(request, 'user/profile.html')


@login_required
def user_update_profile(request):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        user = request.user
        user.email = request.POST.get('email')
        user.phone_number = request.POST.get('phone')
        if 'profile_pic' in request.FILES:
            user.profile_pic = request.FILES['profile_pic']
        user.save()
        return redirect('user_profile')
    return redirect('user_profile')


@login_required
def user_ride_history(request):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")
    rides = Ride.objects.filter(rider=request.user, status='completed').prefetch_related('ratings', 'payments').order_by('-completed_at')
    return render(request, 'user/ride_history.html', {'rides': rides})


@login_required
def user_request_ride(request):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        vehicle_type = request.POST.get('vehicle_type', 'sedan')
        pickup_lat   = safe_float(request.POST.get('pickup_lat'))
        pickup_lng   = safe_float(request.POST.get('pickup_lng'))
        drop_lat     = safe_float(request.POST.get('drop_lat'))
        drop_lng     = safe_float(request.POST.get('drop_lng'))
        distance_km  = safe_float(request.POST.get('distance_km'))

        if distance_km <= 0:
            distance_km = round(haversine(pickup_lat, pickup_lng, drop_lat, drop_lng), 2)

        # Create the ride record first
        ride = Ride.objects.create(
            rider=request.user,
            pickup_location=request.POST.get('pickup_location', ''),
            drop_address=request.POST.get('drop_location', ''),
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            drop_lat=drop_lat,
            drop_lng=drop_lng,
            vehicle_type=vehicle_type,
            status='requested',
            distance_km=distance_km,
        )

        # Calculate estimated fare using vehicle-specific pricing
        pricing = Pricing.objects.filter(vehicle_type=vehicle_type).first() \
                  or Pricing.objects.first()
        if pricing:
            ride.calculate_estimated_fare(pricing)

        # Match driver
        result = match_driver_for_ride(ride)

        return redirect('user_ride_status', ride_id=ride.id)

    # Pre-load available vehicle types and nearby driver counts for the form
    pickup_lat = safe_float(request.GET.get('lat', 0))
    pickup_lng = safe_float(request.GET.get('lng', 0))

    vehicle_options = [
        {'value': 'mini',     'label': 'Mini',    'icon': '🚗', 'desc': 'Affordable, up to 4 passengers'},
        {'value': 'sedan',    'label': 'Sedan',   'icon': '🚙', 'desc': 'Comfortable, up to 4 passengers'},
        {'value': 'suv',      'label': 'SUV',     'icon': '🚐', 'desc': 'Spacious, up to 6 passengers'},
        {'value': 'hatchback','label': 'Hatchback','icon': '🚘', 'desc': 'Compact & economical'},
        {'value': 'luxury',   'label': 'Luxury',  'icon': '🏎️', 'desc': 'Premium ride experience'},
    ]

    pricing_data = {}
    for opt in vehicle_options:
        vt = opt['value']
        pricing = Pricing.objects.filter(vehicle_type=vt).first() or Pricing.objects.first()
        if pricing:
            pricing_data[vt] = {'base': float(pricing.base_fare), 'per_km': float(pricing.per_km_rate)}
        else:
            pricing_data[vt] = {'base': 45.0, 'per_km': 11.0}

    return render(request, 'user/request_ride.html', {
        'vehicle_options': vehicle_options,
        'search_radius_km': FALLBACK_RADIUS_KM,
        'pricing_data_json': json.dumps(pricing_data),
    })


@login_required
def user_available_drivers(request, ride_id):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, rider=request.user)

    # 1. Broad fetch for drivers with required setup
    drivers = User.objects.filter(is_driver=True, taxi__isnull=False, subscription__isnull=False)
    available_drivers = []
    
    for d_user in drivers:
        # 2. Check Driver Profile (Vehicle Type & Availability)
        dp = getattr(d_user, 'driver_profile', None)
        if not dp or dp.status != 'available' or not dp.is_available:
            continue
        if dp.vehicle_type != ride.vehicle_type:
            continue

        # 3. Check Distance
        dist = haversine(ride.pickup_lat, ride.pickup_lng, dp.latitude, dp.longitude)
        if dist > FALLBACK_RADIUS_KM: # Filter by radius
            continue

        # 4. Check Subscription
        sub = getattr(d_user, 'subscription', None)
        if sub and sub.can_accept_ride()[0]:
            d_user.proximity_km = round(dist, 1)
            available_drivers.append(d_user)

    return render(request, 'user/available_drivers.html', {
        'ride': ride,
        'drivers': available_drivers,
    })


@login_required
def user_select_driver(request, ride_id, driver_id):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, rider=request.user)
    driver = get_object_or_404(User, id=driver_id, is_driver=True)

    # Security check: Ensure driver has valid subscription
    try:
        sub = driver.subscription
        can_accept, _ = sub.can_accept_ride()
        if not can_accept:
            messages.error(request, "Selected driver is no longer available.")
            return redirect('user_available_drivers', ride_id=ride.id)
    except DriverSubscription.DoesNotExist:
        messages.error(request, "Selected driver is no longer available.")
        return redirect('user_available_drivers', ride_id=ride.id)

    ride.driver = driver
    ride.status = 'accepted'
    ride.accepted_at = timezone.now()
    ride.save()

    # Reset driver's daily rides count if needed
    sub = getattr(driver, 'subscription', None)
    if sub:
        sub.reset_daily_rides()

    return redirect('user_dashboard')


@login_required
def user_cancel_ride(request, ride_id):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, rider=request.user)
    if ride.status in ['requested', 'accepted']:
        ride.status = 'cancelled'
        ride.save()
        messages.success(request, "Ride cancelled successfully.")

        # Free up the assigned driver profile if any
        if ride.driver:
            try:
                driver_profile = ride.driver.driver_profile
                driver_profile.is_available = True
                driver_profile.status = 'available'
                driver_profile.save()
            except Driver.DoesNotExist:
                pass
    else:
        messages.error(request, "Cannot cancel ride once it has started.")

    return redirect('user_dashboard')


@login_required
def user_ride_status(request, ride_id):
    ride = get_object_or_404(Ride, id=ride_id)
    return render(request, 'user/ride_status.html', {'ride': ride})


@login_required
def user_payment(request, ride_id):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, rider=request.user)

    # Ensure ride is completed
    if ride.status != 'completed':
        messages.error(request, "Ride not completed yet.")
        return redirect('user_dashboard')

    # Prevent double payment
    if ride.is_paid:
        messages.info(request, "Payment already completed.")
        return redirect('user_dashboard')

    amount = ride.actual_fare if ride.actual_fare else (ride.estimated_fare or Decimal('0.00'))
    amount_in_paise = int(float(amount) * 100)

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'cash')
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')

        if payment_method == 'razorpay' and razorpay_payment_id:
            try:
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                params_dict = {
                    'razorpay_order_id': razorpay_order_id,
                    'razorpay_payment_id': razorpay_payment_id,
                    'razorpay_signature': razorpay_signature
                }
                client.utility.verify_payment_signature(params_dict)
                status = 'completed'
            except Exception as e:
                messages.error(request, "Payment Verification Failed.")
                return redirect('user_payment', ride_id=ride.id)
        else:
            status = 'completed'

        Payment.objects.create(
            ride=ride,
            amount=amount,
            payment_method=payment_method,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_signature=razorpay_signature,
            status=status,
            is_paid=(status == 'completed')
        )

        ride.is_paid = True
        ride.save()

        # ---------------------------------------------------------------
        # Create Earning record for the driver (only on successful payment)
        # ---------------------------------------------------------------
        if status == 'completed' and ride.driver:
            # Avoid duplicate earnings for the same ride
            if not Earning.objects.filter(ride=ride).exists():
                Earning.objects.create(
                    driver=ride.driver,
                    ride=ride,
                    amount=amount,
                )

        messages.success(request, "Payment completed successfully 🎉")
        return redirect('user_dashboard')

    # Generate Razorpay Order
    razorpay_order_id = ""
    razorpay_error = ""
    try:
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        if amount_in_paise > 0:
            order = client.order.create({"amount": amount_in_paise, "currency": "INR", "payment_capture": "1"})
            razorpay_order_id = order['id']
    except Exception as e:
        razorpay_error = str(e)

    return render(request, 'user/payment.html', {
        'ride': ride,
        'razorpay_order_id': razorpay_order_id,
        'razorpay_key': getattr(settings, 'RAZORPAY_KEY_ID', ''),
        'amount_in_paise': amount_in_paise,
        'razorpay_error': razorpay_error,
        'user_name': request.user.get_full_name() or request.user.username,
        'user_email': request.user.email,
        'user_phone': getattr(request.user, 'phone_number', ''),
    })


@login_required
def user_rate_driver(request, ride_id):
    if not request.user.is_user:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, rider=request.user)

    if request.method == 'POST':
        try:
            rating_value = float(request.POST.get('rating', 0))
        except ValueError:
            rating_value = 0.0

        Rating.objects.create(
            ride=ride,
            rider=request.user,
            driver=ride.driver,
            rating=rating_value,
            comment=request.POST.get('comment', ''),
        )
        return redirect('user_dashboard')

    return render(request, 'user/rate_driver.html', {'ride': ride})


# ===========================================================================
# DRIVER DASHBOARD
# ===========================================================================

@login_required
def driver_dashboard(request):
    if not getattr(request.user, 'is_driver', False):
        return HttpResponseForbidden("Access denied")

    # Subscription info
    try:
        subscription = DriverSubscription.objects.get(driver=request.user)
        subscription.reset_daily_rides()
        can_accept, message_text = subscription.can_accept_ride()
    except DriverSubscription.DoesNotExist:
        subscription = None
        can_accept = False
        message_text = "No active subscription"

    # Get driver profile
    driver_profile = None
    try:
        driver_profile = request.user.driver_profile
    except Driver.DoesNotExist:
        pass

    # Auto-offline if subscription restricted and currently set as online
    if not can_accept and driver_profile and driver_profile.status == 'available':
        driver_profile.set_offline()

    km_left = 0
    plan_expires_today = False
    if subscription and subscription.plan:
        # Calculate TOTAL limit (Base + Add-Ons)
        total_km_limit = float(subscription.plan.daily_km_limit)
        active_addons = DriverAddOn.objects.filter(
            driver=request.user, is_active=True, expiry_date__gt=timezone.now()
        )
        for addon in active_addons:
            total_km_limit += float(addon.km_limit)

        km_left = max(0.0, total_km_limit - subscription.km_used_today)
        if subscription.end_date == timezone.now().date():
            plan_expires_today = True

    # Active ride (accepted or in_progress)
    active_ride = Ride.objects.filter(
        driver=request.user,
        status__in=['accepted', 'in_progress']
    ).first()

    # Handle POST actions
    if request.method == 'POST':
        if not active_ride:
            messages.error(request, "No active ride found.")
            return redirect('driver_dashboard')

        # OTP verification → start ride
        if 'otp_input' in request.POST:
            otp_input = request.POST.get('otp_input')
            if otp_input == str(active_ride.otp):
                active_ride.status = 'in_progress'
                active_ride.started_at = timezone.now()
                active_ride.otp = None
                active_ride.save()
                messages.success(request, "OTP verified. Ride started! 🚗")
            else:
                messages.error(request, "Invalid OTP. Please try again.")

        # Complete ride
        elif 'complete_ride' in request.POST:
            if active_ride.status != 'in_progress':
                messages.error(request, "Ride must be in progress to complete.")
            else:
                active_ride.status = 'completed'
                active_ride.completed_at = timezone.now()
                active_ride.save()

                # Update subscription ride count
                if subscription:
                    subscription.increment_rides()
                    if active_ride.distance_km:
                        subscription.increment_km(active_ride.distance_km)

                # Free up driver profile availability
                try:
                    driver_profile = request.user.driver_profile
                    driver_profile.is_available = True
                    driver_profile.status = 'available'
                    driver_profile.save()
                except Driver.DoesNotExist:
                    pass

                messages.success(request, "Ride completed. Waiting for payment 💳")

        return redirect('driver_dashboard')

    # 2. Filter available rides specifically for this driver
    available_rides = []
    if driver_profile:
        from django.db.models import Q
        from .models import RideRequest
        
        rejected_ride_ids = RideRequest.objects.filter(
            driver=request.user, status='rejected'
        ).values_list('ride_id', flat=True)

        # Show rides that match: status 'requested', same vehicle type, not requested by the driver themselves
        # Only show rides specifically matching this driver, or unassigned broadcast rides.
        potential_rides = Ride.objects.filter(
            Q(driver=request.user) | Q(driver__isnull=True),
            status='requested',
            vehicle_type=driver_profile.vehicle_type
        ).exclude(rider=request.user).exclude(id__in=rejected_ride_ids)

        # Apply proximity check (e.g. within 10km)
        for r in potential_rides:
            dist = haversine(
                driver_profile.latitude, driver_profile.longitude,
                r.pickup_lat, r.pickup_lng
            )
            if dist <= FALLBACK_RADIUS_KM:  # Matches rides within the defined radius
                r.proximity_km = round(dist, 1) # Set a temp attribute for the template
                available_rides.append(r)
    else:
        available_rides = []

    return render(request, 'driver/dashboard.html', {
        'subscription': subscription,
        'can_accept': can_accept,
        'message_text': message_text,
        'active_ride': active_ride,
        'available_rides': available_rides,
        'driver_profile': driver_profile,
        'search_radius': FALLBACK_RADIUS_KM,
        'plan_expires_today': plan_expires_today,
        'km_left': km_left,
    })


@login_required
def driver_earnings(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    earnings = Earning.objects.filter(driver=request.user).select_related('ride', 'ride__rider').prefetch_related('ride__payments').order_by('-created_at')
    total = earnings.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    today = timezone.now().date()
    today_earnings = earnings.filter(created_at__date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    month_earnings = earnings.filter(
        created_at__year=today.year,
        created_at__month=today.month
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_km_traveled = Ride.objects.filter(driver=request.user, status='completed').aggregate(total=Sum('distance_km'))['total'] or 0

    return render(request, 'driver/earnings.html', {
        'earnings': earnings,
        'total': total,
        'today_earnings': today_earnings,
        'month_earnings': month_earnings,
        'total_km_traveled': total_km_traveled,
    })


@login_required
def driver_profile(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    subscription = None
    try:
        subscription = DriverSubscription.objects.get(driver=request.user)
    except DriverSubscription.DoesNotExist:
        pass

    return render(request, 'driver/profile.html', {'subscription': subscription})


@login_required
def driver_update_profile(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        user = request.user
        user.email = request.POST.get('email')
        user.phone_number = request.POST.get('phone')
        if 'profile_pic' in request.FILES:
            user.profile_pic = request.FILES['profile_pic']
        user.save()

        upi_id = request.POST.get('upi_id')
        try:
            dp = user.driver_profile
            dp.upi_id = upi_id
            dp.save(update_fields=['upi_id'])
        except Driver.DoesNotExist:
            pass

        return redirect('driver_profile')
    return redirect('driver_profile')


@login_required
def driver_view_ratings(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    ratings = Rating.objects.filter(driver=request.user).order_by('-created_at')
    avg_rating = ratings.aggregate(avg=Avg('rating'))['avg'] or 0
    avg_rating = round(avg_rating, 2)
    return render(request, 'driver/ratings.html', {'ratings': ratings, 'avg_rating': avg_rating})


@login_required
def driver_subscription_plans(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    plans = SubscriptionPlan.objects.filter(is_active=True)
    current_subscription = None
    try:
        current_subscription = DriverSubscription.objects.get(driver=request.user)
    except DriverSubscription.DoesNotExist:
        pass

    return render(request, 'driver/subscription_plans.html', {
        'plans': plans,
        'current_subscription': current_subscription,
    })


@login_required
def driver_subscribe(request, plan_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    plan = get_object_or_404(SubscriptionPlan, id=plan_id)

    amount = plan.price
    amount_in_paise = int(float(amount) * 100)

    if request.method == 'POST':
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')
        upi_id = request.POST.get('upi_id')

        if razorpay_payment_id:
            try:
                # Update driver's UPI ID if provided
                if upi_id:
                    try:
                        dp = request.user.driver_profile
                        dp.upi_id = upi_id
                        dp.save(update_fields=['upi_id'])
                    except Driver.DoesNotExist:
                        pass
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                params_dict = {
                    'razorpay_order_id': razorpay_order_id,
                    'razorpay_payment_id': razorpay_payment_id,
                    'razorpay_signature': razorpay_signature
                }
                client.utility.verify_payment_signature(params_dict)

                # Calculate dates for both payment record and subscription update
                try:
                    existing_sub = DriverSubscription.objects.get(driver=request.user)
                    if existing_sub.plan == plan and not existing_sub.is_expired:
                        # Extend the existing subscription
                        start_date = existing_sub.start_date
                        end_date = existing_sub.end_date + timedelta(days=plan.duration_days)
                    else:
                        # New or Reactivate expired
                        start_date = timezone.now().date()
                        end_date = start_date + timedelta(days=plan.duration_days)
                except DriverSubscription.DoesNotExist:
                    start_date = timezone.now().date()
                    end_date = start_date + timedelta(days=plan.duration_days)

                # Save subscription payment with dates
                SubscriptionPayment.objects.create(
                    driver=request.user,
                    plan=plan,
                    amount=amount,
                    razorpay_order_id=razorpay_order_id,
                    razorpay_payment_id=razorpay_payment_id,
                    razorpay_signature=razorpay_signature,
                    status='completed',
                    start_date=start_date,
                    end_date=end_date
                )

                # Update or create active subscription record
                DriverSubscription.objects.update_or_create(
                    driver=request.user,
                    defaults={
                        'plan': plan,
                        'start_date': start_date,
                        'end_date': end_date,
                        'is_active': True,
                        'rides_used_today': 0,
                    }
                )
                messages.success(request, "Subscription activated successfully! 🎉")
                return redirect('driver_dashboard')

            except Exception as e:
                messages.error(request, "Payment Verification Failed.")
        else:
            messages.error(request, "Payment failed cleanly.")

        return redirect('driver_subscribe', plan_id=plan.id)

    # Generate Razorpay Order
    # Generate Razorpay Order
    razorpay_order_id = ""
    razorpay_error = ""
    try:
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        if amount_in_paise > 0:
            order = client.order.create({"amount": amount_in_paise, "currency": "INR", "payment_capture": "1"})
            razorpay_order_id = order['id']
    except Exception as e:
        razorpay_error = str(e)

    is_renewal = False
    try:
        existing_sub = DriverSubscription.objects.get(driver=request.user)
        if existing_sub.plan == plan and not existing_sub.is_expired:
            is_renewal = True
    except DriverSubscription.DoesNotExist:
        pass

    return render(request, 'driver/subscribe.html', {
        'plan': plan,
        'is_renewal': is_renewal,
        'razorpay_order_id': razorpay_order_id,
        'razorpay_key': getattr(settings, 'RAZORPAY_KEY_ID', ''),
        'amount_in_paise': amount_in_paise,
        'razorpay_error': razorpay_error,
        'user_name': request.user.get_full_name() or request.user.username,
        'user_email': request.user.email,
        'user_phone': getattr(request.user, 'phone_number', ''),
    })


@login_required
@require_POST
def driver_cancel_subscription(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")
    
    try:
        subscription = DriverSubscription.objects.get(driver=request.user)
        subscription.delete()
        messages.success(request, "Your subscription has been cancelled.")
    except DriverSubscription.DoesNotExist:
        messages.error(request, "You do not have an active subscription.")
        
    return redirect('driver_subscription_plans')


@login_required
def driver_add_taxi(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    if hasattr(request.user, 'taxi'):
        return redirect('driver_dashboard')

    if request.method == 'POST':
        plate_number = request.POST.get('plate_number')

        if Taxi.objects.filter(plate_number=plate_number).exists():
            messages.error(request, "A vehicle with this plate number is already registered.")
            return render(request, 'driver/add_taxi.html')

        Taxi.objects.create(
            driver=request.user,
            model_name=request.POST.get('model_name'),
            plate_number=plate_number,
            taxi_type=request.POST.get('taxi_type'),
            capacity=request.POST.get('capacity'),
            color=request.POST.get('color'),
        )
        messages.success(request, "Vehicle added successfully.")
        return redirect('driver_dashboard')

    return render(request, 'driver/add_taxi.html')


@login_required
def driver_ride_history(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    rides = Ride.objects.filter(driver=request.user).select_related('rider').prefetch_related('payments').order_by('-requested_at')

    for ride in rides:
        fare = ride.actual_fare or ride.estimated_fare or Decimal('0.00')
        ride.driver_earning = round(Decimal(str(fare)), 2)

    total_earnings = sum(ride.driver_earning for ride in rides)

    return render(request, 'driver/ride_history.html', {
        'rides': rides,
        'total_earnings': total_earnings,
    })


@login_required
def driver_accept_ride(request, ride_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    # Check subscription
    try:
        subscription = DriverSubscription.objects.get(driver=request.user)
        can_accept, message = subscription.can_accept_ride()
        if not can_accept:
            return render(request, 'driver/error.html', {'message': message})
    except DriverSubscription.DoesNotExist:
        return render(request, 'driver/error.html', {'message': 'No active subscription'})

    # Prevent accepting a second active ride
    if Ride.objects.filter(
        driver=request.user,
        status__in=['accepted', 'arrived', 'in_progress']
    ).exists():
        return render(request, 'driver/error.html', {'message': 'You already have an active ride'})

    ride = get_object_or_404(Ride, id=ride_id, status='requested')
    
    if ride.driver and ride.driver != request.user:
        messages.error(request, "This ride request was assigned to another driver.")
        return redirect('driver_dashboard')

    ride.driver = request.user
    ride.status = 'accepted'
    ride.accepted_at = timezone.now()
    ride.otp = str(random.randint(1000, 9999))
    ride.save()

    messages.success(request, "Ride accepted. Ask rider for OTP.")
    return redirect('driver_dashboard')


@login_required
def driver_reject_ride(request, ride_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, status='requested')
    
    # If the ride was explicitly assigned to this driver, unassign it and cancel it
    if ride.driver == request.user:
        ride.driver = None
        ride.status = 'cancelled'
        ride.save()
        
        # Reset driver availability so they can receive other requests
        try:
            dp = request.user.driver_profile
            dp.set_available()
        except Driver.DoesNotExist:
            pass
        
    # Record rejection so it doesn't show up again
    RideRequest.objects.get_or_create(ride=ride, driver=request.user, defaults={'status': 'rejected'})
    
    # Track cancellations/rejections and penalize
    try:
        from django.contrib.auth import logout
        dp = request.user.driver_profile
        dp.cancellation_count += 1
        
        if dp.cancellation_count >= 3:
            request.user.is_active = False
            request.user.save(update_fields=['is_active'])
            dp.save(update_fields=['cancellation_count'])
            messages.error(request, "Your account has been suspended due to excessive ride cancellations.")
            logout(request)
            return redirect('login')
            
        dp.save(update_fields=['cancellation_count'])
    except Driver.DoesNotExist:
        pass

    messages.info(request, "Ride rejected.")
    return redirect('driver_dashboard')


@login_required
def driver_ride_details(request, ride_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id)
    return render(request, 'driver/ride_details.html', {'ride': ride})


@login_required
def driver_verify_otp(request, ride_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, driver=request.user, status='accepted')

    if request.method == 'POST':
        otp_input = request.POST.get('otp_input')
        if otp_input == str(ride.otp):
            ride.status = 'in_progress'
            ride.started_at = timezone.now()
            ride.otp = None
            ride.save()
            messages.success(request, "Ride started successfully!")
            return redirect('driver_dashboard')
        else:
            messages.error(request, "Invalid OTP")

    return render(request, 'driver/verify_otp.html', {'ride': ride})


@login_required
def driver_live_map(request, ride_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, driver=request.user)
    return render(request, 'driver/route.html', {'ride': ride})


@login_required
def driver_complete_ride(request, ride_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    ride = get_object_or_404(Ride, id=ride_id, driver=request.user)

    # Fixed: was checking "started" which is not a valid status; correct status is "in_progress"
    if ride.status != 'in_progress':
        messages.error(request, "Ride must be in progress to complete.")
        return redirect('driver_dashboard')

    # Calculate actual fare
    pricing = Pricing.objects.filter(vehicle_type=ride.vehicle_type).first()
    if not pricing:
        pricing = Pricing.objects.first()

    if pricing and ride.distance_km:
        base = float(pricing.base_fare)
        km_rate = float(pricing.per_km_rate)
        ride.actual_fare = Decimal(str(round(base + float(ride.distance_km) * km_rate, 2)))

    ride.status = 'completed'
    ride.completed_at = timezone.now()
    ride.save()

    # Create Earning record
    if ride.actual_fare:
        Earning.objects.get_or_create(
            ride=ride,
            defaults={
                'driver': request.user,
                'amount': ride.actual_fare
            }
        )

    # Update subscription ride count
    subscription = getattr(request.user, 'subscription', None)
    if subscription:
        subscription.increment_rides()

    # Free up driver profile availability
    try:
        driver_profile = request.user.driver_profile
        driver_profile.is_available = True
        driver_profile.status = 'available'
        driver_profile.save()
    except Driver.DoesNotExist:
        pass

    messages.success(request, "Ride completed successfully ✅")
    return redirect('driver_dashboard')


# --- Admin Add-On Views ---

@login_required
def admin_manage_addons(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    addons = AddOnPlan.objects.all()
    return render(request, 'admin/manage_addons.html', {'addons': addons})

@login_required
def admin_add_addon(request):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    if request.method == 'POST':
        AddOnPlan.objects.create(
            name=request.POST.get('name'),
            price=request.POST.get('price'),
            ride_limit=0, # No longer using daily ride limit
            km_limit=request.POST.get('km_limit', 0),
            validity_days=request.POST.get('validity_days', 1),
            description=request.POST.get('description')
        )
        messages.success(request, "Add-on plan added successfully.")
        return redirect('admin_manage_addons')
    return render(request, 'admin/add_addon.html')

@login_required
def admin_edit_addon(request, addon_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    addon = get_object_or_404(AddOnPlan, id=addon_id)
    if request.method == 'POST':
        addon.name = request.POST.get('name')
        addon.price = request.POST.get('price')
        addon.ride_limit = 0 # No longer using daily ride limit
        addon.km_limit = request.POST.get('km_limit', 0)
        addon.validity_days = request.POST.get('validity_days', 1)
        addon.description = request.POST.get('description')
        addon.is_active = 'is_active' in request.POST
        addon.save()
        messages.success(request, "Add-on plan updated.")
        return redirect('admin_manage_addons')
    return render(request, 'admin/edit_addon.html', {'addon': addon})

@login_required
def admin_delete_addon(request, addon_id):
    if not (request.user.is_admin or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")
    addon = get_object_or_404(AddOnPlan, id=addon_id)
    addon.delete()
    messages.info(request, "Add-on plan deleted.")
    return redirect('admin_manage_addons')

# --- Driver Add-On Views ---

@login_required
def driver_available_addons(request):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")
    addons = AddOnPlan.objects.filter(is_active=True)
    return render(request, 'driver/available_addons.html', {'addons': addons})

@login_required
def driver_purchase_addon(request, addon_id):
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")
    
    addon = get_object_or_404(AddOnPlan, id=addon_id, is_active=True)
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    
    amount_in_paise = int(float(addon.price) * 100)
    order_data = {
        'amount': amount_in_paise,
        'currency': 'INR',
        'payment_capture': '1'
    }
    
    try:
        order = client.order.create(data=order_data)
        razorpay_order_id = order['id']
        
        # Create payment record (pending)
        AddOnPayment.objects.create(
            driver=request.user,
            plan=addon,
            amount=addon.price,
            razorpay_order_id=razorpay_order_id,
            status='pending'
        )
        
        return render(request, 'driver/addon_payment.html', {
            'addon': addon,
            'razorpay_order_id': razorpay_order_id,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'amount': addon.price,
            'amount_in_paise': amount_in_paise,
            'user_name': request.user.get_full_name() or request.user.username,
            'user_email': request.user.email,
            'user_phone': getattr(request.user, 'phone_number', ''),
            'user': request.user
        })
    except Exception as e:
        messages.error(request, f"Error initializing payment: {str(e)}")
        return redirect('driver_available_addons')

@login_required
def driver_addon_payment_handle(request):
    if request.method == 'POST':
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')
        upi_id = request.POST.get('upi_id')
        
        # Update driver's UPI ID if provided
        if upi_id:
            try:
                dp = request.user.driver_profile
                dp.upi_id = upi_id
                dp.save(update_fields=['upi_id'])
            except Driver.DoesNotExist:
                pass
        
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        
        try:
            client.utility.verify_payment_signature(params_dict)
            payment = AddOnPayment.objects.get(razorpay_order_id=razorpay_order_id)
            payment.status = 'completed'
            payment.razorpay_payment_id = razorpay_payment_id
            payment.razorpay_signature = razorpay_signature
            payment.save()
            
            # Grant the addon to the driver
            DriverAddOn.objects.create(
                driver=request.user,
                plan=payment.plan,
                expiry_date=timezone.now() + timedelta(days=payment.plan.validity_days),
                rides_limit=payment.plan.ride_limit,
                km_limit=payment.plan.km_limit,
                is_active=True
            )
            
            messages.success(request, f"Add-on '{payment.plan.name}' purchased successfully! You can now accept more rides.")
            return redirect('driver_dashboard')
            
        except Exception as e:
            messages.error(request, f"Payment verification failed: {str(e)}")
            return redirect('driver_available_addons')
            
    return redirect('driver_available_addons')


# ---------------------------------------------------------------------------
# Driver Matching Helper
# ---------------------------------------------------------------------------

def match_driver(ride):
    """
    Find the nearest available Driver for a given Ride and assign it.
    Returns the assigned Driver instance or None.
    """
    user_lat = ride.pickup_lat
    user_lng = ride.pickup_lng

    # Use the unified Driver model (has lat/lng/availability)
    drivers = Driver.objects.filter(is_available=True)

    nearby_drivers = []
    for driver_profile in drivers:
        distance = haversine(
            user_lat, user_lng,
            driver_profile.latitude, driver_profile.longitude,
        )
        if distance <= 10:
            nearby_drivers.append((driver_profile, distance))

    if not nearby_drivers:
        return None

    nearby_drivers.sort(key=lambda x: x[1])
    nearest = nearby_drivers[0][0]

    ride.driver = nearest.user   # FK to User
    ride.status = 'accepted'
    ride.accepted_at = timezone.now()
    ride.save()

    nearest.is_available = False
    nearest.status = 'busy'
    nearest.save()

    return nearest


# ===========================================================================
# OTP verification (standalone endpoint)
# ===========================================================================

@login_required
def verify_ride_otp(request, ride_id):
    ride = get_object_or_404(Ride, id=ride_id, driver=request.user)

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        if entered_otp == str(ride.otp):
            ride.status = 'in_progress'
            ride.started_at = timezone.now()
            ride.otp = None
            ride.save()
            messages.success(request, "OTP verified. Ride started!")
        else:
            return render(request, 'driver/error.html', {'message': 'Invalid OTP'})

    return redirect('driver_dashboard')


# ===========================================================================
# API VIEWS
# ===========================================================================

@login_required
def api_ride_status(request, ride_id):
    ride = get_object_or_404(Ride, id=ride_id)
    driver_info = None
    if ride.driver:
        try:
            dp = ride.driver.driver_profile
            driver_info = {
                'name': ride.driver.get_full_name() or ride.driver.username,
                'phone': ride.driver.phone_number,
                'vehicle_type': dp.get_vehicle_type_display(),
                'avg_rating': dp.average_rating,
            }
        except Driver.DoesNotExist:
            driver_info = {'name': ride.driver.username}

    return JsonResponse({
        'status': ride.status,
        'status_display': ride.get_status_display(),
        'otp': ride.otp if ride.status in ['accepted', 'arrived', 'in_progress'] else '',
        'driver': driver_info,
        'matched_distance_km': ride.matched_distance_km,
        'estimated_fare': ride.estimated_fare,
    })


@login_required
def api_check_subscription(request):
    if not request.user.is_driver:
        return JsonResponse({'valid': False, 'message': 'Not a driver'})

    try:
        subscription = DriverSubscription.objects.get(driver=request.user)
        subscription.reset_daily_rides()
        can_accept, message = subscription.can_accept_ride()
        return JsonResponse({
            'valid': can_accept,
            'message': message,
            'rides_left': (
                subscription.plan.daily_ride_limit - subscription.rides_used_today
                if subscription.plan else 0
            ),
        })
    except DriverSubscription.DoesNotExist:
        return JsonResponse({'valid': False, 'message': 'No active subscription'})


# GET /api/nearby-drivers/?lat=&lng=&vehicle_type=&radius=
def api_nearby_drivers(request):
    """
    Public API — returns available drivers near a location.
    Query params: lat, lng, vehicle_type (optional), radius (optional, km)
    """
    try:
        lat = float(request.GET.get('lat', 0))
        lng = float(request.GET.get('lng', 0))
        vehicle_type = request.GET.get('vehicle_type') or None
        radius = float(request.GET.get('radius', SEARCH_RADIUS_KM))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid parameters'}, status=400)

    drivers = get_nearby_drivers(lat, lng, vehicle_type=vehicle_type, radius_km=radius)

    return JsonResponse({
        'count': len(drivers),
        'search_radius_km': radius,
        'drivers': [
            {
                'id': d['user'].id,
                'name': d['user'].get_full_name() or d['user'].username,
                'vehicle_type': d['vehicle_type'],
                'distance_km': d['distance_km'],
                'latitude': d['driver_profile'].latitude,
                'longitude': d['driver_profile'].longitude,
                'avg_rating': d['avg_rating'],
                'status': d['status'],
            }
            for d in drivers
        ],
    })


@login_required
@require_POST
def api_driver_toggle_availability(request):
    """Driver toggles their own online/offline status."""
    if not request.user.is_driver:
        return JsonResponse({'error': 'Not a driver'}, status=403)

    try:
        dp = request.user.driver_profile
    except Driver.DoesNotExist:
        return JsonResponse({'error': 'Driver profile not found'}, status=404)

    if dp.status == 'offline':
        # Check subscription before allowing to go online
        try:
            subscription = request.user.subscription
            can_accept, message = subscription.can_accept_ride()
            if not can_accept:
                return JsonResponse({'error': message}, status=403)
        except DriverSubscription.DoesNotExist:
            return JsonResponse({'error': 'No active subscription. Please subscribe to go online.'}, status=403)
            
        dp.set_available()
        new_status = 'available'
    else:
        dp.set_offline()
        new_status = 'offline'

    return JsonResponse({'status': new_status, 'is_available': dp.is_available})

@login_required
@require_POST
def api_update_driver_location(request):
    """Update driver's lat/lng via AJAX."""
    if not request.user.is_driver:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        data = json.loads(request.body)
        lat = data.get('latitude')
        lng = data.get('longitude')
        
        if lat is None or lng is None:
            return JsonResponse({'error': 'Latitude and longitude are required'}, status=400)
            
        # Use get_or_create to be super safe
        driver_profile, created = Driver.objects.get_or_create(user=request.user)
        driver_profile.latitude = float(lat)
        driver_profile.longitude = float(lng)
        driver_profile.save(update_fields=['latitude', 'longitude'])

        # Proactively check subscription and force offline if expired/exhausted
        if driver_profile.status == 'available':
            try:
                sub = request.user.subscription
                if not sub.can_accept_ride()[0]:
                    driver_profile.set_offline()
            except Exception:
                # No subscription or other error -> force offline if they are trying to be available
                driver_profile.set_offline()
        
        return JsonResponse({'success': True, 'captured': True})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def driver_subscription_history(request):
    """View history of all subscription and add-on payments made by the driver."""
    if not request.user.is_driver:
        return HttpResponseForbidden("Access denied")

    sub_history = SubscriptionPayment.objects.filter(
        driver=request.user, 
        status='completed'
    ).order_by('-created_at')
    
    addon_history = AddOnPayment.objects.filter(
        driver=request.user,
        status='completed'
    ).order_by('-created_at')

    return render(request, 'driver/subscription_history.html', {
        'history': sub_history,
        'addon_history': addon_history
    })
