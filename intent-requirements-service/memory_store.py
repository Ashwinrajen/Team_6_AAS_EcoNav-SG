# intent-requirements-service/memory_store.py  (FIXED VERSION)

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
S3_ENDPOINT = os.getenv("AWS_S3_ENDPOINT")  
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
    """
    Get memory data with S3 fallback support.
    
    Flow:
    1. Check in-memory cache first (fast path)
    2. If not in cache AND S3 is enabled, try reading from S3
    3. If found in S3, populate cache and return it
    4. Otherwise, return default template
    """
    # Fast path: check in-memory cache
    if session_id in _memory_store:
        print(f"✅ Memory cache hit for session: {session_id}")
        return _memory_store[session_id]
    
    # Slow path: try loading from S3 if enabled
    if USE_S3 and S3_BUCKET_NAME:
        key = _memory_key(session_id)
        try:
            print(f"🔍 Memory cache miss, attempting S3 read: {key}")
            obj = _s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
            body = obj["Body"].read().decode("utf-8")
            data = json.loads(body)
            
            # Populate cache for future requests
            _memory_store[session_id] = data
            print(f"✅ Session loaded from S3 and cached: {session_id}")
            return data
            
        except _s3.exceptions.NoSuchKey:
            print(f"ℹ️  No S3 data found for session: {session_id}, using default template")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                print(f"ℹ️  No S3 data found for session: {session_id}, using default template")
            else:
                print(f"⚠️  S3 get_memory error: {e}")
        except Exception as e:
            print(f"⚠️  Unexpected error loading from S3: {e}")
    
    # Return default template if not found anywhere
    default_data = {
        "session_id": session_id,
        "conversation_history": [],
        "requirements": target_template or {},
        "phase": "initial",
        "last_updated": _now_iso()
    }
    print(f"📝 Returning default template for session: {session_id}")
    return default_data

def put_memory(session_id: str, conversation_history: list, requirements: dict, phase: str):
    """Store memory data in both memory AND S3"""
    data = {
        "session_id": session_id,
        "conversation_history": conversation_history[-int(os.getenv("MAX_HISTORY", "10")):],
        "requirements": requirements,
        "phase": phase,
        "last_updated": _now_iso()
    }
    
    # Store in memory cache
    _memory_store[session_id] = data
    print(f"✅ Session cached in memory: {session_id}")
    
    # ALSO store in S3
    if USE_S3 and S3_BUCKET_NAME:
        key = _memory_key(session_id)
        try:
            _s3.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=key,
                Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                ContentType="application/json",
                ServerSideEncryption="AES256"
            )
            print(f"✅ Session persisted to S3: {key}")
        except Exception as e:
            print(f"❌ Error storing memory to S3: {e}")

def delete_memory(session_id: str):
    """Delete memory from both in-memory cache and S3"""
    # Remove from cache
    if session_id in _memory_store:
        del _memory_store[session_id]
        print(f"✅ Session removed from memory cache: {session_id}")
    
    # Remove from S3
    if USE_S3 and S3_BUCKET_NAME:
        key = _memory_key(session_id)
        try:
            _s3.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
            print(f"✅ Session removed from S3: {key}")
        except Exception as e:
            print(f"⚠️  Error deleting memory from S3: {e}")