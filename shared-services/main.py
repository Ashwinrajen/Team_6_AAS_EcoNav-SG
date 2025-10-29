# shared-services/main.py

import os, sys, json
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.testclient import TestClient

from security_pipeline import SecurityPipeline
from transparency import TransparencyEngine

# -------- Select backend at runtime --------
USE_S3 = os.getenv("USE_S3")
if USE_S3:
    from s3_store import (
        get_session as store_get,
        put_session as store_put,
        update_session as store_update,
        delete_session as store_delete,
    )
else:
    # Fallback to existing DDB helper
    from dynamo import (
        get_session as store_get,
        put_session as store_put,
        update_session as store_update,
        delete_session as store_delete,
    )

# ---------------------------
# Pydantic models
# ---------------------------
class SecurityInputRequest(BaseModel):
    text: str
    user_context: Optional[Dict[str, Any]] = {}

class SecurityOutputRequest(BaseModel):
    response: str
    context: Optional[Dict[str, Any]] = {}

class TrustScoreRequest(BaseModel):
    session_data: Dict[str, Any]
    user_context: Dict[str, Any]

class SessionCreateRequest(BaseModel):
    user_id: Optional[str] = None

# ---------------------------
# Session Manager (S3 or DDB)
# ---------------------------
class SessionManager:
    @staticmethod
    def ensure_session(
        session_id: str = None,
        user_id: str = None,
        updates: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        import uuid

        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        existing = store_get(session_id)
        if not existing:
            session = {
                "session_id": session_id,
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "trust_score": 1.0,
                "conversation_state": "greeting",
                "error_count": 0,
                "success_metrics": {"responses_generated": 0, "coordinations_successful": 0},
            }
            store_put(session)
            return session

        if updates:
            updates = {**updates, "last_active": datetime.now().isoformat()}
            store_update(session_id, updates)
            existing.update(updates)

        return existing

# ---------------------------
# FastAPI app & services
# ---------------------------
app = FastAPI(title="Shared Services - Security & Transparency", version="1.0.0")
security_pipeline = SecurityPipeline()
transparency_engine = TransparencyEngine()

def handle_errors(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            print(f"{func.__name__} error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "shared-services", "backend": "S3" if USE_S3 else "DDB"}

# ----- Security -----
@app.post("/security/validate-input")
@handle_errors
async def validate_input(request: SecurityInputRequest):
    return await security_pipeline.validate_input(request.text, request.user_context)

@app.post("/security/validate-output")
@handle_errors
async def validate_output(request: SecurityOutputRequest):
    return await security_pipeline.validate_output(request.response, request.context)

# ----- Transparency -----
@app.post("/transparency/trust-score")
@handle_errors
async def calculate_trust_score(request: TrustScoreRequest):
    return transparency_engine.calculate_trust_score(request.session_data, request.user_context)

@app.post("/transparency/explain-decision")
@handle_errors
async def explain_decision(request: Dict[str, Any]):
    import uuid
    decision_id = request.get("decision_id", str(uuid.uuid4())[:8])
    reasoning_data = request.get("reasoning_data", {})
    explanation = transparency_engine.explain_decision(decision_id, reasoning_data)
    return {
        "decision_id": decision_id,
        "explanation": explanation,
        "timestamp": datetime.now().isoformat(),
    }

@app.get("/transparency/report/{session_id}")
@handle_errors
async def get_transparency_report(session_id: str):
    cleaned = transparency_engine.clear_old_explanations()
    if cleaned > 0:
        print(f"Cleaned up {cleaned} old explanations")
    return transparency_engine.get_transparency_report(session_id)

# ----- Sessions -----
@app.post("/session/create")
async def create_session(request: SessionCreateRequest):
    try:
        session = SessionManager.ensure_session(user_id=request.user_id)
        return {
            "session_id": session["session_id"],
            "created_at": session["created_at"],
            "trust_score": session["trust_score"],
        }
    except Exception as e:
        print(f"Session creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Session creation failed: {str(e)}")

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    try:
        session = SessionManager.ensure_session(session_id)
        return {
            "session_id": session["session_id"],
            "user_id": session.get("user_id"),
            "trust_score": session["trust_score"],
            "conversation_state": session["conversation_state"],
            "created_at": session["created_at"],
            "last_active": session["last_active"],
            "error_count": session.get("error_count", 0),
            "success_metrics": session.get("success_metrics", {}),
        }
    except Exception as e:
        print(f"Session retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve session: {str(e)}")

@app.put("/session/{session_id}")
async def update_session(session_id: str, updates: Dict[str, Any]):
    try:
        SessionManager.ensure_session(session_id, updates=updates)
        return {"message": "Session updated successfully", "session_id": session_id}
    except Exception as e:
        print(f"Session update error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update session: {str(e)}")

@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    try:
        if store_get(session_id):
            store_delete(session_id)
            return {"message": "Session deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Session deletion error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")

@app.get("/")
async def root():
    return {
        "message": "Shared Services - Security & Transparency",
        "version": "1.0.0",
        "backend": "S3" if USE_S3 else "DDB",
        "services": {"security": "NeMo Guardrails", "transparency": "Trust & explanations"},
        "endpoints": ["/health", "/security/*", "/session/*", "/transparency/*"],
    }

# --- Lambda adapter: support both APIGW proxy via Mangum AND direct-invoke shape ---
from mangum import Mangum
_mangum = Mangum(app)

def lambda_handler(event, context):
    """
    Supports:
    1) Direct invokes (simple shape): {"path": "/session/create", "httpMethod": "POST", "body": {...}}
    2) API Gateway/HttpApi proxy events (handled by Mangum)
    """
    if isinstance(event, dict) and "path" in event:
        path = event.get("path", "")
        method = (event.get("httpMethod") or "POST").upper()
        body = event.get("body") or {}
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except Exception:
                body = {}

        with TestClient(app) as c:
            resp = c.request(method, path, json=body if method in ("POST", "PUT") else None)
            try:
                return resp.json()
            except Exception:
                # Ensure something sensible is returned
                return {"status_code": resp.status_code, "text": resp.text}

    # Default to APIGW proxy handling
    return _mangum(event, context)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
