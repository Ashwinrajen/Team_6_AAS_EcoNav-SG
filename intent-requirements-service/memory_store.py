# intent-requirements-service/memory_store.py  (REPLACE FULL FILE)

import os, json
from datetime import datetime
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION")
USE_S3 = os.environ.get("USE_S3", "false").lower() == "true"

# S3 settings
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_BASE_PREFIX = os.getenv("S3_BASE_PREFIX")
S3_MEMORY_PREFIX = os.getenv("S3_MEMORY_PREFIX")
S3_ENDPOINT = os.getenv("AWS_S3_ENDPOINT")  # LocalStack optional
S3_ENDPOINT = S3_ENDPOINT if S3_ENDPOINT and S3_ENDPOINT.strip() else None

# Fallback in-memory (for local/dev when USE_S3=false)
_memory_store: Dict[str, Dict[str, Any]] = {}

_s3 = boto3.client("s3", region_name=AWS_REGION, endpoint_url=S3_ENDPOINT)

def _join_prefix(*parts: str) -> str:
    pieces = [p.strip().strip("/") for p in parts if p and p.strip().strip("/")]
    if not pieces:
        return ""
    return "/".join(pieces) + "/"

def _effective_prefix(service_prefix: str) -> str:
    return _join_prefix(S3_BASE_PREFIX, service_prefix)

def _memory_key(session_id: str) -> str:
    base = _effective_prefix(S3_MEMORY_PREFIX)  # e.g., dev/memory/
    return f"{base}{session_id}.json"

def _now_iso() -> str:
    return datetime.now().isoformat()

def get_memory(session_id: str, target_template: dict = None) -> Dict[str, Any]:
    if not USE_S3:
        return _memory_store.get(session_id, {
            "session_id": session_id,
            "conversation_history": [],
            "requirements": target_template or {},
            "phase": "initial",
            "last_updated": _now_iso()
        })

    key = _memory_key(session_id)
    try:
        obj = _s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        body = obj["Body"].read().decode("utf-8")
        return json.loads(body)
    except _s3.exceptions.NoSuchKey:
        # Return default if not found
        return {
            "session_id": session_id,
            "conversation_history": [],
            "requirements": target_template or {},
            "phase": "initial",
            "last_updated": _now_iso()
        }
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return {
                "session_id": session_id,
                "conversation_history": [],
                "requirements": target_template or {},
                "phase": "initial",
                "last_updated": _now_iso()
            }
        print(f"S3 get_memory error: {e}")
        return {
            "session_id": session_id,
            "conversation_history": [],
            "requirements": target_template or {},
            "phase": "initial",
            "last_updated": _now_iso()
        }

def put_memory(session_id: str, conversation_history: list, requirements: dict, phase: str):
    if not USE_S3:
        print(f"📝 Local storage mode - skipping S3 for session {session_id}")
        _memory_store[session_id] = {  # Store in memory instead
            "session_id": session_id,
            "conversation_history": conversation_history[-int(os.getenv("MAX_HISTORY", "10")):],
            "requirements": requirements,
            "phase": phase,
            "last_updated": _now_iso()
        }
        return
    
    item = {
        "session_id": session_id,
        "conversation_history": conversation_history[-int(os.getenv("MAX_HISTORY", "10")):],
        "requirements": requirements,
        "phase": phase,
        "last_updated": _now_iso()
    }
    
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not set")
    
    key = _memory_key(session_id)
    body = json.dumps(item, ensure_ascii=False).encode("utf-8")
    _s3.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=key,
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="AES256"
    )