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

