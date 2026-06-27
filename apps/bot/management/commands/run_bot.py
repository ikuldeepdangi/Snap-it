import os
from django.core.management.base import BaseCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from apps.bot.telegram_bot import start_command, handle_media_ingestion

class Command(BaseCommand):
    help = "Runs the standalone long-polling Telegram ingest loop service."

    def handle(self, *args, **options):
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            self.stderr.write(self.style.ERROR("Missing TELEGRAM_BOT_TOKEN variable."))
            return

        self.stdout.write(self.style.SUCCESS("SnapIt Telegram Module Listening Gateway Online..."))
        application = Application.builder().token(bot_token).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_media_ingestion))

        application.run_polling()
