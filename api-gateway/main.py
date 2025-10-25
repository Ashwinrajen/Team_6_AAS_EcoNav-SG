# api-gateway/main.py

import os
import sys
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

DOWNSTREAM_MODE = os.getenv("DOWNSTREAM_MODE", "HTTP").upper()

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
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------
def handle_errors(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            print(f"[ERROR] {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper


# ---------------------------------------------------------------------------
# Main Gateway Class
# ---------------------------------------------------------------------------
class TravelGateway:
    """Unified gateway for travel planning with security validation."""

    def __init__(self):
        print(f"🚀 Travel Gateway initialized | Mode: {DOWNSTREAM_MODE}")

    async def process_input(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Main orchestration pipeline."""

        # Step 1: Session initialization
        if not session_id:
            session_data = create_session({"user_id": None})
            session_id = session_data.get("session_id", "unknown")

        print(f"Processing input: {user_input[:60]}... (session: {session_id})")

        try:
            # Step 2: Input security validation
            security_ok = validate_input({"text": user_input, "user_context": {"session_id": session_id}})
            if not security_ok.get("is_safe", True):
                return self._create_blocked_response(session_id, "input_blocked")

            # Step 3: Intent classification
            intent_data = classify_intent({"user_input": user_input, "session_context": {"session_id": session_id}})
            intent = intent_data.get("intent", "unknown")
            print(f"Intent classified: {intent}")

            # Step 4: Requirements gathering
            req_data = gather_requirements({
                "user_input": user_input,
                "intent": intent,
                "session_context": {"session_id": session_id},
            })

            # Step 5: Output security validation
            validated_output = validate_output({
                "response": req_data.get("response", ""),
                "context": {"session_id": session_id},
            })
            response_text = (
                validated_output.get("filtered_response", req_data.get("response", ""))
                if not validated_output.get("is_safe", True)
                else req_data.get("response", "")
            )

            # Step 6: Update session + trust score (mock)
            update_session(
                session_id,
                {
                    "conversation_state": self._get_conversation_state(intent, req_data.get("requirements_extracted", False)),
                    "last_active": datetime.now().isoformat(),
                    "last_intent": intent,
                    "requirements_complete": req_data.get("requirements_extracted", False),
                },
            )
            trust_score = 1.0  # Placeholder (could later come from session table)

            return {
                "success": True,
                "response": response_text,
                "session_id": session_id,
                "intent": intent,
                "conversation_state": self._get_conversation_state(intent, req_data.get("requirements_extracted", False)),
                "trust_score": trust_score,
            }

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


# NEW: Session info route used by the Streamlit UI sidebar
@app.get("/travel/session/{session_id}")
@handle_errors
async def get_session_info(session_id: str):
    """Return session info proxied from shared-services (HTTP) or shared-services Lambda."""
    return get_session(session_id)


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
        ],
        "routes": ["/travel/plan", "/travel/session/{session_id}", "/health"],
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
