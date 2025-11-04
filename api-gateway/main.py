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

RETRIEVAL_AGENT_URL = os.getenv("RETRIEVAL_AGENT_URL")
RETRIEVAL_AGENT_API_KEY = os.getenv("RETRIEVAL_AGENT_API_KEY")

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
def _store_final_json_in_s3(session_id: str, final_json: Dict[str, Any]) -> str:
    """Store final completion JSON in S3"""
    try:
        s3 = _get_s3_client()
        key = f"{S3_BASE_PREFIX}/final/{session_id}.json" if S3_BASE_PREFIX else f"final/{session_id}.json"
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=json.dumps(final_json, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256"
        )
        print(f"✅ Final JSON stored in S3: s3://{S3_BUCKET_NAME}/{key}")
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

async def _call_planning_agent(final_json: Dict[str, Any]) -> Dict[str, Any]:
    """Call the retrieval agent with final JSON details"""
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            session_id = final_json.get("session_id")
            s3_key = f"{S3_BASE_PREFIX}/final/{session_id}.json" if S3_BASE_PREFIX else f"final/{session_id}.json"
            
            payload = {
                "bucket_name": S3_BUCKET_NAME,
                "key": s3_key,
                "sender_agent": "Intent Agent",
                "session": session_id
            }
            
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": RETRIEVAL_AGENT_API_KEY
            }
            
            print("\n" + "="*80)
            print(f"🚀 CALLING RETRIEVAL AGENT (Attempt {attempt + 1}/{max_retries})")
            print("="*80)
            print(f"📍 URL: {RETRIEVAL_AGENT_URL}")
            print(f"📦 Payload:")
            print(json.dumps(payload, indent=2))
            print("="*80 + "\n")
            
            response = requests.post(
                RETRIEVAL_AGENT_URL,
                json=payload,
                headers=headers,
                timeout=400  # ← Increased from 60 to 120 seconds
            )
            
            response.raise_for_status()
            result = response.json()
            
            print("\n" + "="*80)
            print(f"✅ RETRIEVAL AGENT RESPONSE RECEIVED")
            print("="*80)
            print(f"📥 Status Code: {response.status_code}")
            print(f"📄 Response:")
            print(json.dumps(result, indent=2))
            print("="*80 + "\n")
            
            return {
                "status": "success",
                "retrieval_response": result,
                "message": "Successfully called retrieval agent"
            }
            
        except requests.exceptions.Timeout:
            print(f"\n⚠️ Attempt {attempt + 1} timed out")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                continue
            else:
                print("❌ All retry attempts exhausted")
                return {
                    "status": "timeout",
                    "message": "Retrieval agent took too long to respond after 3 attempts"
                }
                
        except requests.exceptions.RequestException as e:
            print(f"\n❌ Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                continue
            else:
                return {
                    "status": "error",
                    "message": f"Failed after {max_retries} attempts: {str(e)}"
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
    retrieval_agent: Optional[Dict[str, Any]] = None  # ← ADD THIS
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

            # Get session to check if already uploaded
            session = get_session(session_id)
            already_uploaded = session.get("data", {}).get("initial_json_uploaded", False) if session else False

            if is_mandatory_complete:
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

                # Store/update JSON in S3
                final_json_s3_key = _store_final_json_in_s3(session_id, final_json)
                # for_call_key = _store_for_call_in_s3(session_id, final_json, final_json_s3_key)
                
                # Only call planning agent when ALL complete
                if is_all_complete:
                    agent_response = await _call_planning_agent(final_json)
                    print(f"📬 Planning agent response: {agent_response.get('status')}")
                
                # Mark as uploaded (first time only)
                if not already_uploaded:
                    update_session(session_id, {"initial_json_uploaded": True})
                    print("✅ Marked initial JSON as uploaded")

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
                "planning_agent_status": agent_response.get("status") if agent_response else None
            }

            # Add retrieval agent data if available
            if agent_response and agent_response.get("status") == "success":
                retrieval_data = agent_response.get("retrieval_response", {})
                base_response["retrieval_agent"] = {
                    "status": "success",
                    "data": retrieval_data,
                    "message": "Carbon footprint analysis completed"
                }
                
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
