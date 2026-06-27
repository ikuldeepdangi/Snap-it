from django.db import models
from django.contrib.auth.models import User

class TelegramProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='telegram_profile')
    telegram_chat_id = models.BigIntegerField(unique=True, db_index=True, help_text="Unique chat ID with the user.", null=True, blank=True)
    telegram_username = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    verification_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TG: @{self.telegram_username or self.telegram_chat_id} <-> {self.user.email}"
