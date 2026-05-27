from django.urls import path
from . import views


urlpatterns = [
    # Public views
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),

    # -----------------------------------------------------------------------
    # Admin dashboard
    # -----------------------------------------------------------------------
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/users/', views.admin_manage_users, name='admin_manage_users'),
    path('admin/users/delete/<int:user_id>/', views.admin_delete_user, name='admin_delete_user'),
    path('admin/users/toggle-status/<int:user_id>/', views.admin_toggle_user_status, name='admin_toggle_user_status'),
    path('admin/drivers/', views.admin_manage_drivers, name='admin_manage_drivers'),
    path('admin/drivers/register/', views.admin_register_driver, name='admin_register_driver'),
    path('admin/drivers/view/<int:driver_id>/', views.admin_view_driver, name='admin_view_driver'),
    path('admin/drivers/approve/<int:driver_id>/', views.admin_approve_driver, name='admin_approve_driver'),
    path('admin/drivers/send-approval-email/<int:driver_id>/', views.admin_send_approval_email, name='admin_send_approval_email'),
    path('admin/drivers/reject/<int:driver_id>/', views.admin_reject_driver, name='admin_reject_driver'),
    path('admin/drivers/send-rejection-email/<int:driver_id>/', views.admin_send_rejection_email, name='admin_send_rejection_email'),
    path('admin/drivers/delete/<int:driver_id>/', views.admin_delete_driver, name='admin_delete_driver'),
    path('admin/drivers/toggle-status/<int:driver_id>/', views.admin_toggle_driver_status, name='admin_toggle_driver_status'),
    path('admin/rides/', views.admin_manage_rides, name='admin_manage_rides'),
    path('admin/pricing/', views.admin_manage_pricing, name='admin_manage_pricing'),
    path('admin/pricing/add/', views.admin_add_pricing, name='admin_add_pricing'),
    path('admin/pricing/edit/<int:pricing_id>/', views.admin_edit_pricing, name='admin_edit_pricing'),
    path('admin/pricing/delete/<int:pricing_id>/', views.admin_delete_pricing, name='admin_delete_pricing'),
    path('admin/subscriptions/', views.admin_manage_subscriptions, name='admin_manage_subscriptions'),
    path('admin/subscriptions/add/', views.admin_add_subscription, name='admin_add_subscription'),
    path('admin/subscriptions/edit/<int:plan_id>/', views.admin_edit_subscription, name='admin_edit_subscription'),
    path('admin/subscriptions/delete/<int:plan_id>/', views.admin_delete_subscription, name='admin_delete_subscription'),
    path('admin/addons/', views.admin_manage_addons, name='admin_manage_addons'),
    path('admin/addons/add/', views.admin_add_addon, name='admin_add_addon'),
    path('admin/addons/edit/<int:addon_id>/', views.admin_edit_addon, name='admin_edit_addon'),
    path('admin/addons/delete/<int:addon_id>/', views.admin_delete_addon, name='admin_delete_addon'),
    path('admin/taxis/', views.admin_manage_taxis, name='admin_manage_taxis'),
    path('admin/taxis/add/', views.admin_add_taxi, name='admin_add_taxi'),
    path('admin/taxis/delete/<int:taxi_id>/', views.admin_delete_taxi, name='admin_delete_taxi'),
    path('admin/ride-requests/', views.admin_view_ride_requests, name='admin_view_ride_requests'),
    path('admin/profile/', views.admin_profile, name='admin_profile'),
    path('admin/profile/update/', views.admin_update_profile, name='admin_update_profile'),
    path('admin/payments/', views.admin_manage_payments, name='admin_manage_payments'),
    path('admin/ratings/', views.admin_manage_ratings, name='admin_manage_ratings'),
    path('admin/addon-payments/', views.admin_manage_addon_payments, name='admin_manage_addon_payments'),
    path('admin/driver-addons/', views.admin_manage_driver_addons, name='admin_manage_driver_addons'),
    path('admin/driver-subscriptions/', views.admin_manage_driver_subscriptions, name='admin_manage_driver_subscriptions'),
    path('admin/reports/', views.admin_reports, name='admin_reports'),
    path('admin/reports/download/<str:report_type>/', views.admin_download_report, name='admin_download_report'),

    # -----------------------------------------------------------------------
    # User dashboard
    # -----------------------------------------------------------------------
    path('user/', views.user_dashboard, name='user_dashboard'),
    path('user/profile/', views.user_profile, name='user_profile'),
    path('user/profile/update/', views.user_update_profile, name='user_update_profile'),
    path('user/rides/', views.user_ride_history, name='user_ride_history'),
    path('user/ride/request/', views.user_request_ride, name='user_request_ride'),
    path('user/ride/<int:ride_id>/drivers/', views.user_available_drivers, name='user_available_drivers'),
    path('user/ride/<int:ride_id>/select/<int:driver_id>/', views.user_select_driver, name='user_select_driver'),
    path('user/ride/<int:ride_id>/cancel/', views.user_cancel_ride, name='user_cancel_ride'),
    path('user/ride/<int:ride_id>/status/', views.user_ride_status, name='user_ride_status'),
    # Fixed: removed duplicate payment URL; kept single canonical name
    path('user/ride/<int:ride_id>/payment/', views.user_payment, name='user_payment'),
    path('user/ride/<int:ride_id>/rate/', views.user_rate_driver, name='user_rate_driver'),

    # -----------------------------------------------------------------------
    # Driver dashboard
    # -----------------------------------------------------------------------
    path('driver/', views.driver_dashboard, name='driver_dashboard'),
    path('driver/profile/', views.driver_profile, name='driver_profile'),
    path('driver/profile/update/', views.driver_update_profile, name='driver_update_profile'),
    path('driver/ratings/', views.driver_view_ratings, name='driver_view_ratings'),
    path('driver/earnings/', views.driver_earnings, name='driver_earnings'),
    path('driver/subscriptions/', views.driver_subscription_plans, name='driver_subscription_plans'),
    path('driver/subscription/history/', views.driver_subscription_history, name='driver_subscription_history'),
    path('driver/subscribe/<int:plan_id>/', views.driver_subscribe, name='driver_subscribe'),
    path('driver/subscription/cancel/', views.driver_cancel_subscription, name='driver_cancel_subscription'),
    path('driver/add-taxi/', views.driver_add_taxi, name='driver_add_taxi'),
    path('driver/rides/', views.driver_ride_history, name='driver_ride_history'),
    path('driver/ride/accept/<int:ride_id>/', views.driver_accept_ride, name='driver_accept_ride'),
    path('driver/ride/reject/<int:ride_id>/', views.driver_reject_ride, name='driver_reject_ride'),
    path('driver/ride/<int:ride_id>/', views.driver_ride_details, name='driver_ride_details'),
    path('driver/verify-otp/<int:ride_id>/', views.driver_verify_otp, name='driver_verify_otp'),
    path('driver/ride/<int:ride_id>/map/', views.driver_live_map, name='drive_route'),
    path('driver/ride/<int:ride_id>/complete/', views.driver_complete_ride, name='driver_complete_ride'),
    path('driver/addons/available/', views.driver_available_addons, name='driver_available_addons'),
    path('driver/addons/purchase/<int:addon_id>/', views.driver_purchase_addon, name='driver_purchase_addon'),
    path('driver/addons/payment/handle/', views.driver_addon_payment_handle, name='driver_addon_payment_handle'),

    # -----------------------------------------------------------------------
    # API endpoints
    # -----------------------------------------------------------------------
    path('api/ride/<int:ride_id>/status/', views.api_ride_status, name='api_ride_status'),
    path('api/check-subscription/', views.api_check_subscription, name='api_check_subscription'),
    path('api/nearby-drivers/', views.api_nearby_drivers, name='api_nearby_drivers'),
    path('api/driver/toggle-availability/', views.api_driver_toggle_availability, name='api_driver_toggle_availability'),
    path('api/driver/update-location/', views.api_update_driver_location, name='api_update_driver_location'),
]
