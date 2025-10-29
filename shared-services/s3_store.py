# shared-services/s3_store.py  (REPLACE FULL FILE)

import os, json
from datetime import datetime
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import ClientError

AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# Optional “environment namespace”, e.g. "dev", "prod"
S3_BASE_PREFIX = os.getenv("S3_BASE_PREFIX")

# Service-specific prefixes (can be plain names like "sessions/" or already nested)
S3_SESSIONS_PREFIX = os.getenv("S3_SESSIONS_PREFIX")

# FIXED: Handle empty string for S3_ENDPOINT (AWS expects None, not "")
S3_ENDPOINT = os.getenv("AWS_S3_ENDPOINT")  # for LocalStack (optional)
S3_ENDPOINT = S3_ENDPOINT if S3_ENDPOINT and S3_ENDPOINT.strip() else None

_s3 = boto3.client("s3", region_name=AWS_REGION, endpoint_url=S3_ENDPOINT)


def _join_prefix(*parts: str) -> str:
    """Join path parts with single slashes and ensure trailing slash."""
    pieces = [p.strip().strip("/") for p in parts if p and p.strip().strip("/")]
    if not pieces:
        return ""
    return "/".join(pieces) + "/"


def _effective_prefix(service_prefix: str) -> str:
    """
    Compose S3_BASE_PREFIX (e.g., 'dev') with the service prefix (e.g., 'sessions/'),
    producing 'dev/sessions/' if base is set, otherwise just 'sessions/'.
    """
    # keep service_prefix’s structure but normalize
    service_prefix = service_prefix.strip()
    return _join_prefix(S3_BASE_PREFIX, service_prefix)


def _session_key(session_id: str) -> str:
    base = _effective_prefix(S3_SESSIONS_PREFIX)  # e.g., "dev/sessions/"
    return f"{base}{session_id}.json"


def _now_iso() -> str:
    return datetime.now().isoformat()


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    key = _session_key(session_id)
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        body = obj["Body"].read().decode("utf-8")
        return json.loads(body)
    except _s3.exceptions.NoSuchKey:
        return None
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return None
        print(f"S3 get_session error: {e}")
        return None


def put_session(session: Dict[str, Any]) -> None:
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not set")
    key = _session_key(session["session_id"])
    body = json.dumps(session, ensure_ascii=False).encode("utf-8")
    _s3.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=key,
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def update_session(session_id: str, updates: Dict[str, Any]) -> None:
    existing = get_session(session_id) or {"session_id": session_id, "created_at": _now_iso()}
    existing.update(updates or {})
    existing.setdefault("last_active", _now_iso())
    put_session(existing)


def delete_session(session_id: str) -> None:
    key = _session_key(session_id)
    try:
        _s3.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
    except ClientError as e:
        print(f"S3 delete_session error: {e}")
