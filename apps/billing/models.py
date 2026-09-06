from django.db import models
from django.contrib.auth.models import User

class CreditWallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='credit_wallet')
    balance = models.IntegerField(default=25)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet: {self.balance}"

class TransactionLedger(models.Model):
    TRANSACTION_TYPES = (
        ('SIGNUP', 'Signup Bonus'),
        ('EMAIL_DRAFT', 'Email Drafting'),
        ('REFILL', 'Manual Refill'),
        ('RAZORPAY', 'Razorpay Online Payment'),
    )

    STATUS_CHOICES = (
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PENDING', 'Pending'),
    )

    wallet = models.ForeignKey(CreditWallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.IntegerField()
    transaction_type = models.CharField(max_length=50, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUCCESS')
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    failure_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.wallet.user.username} - {self.transaction_type} ({self.status}): {self.amount}"

