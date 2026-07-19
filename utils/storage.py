import os
import uuid
import tempfile
import logging
from supabase import create_client, Client
import config

logger = logging.getLogger(__name__)

# Initialize Supabase client ONLY if in production-live mode
supabase: Client = None
supabase_key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_KEY

if config.SERVER == 'production-live':
    if config.SUPABASE_URL and supabase_key:
        try:
            supabase = create_client(config.SUPABASE_URL, supabase_key)
            logger.info("Supabase client initialized successfully in production-live mode.")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
    else:
        logger.warning("Supabase URL or Key is missing. Storage client will not be available.")
else:
    logger.info("Local server mode enabled. Bypassing Supabase client initialization.")

def ensure_bucket_exists(bucket_name: str) -> bool:
    """
    Ensure the specified storage bucket exists in Supabase.
    If it doesn't exist, create it as a public bucket.
    """
    if not supabase:
        logger.error("Supabase client is not initialized.")
        return False
    try:
        buckets = supabase.storage.list_buckets()
        bucket_ids = [b.id for b in buckets]
        if bucket_name not in bucket_ids:
            logger.info(f"Bucket '{bucket_name}' not found. Creating it...")
            supabase.storage.create_bucket(bucket_name, options={"public": True})
            logger.info(f"Bucket '{bucket_name}' created successfully.")
        return True
    except Exception as e:
        logger.error(f"Error checking/creating bucket '{bucket_name}': {e}")
        return False

# Initialize the required buckets (Supabase buckets in production, local folders in local mode)
if config.SERVER == 'production-live' and supabase:
    for bucket in [config.SUPABASE_RESUME_BUCKET, config.SUPABASE_GENERATED_BUCKET, config.SUPABASE_PROFILE_BUCKET, config.SUPABASE_TEMP_BUCKET]:
        ensure_bucket_exists(bucket)
elif config.SERVER == 'local':
    for bucket in [config.SUPABASE_RESUME_BUCKET, config.SUPABASE_GENERATED_BUCKET, config.SUPABASE_PROFILE_BUCKET, config.SUPABASE_TEMP_BUCKET]:
        local_dir = os.path.join('media', bucket)
        os.makedirs(local_dir, exist_ok=True)
        logger.info(f"Created local media directory: {local_dir}")

def get_file_extension(filename: str) -> str:
    """Extract and return lowercased file extension with a dot, e.g. '.pdf'"""
    _, ext = os.path.splitext(filename)
    return ext.lower()

def upload_file_to_bucket(file, bucket_name: str, folder_path: str = "") -> str:
    """
    Core function to upload a file-like object to a Supabase bucket (production)
    or save it to local media folder (local).
    Generates a unique UUID-based filename.
    Returns the relative storage path: 'bucket_name/folder_path/unique_filename'
    """
    # Read file content
    if hasattr(file, 'read'):
        file_data = file.read()
        filename = getattr(file, 'name', 'file')
    else:
        # If it's bytes or path
        file_data = file
        filename = 'file'

    ext = get_file_extension(filename)
    unique_name = f"{uuid.uuid4()}{ext}"
    
    # Construct path inside the bucket
    storage_path_in_bucket = f"{folder_path}/{unique_name}" if folder_path else unique_name
    full_path = f"{bucket_name}/{storage_path_in_bucket}"
    
    if config.SERVER == 'production-live':
        if not supabase:
            raise RuntimeError("Supabase client is not initialized.")
        logger.info(f"Uploading file {filename} to bucket '{bucket_name}' at path '{storage_path_in_bucket}'...")
        response = supabase.storage.from_(bucket_name).upload(
            path=storage_path_in_bucket,
            file=file_data,
            file_options={"content-type": getattr(file, 'content_type', 'application/octet-stream')}
        )
        logger.info(f"Upload successful. Storage path: {full_path}")
        return full_path
    else:
        # Local Mode: Save to local media folder
        local_dest_dir = os.path.join('media', bucket_name, folder_path)
        os.makedirs(local_dest_dir, exist_ok=True)
        local_dest_path = os.path.join(local_dest_dir, unique_name)
        
        logger.info(f"Local storage mode: saving file {filename} to {local_dest_path}...")
        with open(local_dest_path, 'wb') as dest_file:
            dest_file.write(file_data)
        logger.info(f"Local save successful. Storage path: {full_path}")
        return full_path

def upload_resume(file, user_id) -> str:
    """Uploads user resume to the resumes bucket."""
    return upload_file_to_bucket(file, config.SUPABASE_RESUME_BUCKET, folder_path=str(user_id))

def upload_generated_file(file) -> str:
    """Uploads a generated file (e.g. PDFs, images, reports) to generated bucket."""
    return upload_file_to_bucket(file, config.SUPABASE_GENERATED_BUCKET)

def upload_profile_image(file, user_id) -> str:
    """Uploads profile image to profile bucket."""
    return upload_file_to_bucket(file, config.SUPABASE_PROFILE_BUCKET, folder_path=str(user_id))

def upload_temp_file(file, user_id=None) -> str:
    """Uploads a temporary file (like screenshots) to temp bucket."""
    folder = str(user_id) if user_id else ""
    return upload_file_to_bucket(file, config.SUPABASE_TEMP_BUCKET, folder_path=folder)

def parse_storage_path(path: str):
    """Parses a full storage path 'bucket/file_path' into (bucket, file_path)"""
    if '/' not in path:
        raise ValueError(f"Invalid storage path format: {path}")
    bucket_name, file_path = path.split('/', 1)
    return bucket_name, file_path

def delete_file(path: str) -> bool:
    """Deletes a file from Supabase Storage (production) or local media (local)."""
    if config.SERVER == 'production-live':
        if not supabase:
            logger.error("Supabase client is not initialized.")
            return False
        
        try:
            bucket_name, file_path = parse_storage_path(path)
            logger.info(f"Deleting file from bucket '{bucket_name}' at path '{file_path}'...")
            supabase.storage.from_(bucket_name).remove([file_path])
            logger.info("File deleted successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file '{path}' from Supabase Storage: {e}")
            return False
    else:
        # Local Mode: delete local file
        try:
            local_path = os.path.join('media', path)
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"Deleted local file: {local_path}")
                return True
            else:
                logger.warning(f"Local file not found for deletion: {local_path}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete local file '{path}': {e}")
            return False

def get_public_url(path: str) -> str:
    """Gets the public URL of a file from Supabase Storage (production) or local media (local)."""
    if config.SERVER == 'production-live':
        if not supabase:
            logger.error("Supabase client is not initialized.")
            return ""
        
        try:
            bucket_name, file_path = parse_storage_path(path)
            url_res = supabase.storage.from_(bucket_name).get_public_url(file_path)
            return url_res
        except Exception as e:
            logger.error(f"Failed to get public URL for '{path}': {e}")
            return ""
    else:
        # Local Mode: return local media URL path
        return f"/media/{path}"

def download_to_temp(path: str) -> str:
    """
    Downloads a file from Supabase Storage (production) or local media (local)
    and saves it to a local temporary file.
    Returns the absolute path to the local temporary file.
    Note: Caller is responsible for deleting this file after use!
    """
    if config.SERVER == 'production-live':
        if not supabase:
            raise RuntimeError("Supabase client is not initialized.")
        
        try:
            bucket_name, file_path = parse_storage_path(path)
            logger.info(f"Downloading file from bucket '{bucket_name}' at path '{file_path}'...")
            
            file_bytes = supabase.storage.from_(bucket_name).download(file_path)
            
            # Create a temporary file
            ext = get_file_extension(file_path)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=config.UPLOAD_FOLDER if os.path.exists(config.UPLOAD_FOLDER) else None)
            temp_file.write(file_bytes)
            temp_file.close()
            
            logger.info(f"Downloaded and saved to temporary file: {temp_file.name}")
            return temp_file.name
        except Exception as e:
            logger.error(f"Failed to download file '{path}' from Supabase Storage: {e}")
            raise e
    else:
        # Local Mode: copy local file to temp directory
        try:
            local_src = os.path.join('media', path)
            if not os.path.exists(local_src):
                raise FileNotFoundError(f"Local file not found at {local_src}")
                
            ext = get_file_extension(path)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=config.UPLOAD_FOLDER if os.path.exists(config.UPLOAD_FOLDER) else None)
            
            logger.info(f"Local storage mode: copying {local_src} to temp file {temp_file.name}...")
            with open(local_src, 'rb') as src_f:
                temp_file.write(src_f.read())
            temp_file.close()
            
            return temp_file.name
        except Exception as e:
            logger.error(f"Failed to copy local file '{path}' to temp: {e}")
            raise e
