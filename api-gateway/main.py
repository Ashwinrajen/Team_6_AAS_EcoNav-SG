# api-gateway/main.py

import os
import sys
import json
import boto3
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests
import time 
from botocore.config import Config

PLANNING_BUCKET_NAME = "iss-travel-planner"  # New bucket for planning agent

# ---------------------------------------------------------------------------
# Path setup to import shared module
# ---------------------------------------------------------------------------
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from configs.config import config
from common.service_client import (
    create_session,
    update_session,
    validate_input,
    validate_output,
    classify_intent,
    gather_requirements,
    get_session, 
)

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------
# Only load .env if not running in Lambda/SAM environment
if not os.getenv('AWS_LAMBDA_FUNCTION_NAME') and not os.getenv('AWS_SAM_LOCAL'):
    load_dotenv()
    print("[API-GATEWAY] Loaded .env file")
else:
    print("[API-GATEWAY] Running in Lambda/SAM - using environment variables")

DOWNSTREAM_MODE = os.getenv("DOWNSTREAM_MODE")

# S3 Configuration
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_BASE_PREFIX = os.getenv("S3_BASE_PREFIX")
S3_ENDPOINT = os.getenv("AWS_S3_ENDPOINT")  

# Planning Agent Configuration
PLANNING_AGENT_URL = os.getenv("PLANNING_AGENT_URL")
PLANNING_AGENT_ENABLED = os.getenv("PLANNING_AGENT_ENABLED")

# Retrieval Agent Configuration
RETRIEVAL_AGENT_URL = os.getenv("RETRIEVAL_AGENT_URL")
RETRIEVAL_AGENT_API_KEY = os.getenv("RETRIEVAL_AGENT_API_KEY")

# Planner Agent Lambda function ARN (for synchronous invocation)
PLANNER_AGENT_FUNCTION = os.getenv("PLANNER_AGENT_FUNCTION")

# ---------------------------------------------------------------------------
# S3 Client Setup
# ---------------------------------------------------------------------------
_s3_client = None

def _get_s3_client():
    """Get or create S3 client"""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            endpoint_url=S3_ENDPOINT if S3_ENDPOINT else None
        )
    return _s3_client

# ---------------------------------------------------------------------------
# S3 Helper Functions
# ---------------------------------------------------------------------------
def lambda_synchronous_call(function_name: str, bucket_name: str, key: str,
                            sender_agent: str, session: str) -> Dict[str, Any]:
    """
    Invoke an AWS Lambda function synchronously.
    Returns the decoded JSON payload from the invoked function.
    """
    print(f"📝 Calling the Planning agent....")
    
    # ✅ ADD CONFIG:
    cfg = Config(connect_timeout=60, read_timeout=900)
    client = boto3.client("lambda", region_name=AWS_REGION, config=cfg)
    
    payload = {
        "bucket_name": bucket_name,
        "key": key,
        "sender_agent": sender_agent,
        "session": session
    }
    try:
        response = client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload).encode('utf-8')
        )
        raw_body = response['Payload'].read().decode('utf-8')
        return json.loads(raw_body) if raw_body else {}
    except Exception as e:
        return {"error": str(e)}


def _store_final_json_in_s3(session_id: str, final_json: Dict[str, Any], existing_key: str = None, timestamp: str = None) -> str:
    """Store or update final completion JSON in S3"""
    try:
        # Use provided timestamp or generate new
        if not timestamp:
            timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")

        s3 = _get_s3_client()
        
        # Use existing key if provided, otherwise create new
        if existing_key:
            key = existing_key
            print(f"♻️ Updating existing JSON: {key}")
        else:
            key = f"retrieval_agent/active/{timestamp}_{session_id}.json"
            print(f"📝 Creating new JSON: {key}")
        
        s3.put_object(
            Bucket=PLANNING_BUCKET_NAME,
            Key=key,
            Body=json.dumps(final_json, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256"
        )
        print(f"✅ JSON stored/updated in S3: s3://{PLANNING_BUCKET_NAME}/{key}")
        return key
    except Exception as e:
        print(f"❌ Error storing final JSON in S3: {e}")
        raise

def _get_session_from_s3(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve session data from S3 to get conversation history"""
    try:
        s3 = _get_s3_client()
        key = f"{S3_BASE_PREFIX}/requirements/{session_id}.json" if S3_BASE_PREFIX else f"requirements/{session_id}.json"
        obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        body = obj["Body"].read().decode("utf-8")
        return json.loads(body)
    except Exception as e:
        print(f"⚠️ Could not retrieve session from S3: {e}")
        return None

def _store_for_call_in_s3(session_id: str, final_json: Dict[str, Any], s3_key: str) -> str:
    """Store forCall message in S3 with correct format"""
    try:
        s3 = _get_s3_client()
        
        # Create forCall format
        for_call_data = {
            "bucket_name": S3_BUCKET_NAME,
            "key": s3_key,  # This is the /prod/final/session_id.json key
            "sender_agent": "Intent_Requirements_Agent",
            "session": session_id
        }
        
        key = f"{S3_BASE_PREFIX}/forCall/{session_id}.json" if S3_BASE_PREFIX else f"forCall/{session_id}.json"
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=json.dumps(for_call_data, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256"
        )
        print(f"✅ ForCall JSON stored in S3: s3://{S3_BUCKET_NAME}/{key}")
        return key
    except Exception as e:
        print(f"❌ Error storing forCall JSON in S3: {e}")
        raise

# ---------------------------------------------------------------------------
# Downstream Agent Integration
# ---------------------------------------------------------------------------

async def _call_planning_agent(final_json: Dict[str, Any], datetime_str: str) -> Dict[str, Any]:
    """
    1. Upload requirements to the retrieval agent (POST).
    2. Poll the retrieval agent (GET) until status == completed.
    3. Invoke the planner agent synchronously via Lambda.
    Returns a dict containing retrieval_result and planner_result.
    """
    session_id = final_json.get("session_id")
    # Generate retrieval S3 key
    retrieval_key = f"retrieval_agent/active/{datetime_str}_{session_id}.json"
    # Build POST payload
    payload = {
        "bucket_name": PLANNING_BUCKET_NAME,
        "key": retrieval_key,
        "sender_agent": "Intent Agent",
        "session": session_id
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": RETRIEVAL_AGENT_API_KEY
    }
    # Step 1: POST to retrieval agent
    post_resp = requests.post(RETRIEVAL_AGENT_URL, json=payload, headers=headers, timeout=400)
    post_resp.raise_for_status()
    post_data = post_resp.json()
    # Derive filename for polling (the retrieval service returns <timestamp>_<session>.json)
    filename = post_data.get("filename") or f"{datetime_str}_{session_id}.json"
    # Step 2: Poll retrieval agent until completed
    polling_headers = {
        "Content-Type": "application/json",
        "x-api-key": RETRIEVAL_AGENT_API_KEY
    }
    retrieval_status = {}
    while True:
        status_resp = requests.get(RETRIEVAL_AGENT_URL,
                                params={"filename": filename},
                                headers=polling_headers,
                                timeout=60)
        print(status_resp)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        if status_data.get("status") == "completed":
            retrieval_status = status_data
            break
        time.sleep(10)  # wait before next poll

    # Step 2.5: Copy processed file to planner_agent folder
    s3 = _get_s3_client()
    source_key = f"retrieval_agent/processed/{datetime_str}_{session_id}.json"
    destination_key = f"planner_agent/{datetime_str}_{session_id}.json"

    try:
        # Copy the file within the same bucket
        s3.copy_object(
            Bucket=PLANNING_BUCKET_NAME,
            CopySource={'Bucket': PLANNING_BUCKET_NAME, 'Key': source_key},
            Key=destination_key
        )
        print(f"✅ Copied {source_key} to {destination_key}")
    except Exception as e:
        print(f"❌ Error copying file: {e}")
        raise

    # Step 3: Invoke planner agent synchronously using Lambda ARN
    planner_result = lambda_synchronous_call(
        function_name=PLANNER_AGENT_FUNCTION,
        bucket_name=PLANNING_BUCKET_NAME,
        key=destination_key,
        sender_agent="Intent Agent",
        session=session_id
    )
    return {
        "status": "success",
        "retrieval_response": retrieval_status,
        "planner_response": planner_result
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class TravelPlanningRequest(BaseModel):
    user_input: str
    session_id: Optional[str] = None

class TravelPlanningResponse(BaseModel):
    success: bool
    response: str
    session_id: str
    intent: str
    conversation_state: str
    trust_score: float
    collection_complete: bool
    completion_status: Optional[str] = None
    optional_progress: Optional[str] = None
    final_json_s3_key: Optional[str] = None
    planning_agent_status: Optional[str] = None
    retrieval_agent: Optional[Dict[str, Any]] = None
    planner_response: Optional[Dict[str, Any]] = None  # ← add this
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------
def handle_errors(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            print(f"[ERROR] {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper

def _ensure_ok(res: dict, step: str):
    """
    Ensure a downstream call succeeded.
    - If service_client returned {"success": False, ...} or {"status_code": >=400}, raise 502.
    """
    if not isinstance(res, dict):
        return
    if res.get("success") is False:
        detail = res.get("error") or f"{step} failed"
        raise HTTPException(status_code=502, detail=detail)
    if res.get("status_code") and int(res["status_code"]) >= 400:
        raise HTTPException(status_code=502, detail=f"{step} HTTP {res['status_code']}: {res.get('error')}")

# ---------------------------------------------------------------------------
# Main Gateway Class
# ---------------------------------------------------------------------------
class TravelGateway:
    """Unified gateway for travel planning with security validation."""

    def __init__(self):
        print(f"🚀 Travel Gateway initialized | Mode: {DOWNSTREAM_MODE}")

    def _build_final_json(
        self, 
        session_id: str, 
        requirements_data: Dict[str, Any],
        interests: list,
        status_code: int = 200
    ) -> Dict[str, Any]:
        """Build final structured JSON for downstream agent"""
        try:
            session_data = _get_session_from_s3(session_id)

            # CHANGE THIS: Capture full conversation with roles
            conversation_messages = []
            if session_data and "conversation_history" in session_data:
                conversation_messages = [
                    {
                        "role": msg.get("role"),
                        "message": msg.get("message", "")
                    }
                    for msg in session_data["conversation_history"]
                ]
                            
            # Handle potential double-nesting
            if "requirements" in requirements_data:
                reqs = requirements_data["requirements"]
                # Check for double-nesting
                if "requirements" in reqs:
                    reqs = reqs["requirements"]
            else:
                reqs = requirements_data

            final_json = {
                "status_code": status_code,
                "interest": interests,
                "message": conversation_messages,
                "json_filename": f"sessions/{session_id}.json",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "requirements": reqs  # Use cleaned reqs directly
            }

            # Ensure travelers exist
            if "travelers" not in final_json["requirements"]:
                final_json["requirements"]["travelers"] = {"adults": None, "children": None}

            return final_json

        except Exception as e:
            print(f"❌ Error building final JSON: {e}")
            return {
                "status_code": 500,
                "interest": [],
                "message": [],  # CHANGED: Empty array instead of string
                "json_filename": f"sessions/{session_id}.json",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }
        
    async def process_input(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Main orchestration pipeline."""

        # Step 1: Session initialization
        if not session_id:
            try:
                session_data = create_session({"user_id": None})
                _ensure_ok(session_data, "session create")
                session_id = session_data.get("session_id", "unknown")
            except Exception as e:
                print(f"❌ Session creation failed: {e}")
                return {
                    "success": False,
                    "response": "I'm having trouble starting our conversation. Please try again.",
                    "session_id": None,
                    "intent": "error",
                    "error": str(e),
                    "conversation_state": "error",
                    "trust_score": 0.0,
                    "collection_complete": False
                }

        print(f"Processing input: {user_input[:60]}... (session: {session_id})")

        try:
            # Step 2: Input security validation
            security_ok = validate_input({"text": user_input, "user_context": {"session_id": session_id}})
            _ensure_ok(security_ok, "input validation")
            if not security_ok.get("is_safe", True):
                return self._create_blocked_response(session_id, "input_blocked")

            # Step 3: Intent classification
            intent_data = classify_intent({"user_input": user_input, "session_context": {"session_id": session_id}})
            _ensure_ok(intent_data, "classify intent")
            intent = intent_data.get("intent", "unknown")
            print(f"Intent classified: {intent}")

            # Step 4: Requirements gathering
            req_data = gather_requirements({
                "user_input": user_input,
                "intent": intent,
                "session_context": {"session_id": session_id},
            })
            _ensure_ok(req_data, "gather requirements")

            completion_status = req_data.get("completion_status", "incomplete")
            is_mandatory_complete = (completion_status in ["mandatory_complete", "all_complete"])
            is_all_complete = (completion_status == "all_complete")

            # Step 5: Output security validation
            validated_output = validate_output({
                "response": req_data.get("response", ""),
                "context": {"session_id": session_id},
            })
            _ensure_ok(validated_output, "output validation")

            response_text = (
                validated_output.get("filtered_response", req_data.get("response", ""))
                if not validated_output.get("is_safe", True)
                else req_data.get("response", "")
            )

            # Step 6: Update session
            upd = update_session(
                session_id,
                {
                    "conversation_state": self._get_conversation_state(intent, req_data.get("requirements_extracted", False)),
                    "last_active": datetime.now().isoformat(),
                    "last_intent": intent,
                    "requirements_complete": req_data.get("requirements_extracted", False),
                },
            )
            _ensure_ok(upd, "update session")

            trust_score = 1.0

            # Handle completion - Generate final JSON and call downstream agent
            final_json_s3_key = None
            agent_response = None

            # Get session to check stored key
            session = get_session(session_id)
            session_data = session.get("data", {}) if session else {}

            # 🔍 DEBUG: Print what we're getting
            print(f"🔍 DEBUG - Session data retrieved: {json.dumps(session_data, indent=2)}")

            # Get existing key if already created
            existing_s3_key = session_data.get("initial_json_s3_key")
            already_uploaded = session_data.get("initial_json_uploaded", False)

            print(f"🔍 DEBUG - existing_s3_key: {existing_s3_key}")
            print(f"🔍 DEBUG - already_uploaded: {already_uploaded}")

            if is_mandatory_complete:
                # Get FRESH session data to check for existing key
                session = get_session(session_id)
                session_data = session.get("data", {}) if session else {}
                existing_s3_key = session_data.get("initial_json_s3_key")
                existing_timestamp = session_data.get("initial_timestamp")  # ← NEW
                
                if not existing_timestamp:
                    existing_timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
                    update_session(session_id, {"initial_timestamp": existing_timestamp})
                
                print(f"🔍 Using timestamp: {existing_timestamp}")

                print(f"🔍 Existing S3 key: {existing_s3_key}")
                print("\n" + "=" * 80)
                if is_all_complete:
                    print("🎉 ALL REQUIREMENTS COMPLETE - FINAL PLANNING")
                else:
                    print("✅ MANDATORY COMPLETE - COLLECTING OPTIONAL FIELDS")
                print("=" * 80)

                final_json = self._build_final_json(
                    session_id=session_id,
                    requirements_data=req_data.get("requirements_data", {}),
                    interests=req_data.get("interests", []),
                    status_code=200
                )

                print("\n📋 FINAL JSON FOR DOWNSTREAM AGENT:")
                print(json.dumps(final_json, indent=2, ensure_ascii=False))
                print("\n" + "=" * 80 + "\n")

                # Store/update JSON in S3 - pass existing key to update same file
                final_json_s3_key = _store_final_json_in_s3(
                    session_id, 
                    final_json,
                    existing_key=existing_s3_key,
                    timestamp=existing_timestamp  
                )

                # Save BOTH flags at once
                update_session(session_id, {
                    "initial_json_s3_key": final_json_s3_key,
                    "initial_json_uploaded": True  # Always set to True
                })

                # Only mark as uploaded first time
                if not already_uploaded:
                    update_session(session_id, {"initial_json_uploaded": True})
                    print("✅ Marked initial JSON as uploaded")
                
                # Only call planning agent when ALL complete
                if is_all_complete:
                    agent_response = await _call_planning_agent(final_json, existing_timestamp)
                    print(f"📬 Intent agent response: {agent_response.get('status')}")
                    print(f"📬 Retrieval agent response: {agent_response.get('retrieval_response')}")
                    print(f"📬 Planning agent response: {agent_response.get('planner_response')}")
                    
                    # ✅ ADD THIS: Build PDF S3 key
                    pdf_s3_key = f"summarizer_agent/pdf/{existing_timestamp}_{session_id}.pdf"
                    agent_response["pdf_s3_key"] = pdf_s3_key  # Add to response

            # Build base response
            base_response = {
                "success": True,
                "response": response_text,
                "session_id": session_id,
                "intent": intent,
                "conversation_state": self._get_conversation_state(intent, is_mandatory_complete),
                "trust_score": trust_score,
                "collection_complete": is_all_complete,  
                "completion_status": completion_status,  
                "optional_progress": req_data.get("optional_progress", "0/6"),  
                "final_json_s3_key": final_json_s3_key,
                "planning_agent_status": agent_response.get("status") if agent_response else None,
                "pdf_s3_key": agent_response.get("pdf_s3_key") if agent_response else None  # ✅ ADD THIS
            }

            # Add retrieval agent data if available
            if agent_response and agent_response.get("status") == "success":
                retrieval_data = agent_response.get("retrieval_response", {})
                base_response["retrieval_agent"] = {
                    "status": "success",
                    "data": retrieval_data,
                    "message": "Carbon footprint analysis completed"
                }
                base_response["planner_response"] = agent_response.get("planner_response")
                
                # Optionally append to user-facing response
                if retrieval_data:
                    response_text += "\n\n🌍 Sustainability Analysis Complete! Your carbon footprint data is ready."
                    base_response["response"] = response_text

            return base_response

        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Processing error: {e}")
            return self._create_error_response(session_id, str(e))

    def _get_conversation_state(self, intent: str, requirements_extracted: bool) -> str:
        if requirements_extracted:
            return "requirements_complete"
        elif intent == "greeting":
            return "greeting_processed"
        elif intent == "blocked":
            return "input_blocked"
        else:
            return "collecting_requirements"

    def _create_blocked_response(self, session_id: str, reason: str) -> Dict[str, Any]:
        return {
            "success": False,
            "response": "I can only help with travel planning. Please ask about destinations, accommodations, or travel advice.",
            "session_id": session_id,
            "intent": "blocked",
            "conversation_state": reason,
            "trust_score": 0.5,
            "collection_complete": False
        }

    def _create_error_response(self, session_id: str, error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "response": "I encountered an issue processing your request. Could you please try again?",
            "session_id": session_id or "unknown",
            "intent": "error",
            "conversation_state": "error",
            "trust_score": 0.5,
            "error": error if config.DEBUG else None,
            "collection_complete": False
        }

# ---------------------------------------------------------------------------
# FastAPI App Setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Travel Planning Gateway",
    version="2.0.0",
    description="Unified gateway with Lambda/HTTP switching and integrated security validation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

gateway = TravelGateway()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "mode": DOWNSTREAM_MODE, "service": "travel-gateway"}

@app.post("/travel/plan", response_model=TravelPlanningResponse)
@handle_errors
async def plan_travel(request: TravelPlanningRequest):
    result = await gateway.process_input(request.user_input, request.session_id)
    return TravelPlanningResponse(**result)

@app.get("/travel/session/{session_id}")
@handle_errors
async def get_session_info(session_id: str):
    res = get_session(session_id)
    _ensure_ok(res, "get session")
    
    # Ensure consistent structure
    if "data" in res:
        session_data = res["data"]
    else:
        session_data = res
    
    return {
        "session_id": session_id,
        "data": session_data,
        "success": res.get("success", True)
    }

@app.get("/")
async def root():
    return {
        "message": "Travel Planning Gateway",
        "version": "2.0.0",
        "mode": DOWNSTREAM_MODE,
        "features": [
            "Intent Classification",
            "Requirements Gathering",
            "Security Validation",
            "Trust Scoring",
            "Final JSON Generation",
            "Downstream Agent Integration"
        ],
        "routes": ["/travel/plan", "/travel/session/{session_id}", "/health"],
    }

@app.get("/health")
async def health():
    """Health check endpoint - warms up downstream services"""
    downstream_status = {}
    
    # Warm up intent service
    try:
        result = classify_intent({"user_input": "warmup", "session_id": "warmup"})
        downstream_status["intent_service"] = "ok" if result.get("success") else "degraded"
    except Exception as e:
        downstream_status["intent_service"] = "error"
    
    # Warm up shared service
    try:
        result = create_session({"session_id": "warmup"})
        downstream_status["shared_service"] = "ok" if result.get("success") else "degraded"
    except Exception as e:
        downstream_status["shared_service"] = "error"
    
    return {
        "status": "ok",
        "downstream": downstream_status
    }

# ---------------------------------------------------------------------------
# Lambda Handler (for AWS SAM)
# ---------------------------------------------------------------------------
from mangum import Mangum
lambda_handler = Mangum(app)

# ---------------------------------------------------------------------------
# Local development entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
