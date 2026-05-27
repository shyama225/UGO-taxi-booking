import os
import django
from django.core.mail import send_mail
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ugoproject.settings')
django.setup()

def test_email():
    try:
        print(f"Testing email connection for {settings.EMAIL_HOST_USER}...")
        send_mail(
            'Test Email',
            'This is a test email.',
            settings.DEFAULT_FROM_EMAIL,
            [settings.EMAIL_HOST_USER], # Send to self
            fail_silently=False,
        )
        print("SUCCESS: Email sent successfully!")
    except Exception as e:
        print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    test_email()
