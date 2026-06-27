from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import CreditWallet, TransactionLedger

@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        wallet = CreditWallet.objects.create(user=instance, balance=25)
        TransactionLedger.objects.create(
            wallet=wallet,
            amount=25,
            transaction_type='SIGNUP',
            description='Initial signup bonus credits'
        )
