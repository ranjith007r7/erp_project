"""
Real file storage via Cloudflare R2 - checked current pricing before
choosing it over S3: R2's free tier is genuinely permanent (10GB
storage, 1M writes/10M reads per month, zero egress fees forever),
while S3's free tier expires after 12 months. R2 is S3-API-compatible,
so this uses the standard boto3 S3 client pointed at R2's endpoint -
no R2-specific SDK needed.

The bucket is treated as PRIVATE, not a public file host - Documents
can hold real business records (contracts, HR files, invoices), and
this project's own established posture elsewhere (hashed tokens, RBAC
on every route) treats that kind of data as sensitive by default.
Nothing here generates a permanent public URL; every download goes
through generate_presigned_url(), which expires quickly (10 minutes)
and requires the requester to already be authenticated and permitted
to view that specific Document - enforced in the route, not here.
"""
import uuid

import boto3
from fastapi import HTTPException

from app.core.config import settings

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
}


def _r2_configured() -> bool:
    return bool(settings.R2_ACCOUNT_ID and settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY and settings.R2_BUCKET_NAME)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",  # R2 doesn't use AWS regions, but boto3 requires a value
    )


def upload_file(org_id: str, filename: str, content: bytes, content_type: str) -> str:
    """
    Returns the storage KEY (not a URL - the bucket is private, there is
    no public URL). Scoped under org_id/ in the key itself so one org's
    files are never in the same "directory" as another's, even though
    R2 has no real folder concept - this is purely for human-readable
    organization and to make a key-guessing attack need to also know a
    valid org_id, not meaningful security on its own (real access
    control is the org_id check in the download route, not obscurity
    here).
    """
    if not _r2_configured():
        raise HTTPException(503, "File storage is not configured yet. Contact your administrator.")

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"File type '{content_type}' is not allowed.")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(400, f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB upload limit.")

    safe_filename = filename.replace("/", "_").replace("\\", "_")
    key = f"{org_id}/{uuid.uuid4()}_{safe_filename}"

    try:
        _client().put_object(
            Bucket=settings.R2_BUCKET_NAME, Key=key, Body=content, ContentType=content_type,
        )
    except Exception as e:
        # Deliberately broad, not just botocore's ClientError - a
        # misconfigured R2_ACCOUNT_ID can fail before any network call
        # even happens (boto3 raises a plain ValueError on a malformed
        # endpoint URL, caught directly by testing this with a
        # deliberately fake account ID, not anticipated in advance).
        # Real network failures, timeouts, and auth errors are just as
        # unpredictable in shape - every one of them should surface as
        # a clean 502 with a real message, never a raw 500.
        raise HTTPException(502, f"Upload to storage failed: {e}")

    return key


def generate_presigned_url(storage_key: str, expires_in_seconds: int = 600) -> str:
    if not _r2_configured():
        raise HTTPException(503, "File storage is not configured yet. Contact your administrator.")

    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": storage_key},
            ExpiresIn=expires_in_seconds,
        )
    except Exception as e:
        raise HTTPException(502, f"Could not generate a download link: {e}")
