import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rkblkhqcpxyvqrjajmux.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY") or ""
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY") or ""

# Buckets
SUPABASE_RESUME_BUCKET = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")
SUPABASE_GENERATED_BUCKET = os.getenv("SUPABASE_GENERATED_BUCKET", "generated")
SUPABASE_PROFILE_BUCKET = os.getenv("SUPABASE_PROFILE_BUCKET", "profile")
SUPABASE_TEMP_BUCKET = os.getenv("SUPABASE_TEMP_BUCKET", "temp")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp")
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 10485760))

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Server Mode (local or production-live)
SERVER = os.getenv("SERVER", "local").strip().lower()
