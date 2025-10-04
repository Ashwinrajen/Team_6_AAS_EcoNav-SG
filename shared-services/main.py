# shared-services/main.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
import uuid
from functools import wraps

# Import the separated services
from security_pipeline import SecurityPipeline
from transparency import TransparencyEngine

# Pydantic models
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

# Session storage (simple in-memory)
SESSIONS = {}

class SessionManager:
    """Simplified session management"""
    
    @staticmethod
    def ensure_session(session_id: str = None, user_id: str = None, updates: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create or update session"""
        if not session_id:
            session_id = str(uuid.uuid4())[:8]
        
        if session_id not in SESSIONS:
            SESSIONS[session_id] = {
                "session_id": session_id,
                "user_id": user_id,
                "created_at": datetime.now(),
                "last_active": datetime.now(),
                "trust_score": 1.0,
                "conversation_state": "greeting",
                "error_count": 0,
                "success_metrics": {"responses_generated": 0, "coordinations_successful": 0}
            }
        
        if updates:
            SESSIONS[session_id].update(updates)
            SESSIONS[session_id]["last_active"] = datetime.now()
        
        return SESSIONS[session_id]

# Initialize FastAPI app and services
app = FastAPI(title="Shared Services - Security & Transparency", version="1.0.0")
security_pipeline = SecurityPipeline()
transparency_engine = TransparencyEngine()

# Common error handler decorator
def handle_errors(func):
    @wraps(func) 
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            print(f"{func.__name__} error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "shared-services"}

# Security endpoints
@app.post("/security/validate-input")
@handle_errors
async def validate_input(request: SecurityInputRequest):
    """Validate input using NeMo Guardrails"""
    return await security_pipeline.validate_input(request.text, request.user_context)

@app.post("/security/validate-output")
@handle_errors
async def validate_output(request: SecurityOutputRequest):
    """Validate output using NeMo Guardrails"""
    return await security_pipeline.validate_output(request.response, request.context)

# Transparency endpoints
@app.post("/transparency/trust-score")
@handle_errors
async def calculate_trust_score(request: TrustScoreRequest):
    """Calculate trust score"""
    return transparency_engine.calculate_trust_score(request.session_data, request.user_context)

@app.post("/transparency/explain-decision")
@handle_errors
async def explain_decision(request: Dict[str, Any]):
    """Generate decision explanation"""
    decision_id = request.get("decision_id", str(uuid.uuid4())[:8])
    reasoning_data = request.get("reasoning_data", {})
    explanation = transparency_engine.explain_decision(decision_id, reasoning_data)
    
    return {
        "decision_id": decision_id,
        "explanation": explanation,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/transparency/report/{session_id}")
@handle_errors
async def get_transparency_report(session_id: str):
    """Get transparency report"""
    # Trigger cleanup before generating report
    cleaned = transparency_engine.clear_old_explanations()
    if cleaned > 0:
        print(f"Cleaned up {cleaned} old explanations")
    
    return transparency_engine.get_transparency_report(session_id)

# Session management endpoints
@app.post("/session/create")
async def create_session(request: SessionCreateRequest):
    """Create a new session"""
    try:
        session = SessionManager.ensure_session(user_id=request.user_id)
        return {
            "session_id": session["session_id"],
            "created_at": session["created_at"].isoformat(),
            "trust_score": session["trust_score"]
        }
    except Exception as e:
        print(f"Session creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Session creation failed: {str(e)}")

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session information"""
    try:
        session = SessionManager.ensure_session(session_id)
        return {
            "session_id": session["session_id"],
            "user_id": session.get("user_id"),
            "trust_score": session["trust_score"],
            "conversation_state": session["conversation_state"],
            "created_at": session["created_at"].isoformat(),
            "last_active": session["last_active"].isoformat(),
            "error_count": session.get("error_count", 0),
            "success_metrics": session.get("success_metrics", {})
        }
    except Exception as e:
        print(f"Session retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve session: {str(e)}")

@app.put("/session/{session_id}")
async def update_session(session_id: str, updates: Dict[str, Any]):
    """Update session"""
    try:
        SessionManager.ensure_session(session_id, updates=updates)
        return {"message": "Session updated successfully", "session_id": session_id}
    except Exception as e:
        print(f"Session update error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update session: {str(e)}")

@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete session"""
    try:
        if session_id in SESSIONS:
            del SESSIONS[session_id]
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
    """Root endpoint"""
    return {
        "message": "Shared Services - Security & Transparency",
        "version": "1.0.0",
        "services": {
            "security": "NeMo Guardrails validation",
            "transparency": "Trust scoring and decision explanation"
        },
        "available_endpoints": [
            "/health",
            "/security/validate-input",
            "/security/validate-output", 
            "/transparency/trust-score",
            "/transparency/explain-decision",
            "/transparency/report/{session_id}",
            "/session/create",
            "/session/{session_id}"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)