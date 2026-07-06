from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse

import razorpay
import os
import json
import hmac
import hashlib
from email.message import EmailMessage
import base64
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .models import CreditWallet, TransactionLedger

# Configure Razorpay
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET else None

@login_required
def billing_page(request):
    """
    Shows the current points, points history and provides an option to add more points.
    """
    wallet, created = CreditWallet.objects.get_or_create(user=request.user)
    transactions = TransactionLedger.objects.filter(wallet=wallet).order_by('-created_at')[:50]
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
        'razorpay_key_id': RAZORPAY_KEY_ID,
        'PAYMENT_MODE': os.getenv('PAYMENT_MODE', 'manual').strip().lower(),
        'UPI_ID': os.getenv('UPI_ID', 'your@upi').strip(),
    }
    return render(request, 'billing/ledger.html', context)


@login_required
def create_razorpay_order(request):
    """
    Creates a Razorpay Order to load points into the wallet.
    1 INR = 1 Point.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    if not razorpay_client:
        return JsonResponse({'error': 'Payment gateway not configured'}, status=500)

    try:
        data = json.loads(request.body)
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        amount = 0

    # Minimum amount for Razorpay is usually 1 INR, but let's stick to 1 INR minimum
    # Actually, we can keep the 50 INR minimum for consistency, but Razorpay allows smaller amounts.
    if amount < 1:
        return JsonResponse({'error': 'Minimum amount is ₹1'}, status=400)

    try:
        # Amount is in paise
        order_amount = amount * 100
        order_currency = 'INR'
        
        notes = {
            'user_id': request.user.id,
            'amount': amount,
        }

        razorpay_order = razorpay_client.order.create(dict(
            amount=order_amount,
            currency=order_currency,
            notes=notes,
            payment_capture='1' # Auto capture
        ))

        return JsonResponse({
            'order_id': razorpay_order['id'],
            'amount': order_amount,
            'currency': order_currency,
        })

    except Exception as e:
        print(f"Error creating Razorpay order: {e}")
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
@transaction.atomic
def verify_razorpay_payment(request):
    """
    Verify the payment signature from Razorpay and credit the wallet.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        data = json.loads(request.body)
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')
        amount = int(data.get('amount', 0))

        if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
            return JsonResponse({'error': 'Missing parameters'}, status=400)

        # Verify signature
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
        }
        
        try:
            razorpay_client.utility.verify_payment_signature(params_dict.copy())
            # Or manually:
            # expected_signature = hmac.new(
            #     bytes(RAZORPAY_KEY_SECRET, 'utf-8'),
            #     bytes(f"{razorpay_order_id}|{razorpay_payment_id}", 'utf-8'),
            #     hashlib.sha256
            # ).hexdigest()
            # if expected_signature != razorpay_signature: raise
        except razorpay.errors.SignatureVerificationError:
            return JsonResponse({'error': 'Invalid signature'}, status=400)

        # Ensure transaction isn't already processed
        if TransactionLedger.objects.filter(description__icontains=razorpay_payment_id).exists():
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})

        # Update wallet
        wallet = CreditWallet.objects.select_for_update().get(user=request.user)
        wallet.balance += amount
        wallet.save()

        # Record transaction
        TransactionLedger.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='REFILL',
            description=f"Payment via Razorpay: {razorpay_payment_id}"
        )

        messages.success(request, f"Payment successful! {amount} points have been added to your wallet.")
        return JsonResponse({'status': 'ok', 'redirect_url': reverse('billing_page')})

    except CreditWallet.DoesNotExist:
        return JsonResponse({'error': 'Wallet not found'}, status=404)
    except Exception as e:
        print(f"Payment verification error: {e}")
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
def manual_payment_request(request):
    """
    Handle the manual payment request form submission.
    Sends an email from the user's connected Gmail account to the Admin with the screenshot.
    """
    if request.method != 'POST':
        return redirect('billing_page')
        
    amount = request.POST.get('amount')
    screenshots = request.FILES.getlist('screenshot')
    
    if not amount or not screenshots:
        messages.error(request, "Please provide both amount and at least one screenshot of the transaction.")
        return redirect('billing_page')
        
    admin_email = os.getenv("ADMIN_EMAIL", "kuldeepdangi@gmail.com")
    user = request.user
    
    # Try to send email via user's Gmail API if connected
    try:
        if not hasattr(user, 'profile') or not user.profile.google_access_token or not user.profile.gmail_connected:
            from django.utils.html import format_html
            from django.urls import reverse
            
            admin_email_env = os.getenv('ADMIN_EMAIL', 'support@snapit.com')
            connect_url = reverse('connect_gmail')
            
            msg = format_html(
                'Gmail integration not fully connected. Cannot send automated email. '
                '<strong><a href="{}" class="underline text-indigo-400 hover:text-indigo-300">Click here to Connect Gmail</a></strong> '
                'or contact support manually at {}.',
                connect_url, admin_email_env
            )
            messages.warning(request, msg)
            return redirect('billing_page')
        profile = user.profile
        creds = Credentials(
            token=profile.google_access_token,
            refresh_token=profile.google_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
        )
        
        service = build('gmail', 'v1', credentials=creds)
        
        # Build message using modern EmailMessage API
        message = EmailMessage()
        message['To'] = admin_email
        message['Subject'] = f"Manual Payment Topup Request - {user.email}"
        
        body = f"""Hi SnapIt Accounts Team,

I have recharged my account with ₹{amount}.
Please review the attached transaction screenshot and top up my wallet.

User Email: {user.email}
User ID: {user.id}
Amount Paid: ₹{amount}

Thank you,
{user.get_full_name() or user.email}
"""
        message.set_content(body)
        
        # Add screenshot attachments
        for screenshot in screenshots:
            file_data = screenshot.read()
            file_name = screenshot.name
            
            # Determine mime type based on extension
            import mimetypes
            mime_type, _ = mimetypes.guess_type(file_name)
            if mime_type is None:
                mime_type = 'application/octet-stream'
                
            main_type, sub_type = mime_type.split('/', 1)
            
            message.add_attachment(
                file_data, 
                maintype=main_type, 
                subtype=sub_type, 
                filename=file_name
            )
            
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
        
        messages.success(request, f"Your request for ₹{amount} topup has been submitted to our team for verification.")
        
    except Exception as e:
        error_str = str(e).lower()
        print(f"Failed to send manual payment email: {e}")
        
        if "insufficient authentication scopes" in error_str or "insufficient permission" in error_str:
            if hasattr(user, 'profile'):
                user.profile.gmail_connected = False
                user.profile.save()
                
            from django.utils.html import format_html
            from django.urls import reverse
            admin_email_env = os.getenv('ADMIN_EMAIL', 'support@snapit.com')
            connect_url = reverse('connect_gmail')
            
            msg = format_html(
                'Gmail permissions have expired or are missing. Cannot send automated email. '
                '<strong><a href="{}" class="underline text-indigo-400 hover:text-indigo-300">Click here to Re-Connect Gmail</a></strong> '
                'or contact support manually at {}.',
                connect_url, admin_email_env
            )
            messages.warning(request, msg)
        else:
            messages.error(request, "Failed to submit request due to a server error. Please try again or contact support.")
        
    return redirect('billing_page')

