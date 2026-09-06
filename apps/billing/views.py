from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse

import os
import json
from email.message import EmailMessage
import base64
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .models import CreditWallet, TransactionLedger
from .razorpay import RazorpayService


@login_required
def billing_page(request):
    """
    Shows the current points, points history and provides an option to add more points.
    """
    wallet, created = CreditWallet.objects.get_or_create(user=request.user)
    transactions = TransactionLedger.objects.filter(wallet=wallet).order_by('-created_at')[:50]
    
    payment_mode = os.getenv('PAYMENT_MODE', 'razorpay').strip().lower()
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
        'razorpay_key_id': RazorpayService.get_key_id(),
        'is_razorpay_configured': RazorpayService.is_configured(),
        'PAYMENT_MODE': payment_mode,
        'UPI_ID': os.getenv('UPI_ID', 'snapit@upi').strip(),
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

    if not RazorpayService.is_configured():
        return JsonResponse({'error': 'Payment gateway not configured'}, status=500)

    try:
        data = json.loads(request.body)
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid amount payload'}, status=400)

    if amount < 1:
        return JsonResponse({'error': 'Minimum amount is ₹1'}, status=400)

    try:
        order_data = RazorpayService.create_order(
            amount_in_rupees=amount,
            user_id=request.user.id
        )
        return JsonResponse(order_data)
    except ValueError as ve:
        return JsonResponse({'error': str(ve)}, status=400)
    except Exception as e:
        error_msg = str(e)
        if "Authentication failed" in error_msg:
            return JsonResponse({
                'error': 'Razorpay authentication failed. Please check RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in your .env file.'
            }, status=400)
        return JsonResponse({'error': error_msg}, status=400)


@login_required
@transaction.atomic
def verify_razorpay_payment(request):
    """
    Verify the payment signature from Razorpay and credit the wallet.
    Logs successful and failed transactions in TransactionLedger.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    if not RazorpayService.is_configured():
        return JsonResponse({'error': 'Payment gateway not configured'}, status=500)

    try:
        data = json.loads(request.body)
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')
        amount = int(data.get('amount', 0))

        if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
            return JsonResponse({'error': 'Missing payment verification parameters'}, status=400)

        wallet, _ = CreditWallet.objects.select_for_update().get_or_create(user=request.user)

        # Verify signature
        is_valid = RazorpayService.verify_payment_signature(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature
        )

        if not is_valid:
            # Record failed transaction in DB
            TransactionLedger.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type='RAZORPAY',
                status='FAILED',
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                failure_reason='Signature verification failed',
                description=f"Failed Payment ({razorpay_payment_id}): Invalid signature"
            )
            return JsonResponse({'error': 'Invalid payment signature. Verification failed.'}, status=400)

        # Idempotency check: Ensure transaction isn't already processed
        if TransactionLedger.objects.filter(razorpay_payment_id=razorpay_payment_id, status='SUCCESS').exists() or \
           TransactionLedger.objects.filter(description__icontains=razorpay_payment_id, status='SUCCESS').exists():
            return JsonResponse({
                'status': 'ok',
                'message': 'Payment already processed',
                'amount': amount,
                'redirect_url': reverse('billing_page') + f"?payment_success=1&amount={amount}"
            })

        # Update wallet balance
        wallet.balance += amount
        wallet.save()

        # Record successful transaction in DB
        TransactionLedger.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='RAZORPAY',
            status='SUCCESS',
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            description=f"Razorpay Online Refill: {razorpay_payment_id}"
        )

        messages.success(request, f"🎉 Payment Received! {amount} Credits have been added to your wallet. Enjoy applying!")
        return JsonResponse({
            'status': 'ok',
            'amount': amount,
            'new_balance': wallet.balance,
            'redirect_url': reverse('billing_page') + f"?payment_success=1&amount={amount}"
        })

    except Exception as e:
        return JsonResponse({'error': f'Server error during payment verification: {str(e)}'}, status=500)


@login_required
def record_failed_payment(request):
    """
    Records a failed or cancelled Razorpay payment attempt into TransactionLedger for full audit tracking.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)
        amount = int(data.get('amount', 0))
        razorpay_order_id = data.get('razorpay_order_id', '')
        razorpay_payment_id = data.get('razorpay_payment_id', '')
        error_description = data.get('error_description', 'Payment failed or cancelled by user')

        wallet, _ = CreditWallet.objects.get_or_create(user=request.user)

        # Check if already logged to prevent duplicates
        if razorpay_payment_id and TransactionLedger.objects.filter(razorpay_payment_id=razorpay_payment_id).exists():
            return JsonResponse({'status': 'ok', 'message': 'Already recorded'})

        TransactionLedger.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='RAZORPAY',
            status='FAILED',
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            failure_reason=error_description,
            description=f"Razorpay Refill Failed: {error_description}"
        )
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


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

