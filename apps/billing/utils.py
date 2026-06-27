from django.db import transaction
from .models import CreditWallet, TransactionLedger

def deduct_credit_atomically(user_id, amount=1, task_type='EMAIL_DRAFT', description='Credits used for AI task') -> bool:
    """
    Atomically deducts credits from a user's wallet.
    Returns True if successful, False if insufficient funds.
    """
    with transaction.atomic():
        # Lock the wallet row to prevent race conditions during concurrent deduction
        try:
            wallet = CreditWallet.objects.select_for_update().get(user_id=user_id)
        except CreditWallet.DoesNotExist:
            return False

        if wallet.balance >= amount:
            wallet.balance -= amount
            wallet.save()

            TransactionLedger.objects.create(
                wallet=wallet,
                amount=-amount,
                transaction_type=task_type,
                description=description
            )
            return True
            
        return False
