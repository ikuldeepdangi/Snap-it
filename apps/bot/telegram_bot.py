import os
import logging
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from telegram import Update, Bot
from telegram.ext import ContextTypes

from apps.bot.models import TelegramProfile
from apps.queue_manager.models import ProcessingJob
from apps.core.models import Resume

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles secure web handshake deep-linking.
    URL Format: https://t.me/YourSnapItBot?start=verification_token
    """
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    args = context.args

    if not args:
        await update.message.reply_text("👋 Welcome to SnapIt! Link your Telegram profile from your web account dashboard panel.")
        return

    token = args[0]
    try:
        profile = TelegramProfile.objects.get(verification_token=token)
        profile.telegram_chat_id = chat_id
        profile.telegram_username = username
        profile.is_verified = True
        profile.verification_token = None  # Consume single-use token
        profile.save()

        display_name = username or update.effective_user.first_name or "there"
        greeting = (
            f"👋 Hello {display_name}! Welcome to SnapIt.\n\n"
            f"⚡ We've successfully linked your Telegram profile to your web account ({profile.user.email}).\n\n"
            f"You can now manage your applications and apply to jobs directly through our bot. "
            f"Simply send or forward job posting screenshots here! Our background queue will process them instantly."
        )
        
        await update.message.reply_text(greeting)
    except TelegramProfile.DoesNotExist:
        await update.message.reply_text("❌ Verification Link is invalid or expired.")

async def handle_media_ingestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interceptors for documents, single photos, and bulk album frames."""
    chat_id = update.effective_chat.id

    try:
        tg_profile = TelegramProfile.objects.select_related('user__credit_wallet', 'user__resume').get(
            telegram_chat_id=chat_id, is_verified=True
        )
        user = tg_profile.user
        wallet = user.credit_wallet
    except TelegramProfile.DoesNotExist:
        await update.message.reply_text("🔒 Account not linked. Please link your Telegram profile on your settings dashboard.")
        return
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        await update.message.reply_text("❌ Failed to fetch user profile. Please contact support.")
        return

    # Guardrail: Resume Presence Verification
    if not hasattr(user, 'resume') or not user.resume.resume_storage_path:
        if update.message.document and update.message.document.mime_type == 'application/pdf':
            doc = update.message.document
            tg_file = await context.bot.get_file(doc.file_id)
            file_bytes = await tg_file.download_as_bytearray()
            
            import asyncio
            from utils.storage import upload_resume, get_public_url, delete_file
            
            resume, _ = Resume.objects.get_or_create(user=user)
            if resume.resume_storage_path:
                await asyncio.to_thread(delete_file, resume.resume_storage_path)
                
            wrapped_file = ContentFile(file_bytes, name=doc.file_name)
            storage_path = await asyncio.to_thread(upload_resume, wrapped_file, user.id)
            public_url = await asyncio.to_thread(get_public_url, storage_path)
            
            resume.resume_storage_path = storage_path
            resume.resume_public_url = public_url
            resume.original_filename = doc.file_name
            resume.save()
            
            from apps.core.engine import extract_text_from_pdf
            await asyncio.to_thread(extract_text_from_pdf, resume)
            
            await update.message.reply_text("📄 Resume saved and processed successfully! You can now send job screenshots.")
            return
        else:
            await update.message.reply_text("⚠️ Resume missing! Please upload your Resume PDF directly to this chat thread to proceed.")
            return

    # Sort photo layers or documents
    photo_file = None
    if update.message.photo:
        photo_file = update.message.photo[-1]
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        photo_file = update.message.document

    if not photo_file:
        await update.message.reply_text("🤖 Unsupported format. Please submit a valid image screenshot.")
        return

    # Album Group Multi-Image Ingestion Aggregator
    media_group_id = update.message.media_group_id
    if media_group_id:
        if 'albums' not in context.application.user_data:
            context.application.user_data['albums'] = {}
        if media_group_id not in context.application.user_data['albums']:
            context.application.user_data['albums'][media_group_id] = []
            
        context.application.user_data['albums'][media_group_id].append(photo_file.file_id)
        
        # Debouncer execution window (1.2 seconds) to let parallel network packets hit the gateway loop
        context.job_queue.run_once(
            process_media_batch,
            when=1.2,
            data={'chat_id': chat_id, 'media_group_id': media_group_id, 'user_id': user.id},
            name=f"job_{media_group_id}"
        )
        return

    # Single Image Processing Guardrail Path
    if wallet.balance < 1:
        await update.message.reply_text(f"❌ Insufficient points! This requires 1 credit, but you have {wallet.balance}.")
        return

    tg_file = await context.bot.get_file(photo_file.file_id)
    img_bytes = await tg_file.download_as_bytearray()
    
    import asyncio
    from utils.storage import upload_temp_file, get_public_url
    
    job = ProcessingJob.objects.create(user=user, status='PENDING')
    wrapped_file = ContentFile(img_bytes, name=f"tg_job_{job.id}.jpg")
    
    storage_path = await asyncio.to_thread(upload_temp_file, wrapped_file, user.id)
    public_url = await asyncio.to_thread(get_public_url, storage_path)
    
    job.screenshot_storage_path = storage_path
    job.screenshot_public_url = public_url
    job.save()
    
    await update.message.reply_text(f"⚡ Ingested! Job reference ID #{job.id} appended to queue pipeline.")

async def process_media_batch(context: ContextTypes.DEFAULT_TYPE):
    """Callback evaluating total album size requirements vs user credit balance dynamically."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    group_id = job_data['media_group_id']
    user_id = job_data['user_id']
    bot: Bot = context.bot

    file_ids = context.application.user_data['albums'].pop(group_id, [])
    if not file_ids:
        return

    user = User.objects.select_related('credit_wallet').get(id=user_id)
    image_count = len(file_ids)

    # 🛑 MULTI-IMAGE ATOMIC WALLET GUARDRAIL
    if image_count > user.credit_wallet.balance:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Batch Ingestion Blocked! You submitted an album containing {image_count} screenshots, but your "
                 f"wallet currently only holds {user.credit_wallet.balance} credits.\n\nPlease recharge your wallet at "
                 f"dosnapit.com/billing/ or upload fewer images than your current limit ({user.credit_wallet.balance}) to process."
        )
        return

    # Validated: Push cleanly to PENDING database arrays
    import asyncio
    from utils.storage import upload_temp_file, get_public_url

    queued_ids = []
    for f_id in file_ids:
        tg_file = await bot.get_file(f_id)
        img_bytes = await tg_file.download_as_bytearray()
        
        job = ProcessingJob.objects.create(user=user, status='PENDING')
        wrapped_file = ContentFile(img_bytes, name=f"tg_job_bulk_{job.id}.jpg")
        
        storage_path = await asyncio.to_thread(upload_temp_file, wrapped_file, user.id)
        public_url = await asyncio.to_thread(get_public_url, storage_path)
        
        job.screenshot_storage_path = storage_path
        job.screenshot_public_url = public_url
        job.save()
        queued_ids.append(str(job.id))

    await bot.send_message(
        chat_id=chat_id,
        text=f"⚡ Bulk Album Upload Verified! Processed {image_count} new tasks smoothly.\n"
             f"Job Reference IDs: {', '.join(queued_ids)}. Processing chronologically..."
    )
