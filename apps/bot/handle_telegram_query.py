import os
import json
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from telegram import Bot, Update
from apps.bot.models import TelegramProfile
from asgiref.sync import sync_to_async

@sync_to_async
def link_account(token, chat_id, username):
    from django.db import IntegrityError
    try:
        profile = TelegramProfile.objects.get(verification_token=token)
        profile.telegram_chat_id = chat_id
        profile.telegram_username = username
        profile.is_verified = True
        profile.verification_token = None
        profile.save()
        return profile, None
    except TelegramProfile.DoesNotExist:
        return None, "invalid"
    except IntegrityError:
        return None, "duplicate"

@sync_to_async
def get_or_verify_user(chat_id, username):
    # First, check if already verified by chat_id
    profile = TelegramProfile.objects.filter(telegram_chat_id=chat_id, is_verified=True).first()
    if profile:
        return True, False
        
    # If not verified by chat_id, check if they inputted this username on the web dashboard
    if username:
        # Some users might have typed it with or without @
        clean_username = username.lstrip('@')
        profile = TelegramProfile.objects.filter(telegram_username__iexact=clean_username).first()
        
        if profile and not profile.is_verified:
            # Auto-link the account!
            profile.telegram_chat_id = chat_id
            profile.is_verified = True
            profile.verification_token = None
            profile.save()
            return True, True
            
    return False, False
@csrf_exempt
async def telegram_webhook(request):
    """
    Entry point for all incoming Telegram messages (Webhook).
    This removes the need for a separate long-polling process.
    """
    if request.method == "POST":
        try:
            bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
            data = json.loads(request.body.decode('utf-8'))
            update = Update.de_json(data, bot)

            if update.message:
                chat_id = update.message.chat.id
                text = update.message.text
                
                # Check for Start / Link command
                if text and text.startswith("/start"):
                    parts = text.split()
                    if len(parts) > 1:
                        token = parts[1]
                        profile, err = await link_account(token, chat_id, update.effective_user.username)
                        
                        if profile:
                            display_name = update.effective_user.username or update.effective_user.first_name or "there"
                            greeting = (
                                f"👋 Hello {display_name}! Welcome to SnapIt.\n\n"
                                f"⚡ We've successfully linked your Telegram profile to your web account ({profile.user.email}).\n\n"
                                f"You can now manage your applications and apply to jobs directly through our bot."
                            )
                            await bot.send_message(chat_id=chat_id, text=greeting)
                        elif err == "duplicate":
                            await bot.send_message(
                                chat_id=chat_id, 
                                text="❌ Verification Failed: This Telegram account is already linked to another SnapIt web account! You can only link one web account per Telegram profile."
                            )
                        else:
                            await bot.send_message(chat_id=chat_id, text="❌ Verification Link is invalid or expired.")
                    else:
                        await bot.send_message(chat_id=chat_id, text="Welcome! Please link your account from the SnapIt dashboard.")
                
                # Handle text messages
                elif text:
                    verified, newly_linked = await get_or_verify_user(chat_id, update.effective_user.username)
                    if not verified:
                        await bot.send_message(
                            chat_id=chat_id, 
                            text="Please connect your username with the platform account first. Thank you!"
                        )
                    else:
                        if newly_linked:
                            display_name = update.effective_user.username or update.effective_user.first_name or "there"
                            greeting = (
                                f"👋 Hello {display_name}! Welcome to SnapIt.\n\n"
                                f"⚡ We've successfully linked your Telegram profile to your web account.\n\n"
                                f"You can now manage your applications and apply to jobs directly through our bot."
                            )
                            await bot.send_message(chat_id=chat_id, text=greeting)
                        else:
                            ai_response = await sync_to_async(generate_ai_reply)(text)
                            await bot.send_message(
                                chat_id=chat_id, 
                                text=ai_response
                            )
                
                # Handle images and documents
                elif update.message.photo or update.message.document:
                    verified, _ = await get_or_verify_user(chat_id, update.effective_user.username)
                    if not verified:
                        await bot.send_message(chat_id=chat_id, text="Please connect your username with the platform account first. Thank you!")
                        return HttpResponse("OK")
                    
                    is_pdf = False
                    tg_file_id = None
                    file_name = "upload"
                    
                    if update.message.document and update.message.document.mime_type == 'application/pdf':
                        is_pdf = True
                        tg_file_id = update.message.document.file_id
                        file_name = update.message.document.file_name
                    elif update.message.photo:
                        tg_file_id = update.message.photo[-1].file_id
                        file_name = f"photo_{tg_file_id}.jpg"
                    elif update.message.document and update.message.document.mime_type.startswith('image/'):
                        tg_file_id = update.message.document.file_id
                        file_name = update.message.document.file_name
                    
                    if not tg_file_id:
                        await bot.send_message(chat_id=chat_id, text="🤖 Unsupported format. Please submit a valid image screenshot.")
                        return HttpResponse("OK")
                        
                    # Handle Albums (Debouncing notifications via Cache)
                    media_group_id = update.message.media_group_id
                    from django.core.cache import cache
                    
                    # Process file immediately for robustness (no holding in memory)
                    tg_file = await bot.get_file(tg_file_id)
                    file_bytes = await tg_file.download_as_bytearray()
                    
                    res = await sync_to_async(process_single_media)(chat_id, file_bytes, file_name, is_pdf)
                    
                    if res == "resume_saved":
                        await bot.send_message(chat_id=chat_id, text="📄 Resume saved and processed successfully! You can now send job screenshots.")
                    elif res == "resume_missing":
                        await bot.send_message(chat_id=chat_id, text="⚠️ Resume missing! Please upload your Resume PDF directly to this chat thread to proceed.")
                    elif res.startswith("insufficient_"):
                        bal = res.split("_")[1]
                        if media_group_id:
                            if not cache.get(f"tg_insuf_{media_group_id}"):
                                cache.set(f"tg_insuf_{media_group_id}", True, timeout=60)
                                await bot.send_message(chat_id=chat_id, text=f"❌ Insufficient points! This requires 1 credit, but you have {bal}.")
                        else:
                            await bot.send_message(chat_id=chat_id, text=f"❌ Insufficient points! This requires 1 credit, but you have {bal}.")
                    elif res == "unsupported":
                        await bot.send_message(chat_id=chat_id, text="🤖 Unsupported format. Please submit a valid image screenshot.")
                    elif res.startswith("job_created_"):
                        job_id = res.split("_")[2]
                        if media_group_id:
                            if not cache.get(f"tg_notified_{media_group_id}"):
                                cache.set(f"tg_notified_{media_group_id}", True, timeout=60)
                                await bot.send_message(
                                    chat_id=chat_id, 
                                    text=f"⚡ Batch Ingested! Job reference ID #{job_id} appended to queue pipeline.\nWe are processing your album chronologically..."
                                )
                        else:
                            await bot.send_message(chat_id=chat_id, text=f"⚡ Ingested! Job reference ID #{job_id} appended to queue pipeline.")
                        
        except Exception as e:
            print("Webhook exception:", e)

    return HttpResponse("OK")


def generate_ai_reply(query):
    try:
        from google import genai
        import os
        
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        prompt = (
            "You are an AI assistant for the SnapIt platform. SnapIt helps users automatically apply to jobs. "
            "The user uploads a screenshot of a job description with an HR email, and our system processes it to draft a perfect application email. "
            "A user just sent the following message to our Telegram bot. Reply to them in a short, friendly, and helpful manner suitable for a mobile chat interface. "
            "Always encourage them to upload a screenshot of a job posting to get started.\n\n"
            f"User message: {query}"
        )
        
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt
        )
        return response.text
    except Exception as e:
        print("AI generation error:", e)
        return "Hello! I am the SnapIt Assistant ⚡. Just send me a screenshot of any job posting (with an HR email visible) and I'll automatically draft and send your application!"


def process_single_media(chat_id, file_bytes, file_name, is_pdf):
    from apps.core.models import Resume
    from apps.queue_manager.models import ProcessingJob
    from django.core.files.base import ContentFile
    
    profile = TelegramProfile.objects.select_related('user__credit_wallet', 'user__resume').get(telegram_chat_id=chat_id, is_verified=True)
    user = profile.user
    wallet = user.credit_wallet
    
    if not hasattr(user, 'resume') or not user.resume.resume_storage_path:
        if is_pdf:
            resume, _ = Resume.objects.get_or_create(user=user)
            
            from utils.storage import upload_resume, get_public_url, delete_file
            if resume.resume_storage_path:
                delete_file(resume.resume_storage_path)
                
            wrapped_file = ContentFile(file_bytes, name=file_name)
            storage_path = upload_resume(wrapped_file, user.id)
            public_url = get_public_url(storage_path)
            
            resume.resume_storage_path = storage_path
            resume.resume_public_url = public_url
            resume.original_filename = file_name
            resume.save()
            
            from apps.core.engine import extract_text_from_pdf
            extract_text_from_pdf(resume)
            return "resume_saved"
        else:
            return "resume_missing"
            
    if is_pdf:
        return "unsupported"
        
    if wallet.balance < 1:
        return f"insufficient_{wallet.balance}"
        
    job = ProcessingJob.objects.create(user=user, status='PROCESSING')
    
    from utils.storage import upload_temp_file, get_public_url
    wrapped_file = ContentFile(file_bytes, name=file_name)
    storage_path = upload_temp_file(wrapped_file, user.id)
    public_url = get_public_url(storage_path)
    
    job.screenshot_storage_path = storage_path
    job.screenshot_public_url = public_url
    job.status = 'PENDING'
    job.save()
    return f"job_created_{job.id}"

def process_album_batch(chat_id, file_ids):
    import requests
    import os
    from apps.queue_manager.models import ProcessingJob
    from django.core.files.base import ContentFile
    
    profile = TelegramProfile.objects.select_related('user__credit_wallet', 'user__resume').get(telegram_chat_id=chat_id, is_verified=True)
    user = profile.user
    wallet = user.credit_wallet
    
    if not hasattr(user, 'resume') or not user.resume.resume_storage_path:
        return "resume_missing"
        
    if len(file_ids) > wallet.balance:
        return f"insufficient_{wallet.balance}"
        
    queued_ids = []
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    from utils.storage import upload_temp_file, get_public_url
    
    for f_id in file_ids:
        r1 = requests.get(f"https://api.telegram.org/bot{token}/getFile?file_id={f_id}").json()
        file_path = r1['result']['file_path']
        r2 = requests.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        
        job = ProcessingJob.objects.create(user=user, status='PROCESSING')
        wrapped_file = ContentFile(r2.content, name=f"tg_job_bulk_{job.id}.jpg")
        
        storage_path = upload_temp_file(wrapped_file, user.id)
        public_url = get_public_url(storage_path)
        
        job.screenshot_storage_path = storage_path
        job.screenshot_public_url = public_url
        job.status = 'PENDING'
        job.save()
        queued_ids.append(str(job.id))
        
    return ", ".join(queued_ids)