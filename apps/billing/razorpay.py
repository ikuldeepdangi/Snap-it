





import os
import logging
import razorpay
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class RazorpayService:
    """
    Production-ready service wrapper for Razorpay payment integration.
    Handles order creation, payment verification, and client initialization.
    """

    @staticmethod
    def get_key_id() -> str:
        return os.getenv("RAZORPAY_KEY_ID", "").strip()

    @staticmethod
    def get_key_secret() -> str:
        return os.getenv("RAZORPAY_KEY_SECRET", "").strip()

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.get_key_id() and cls.get_key_secret())

    @classmethod
    def get_client(cls) -> razorpay.Client:
        key_id = cls.get_key_id()
        key_secret = cls.get_key_secret()
        if not key_id or not key_secret:
            raise ValueError("Razorpay API keys (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET) are not configured.")
        return razorpay.Client(auth=(key_id, key_secret))

    @classmethod
    def create_order(
        cls,
        amount_in_rupees: int,
        user_id: Optional[int] = None,
        extra_notes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay Order.
        :param amount_in_rupees: Amount in INR (minimum 1 INR)
        :param user_id: ID of the user placing the order
        :param extra_notes: Additional custom key-value pairs
        :return: Dict containing order_id, amount (in paise), currency
        """
        if amount_in_rupees < 1:
            raise ValueError("Minimum payment amount is ₹1.")

        client = cls.get_client()

        # Razorpay expects amount in paise (1 INR = 100 paise)
        amount_in_paise = amount_in_rupees * 100
        currency = "INR"

        notes = {
            "user_id": str(user_id) if user_id is not None else "",
            "amount_in_rupees": str(amount_in_rupees),
        }
        if extra_notes:
            notes.update({k: str(v) for k, v in extra_notes.items()})

        order_data = {
            "amount": amount_in_paise,
            "currency": currency,
            "notes": notes,
            "payment_capture": 1,  # Auto-capture payment after authorization
        }

        try:
            razorpay_order = client.order.create(data=order_data)
            return {
                "order_id": razorpay_order["id"],
                "amount": razorpay_order["amount"],
                "currency": razorpay_order["currency"],
            }
        except (razorpay.errors.BadRequestError, razorpay.errors.GatewayError, razorpay.errors.ServerError) as e:
            logger.error(f"Razorpay order creation failed: {e}")
            raise RuntimeError(f"Razorpay API Error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during Razorpay order creation: {e}")
            raise RuntimeError(f"Failed to create Razorpay order: {str(e)}")

    @classmethod
    def verify_payment_signature(
        cls, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str
    ) -> bool:
        """
        Verifies the payment signature returned by Razorpay Checkout.
        :return: True if valid signature, False otherwise.
        """
        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            return False

        client = cls.get_client()
        params_dict = {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        }

        try:
            client.utility.verify_payment_signature(params_dict)
            return True
        except razorpay.errors.SignatureVerificationError:
            logger.warning(f"Razorpay signature verification failed for payment {razorpay_payment_id}")
            return False
        except Exception as e:
            logger.error(f"Razorpay signature verification error: {e}")
            return False