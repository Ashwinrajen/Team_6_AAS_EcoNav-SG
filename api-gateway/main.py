# api-gateway/main.py

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
from datetime import datetime
from functools import wraps

from configs.config import config

# Service configuration
class ServiceConfig:
    INTENT_REQUIREMENTS_SERVICE = "http://localhost:8001"
    SHARED_SERVICES = "http://localhost:8004"

# Pydantic models
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

# Error handling decorator
def handle_errors(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPError as e:
            print(f"HTTP error in {func.__name__}: {str(e)}")
            raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
        except Exception as e:
            print(f"Error in {func.__name__}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper

class TravelGateway:
    """Simplified Travel Planning Gateway with integrated security validation"""
    
    def __init__(self):
        print("Travel Gateway initialized with security integration")
    
    async def process_input(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Main processing pipeline with security validation"""
        
        # Step 1: Create session if needed
        if not session_id:
            session_data = await self._create_session()
            session_id = session_data["session_id"]
        
        try:
            print(f"Processing input: {user_input[:50]}...")
            
            # Step 2: Input security validation
            if not await self._validate_input_security(user_input, session_id):
                return self._create_blocked_response(session_id, "input_blocked")
            
            # Step 3: Intent classification
            intent = await self._classify_intent(user_input, session_id)
            print(f"Intent classified: {intent}")
            
            # Step 4: Requirements gathering
            response = await self._gather_requirements(user_input, intent, session_id)
            
            # Step 5: Output security validation
            response["response"] = await self._validate_output_security(
                response["response"], session_id
            )
            
            # Step 6: Update session and calculate trust
            await self._update_session_state(session_id, intent, response.get("requirements_extracted", False))
            trust_score = await self._get_trust_score(session_id)
            
            return {
                "success": True,
                "response": response["response"],
                "session_id": session_id,
                "intent": intent,
                "conversation_state": self._get_conversation_state(intent, response.get("requirements_extracted", False)),
                "trust_score": trust_score
            }
            
        except Exception as e:
            print(f"Processing error: {str(e)}")
            return self._create_error_response(session_id, str(e))
    
    async def _create_session(self) -> Dict[str, Any]:
        """Create new session via shared services"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{ServiceConfig.SHARED_SERVICES}/session/create",
                json={}
            )
            response.raise_for_status()
            return response.json()
    
    async def _validate_input_security(self, user_input: str, session_id: str) -> bool:
        """Validate input security and return boolean result"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{ServiceConfig.SHARED_SERVICES}/security/validate-input",
                    json={"text": user_input, "user_context": {"session_id": session_id}}
                )
                response.raise_for_status()
                result = response.json()
                return result.get("is_safe", True)
        except Exception as e:
            print(f"Input security validation failed: {e}")
            return True  # Fail open for availability
    
    async def _validate_output_security(self, response_text: str, session_id: str) -> str:
        """Validate output security and return filtered response"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{ServiceConfig.SHARED_SERVICES}/security/validate-output",
                    json={"response": response_text, "context": {"session_id": session_id}}
                )
                response.raise_for_status()
                result = response.json()
                
                if not result.get("is_safe", True):
                    return result.get("filtered_response", 
                        "I apologize, but I cannot provide that information. Let me help you with your travel planning instead.")
                return response_text
        except Exception as e:
            print(f"Output security validation failed: {e}")
            return response_text  # Fail open
    
    async def _classify_intent(self, user_input: str, session_id: str) -> str:
        """Classify user intent"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{ServiceConfig.INTENT_REQUIREMENTS_SERVICE}/classify-intent",
                json={
                    "user_input": user_input,
                    "session_context": {"session_id": session_id}
                }
            )
            response.raise_for_status()
            return response.json()["intent"]
    
    async def _gather_requirements(self, user_input: str, intent: str, session_id: str) -> Dict[str, Any]:
        """Gather travel requirements"""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{ServiceConfig.INTENT_REQUIREMENTS_SERVICE}/gather-requirements",
                json={
                    "user_input": user_input,
                    "intent": intent,
                    "session_context": {"session_id": session_id}
                }
            )
            response.raise_for_status()
            return response.json()
    
    async def _update_session_state(self, session_id: str, intent: str, requirements_extracted: bool):
        """Update session state"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.put(
                    f"{ServiceConfig.SHARED_SERVICES}/session/{session_id}",
                    json={
                        "conversation_state": self._get_conversation_state(intent, requirements_extracted),
                        "last_active": datetime.now().isoformat(),
                        "last_intent": intent,
                        "requirements_complete": requirements_extracted
                    }
                )
        except Exception as e:
            print(f"Session update failed: {e}")
    
    async def _get_trust_score(self, session_id: str) -> float:
        """Get trust score from session"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{ServiceConfig.SHARED_SERVICES}/session/{session_id}")
                response.raise_for_status()
                return response.json().get("trust_score", 1.0)
        except Exception:
            return 1.0
    
    def _get_conversation_state(self, intent: str, requirements_extracted: bool) -> str:
        """Determine conversation state"""
        if requirements_extracted:
            return "requirements_complete"
        elif intent == "greeting":
            return "greeting_processed"
        elif intent == "blocked":
            return "input_blocked"
        else:
            return "collecting_requirements"
    
    def _create_blocked_response(self, session_id: str, reason: str) -> Dict[str, Any]:
        """Create response for blocked input"""
        return {
            "success": False,
            "response": "I can only help with travel planning. Please ask about destinations, accommodations, or travel advice.",
            "session_id": session_id,
            "intent": "blocked",
            "conversation_state": reason,
            "trust_score": 0.5
        }
    
    def _create_error_response(self, session_id: str, error: str) -> Dict[str, Any]:
        """Create error response"""
        return {
            "success": False,
            "response": "I encountered an issue processing your request. Could you please try again?",
            "session_id": session_id or "unknown",
            "intent": "error",
            "conversation_state": "error",
            "trust_score": 0.5,
            "error": error if config.DEBUG else None
        }
    
    async def get_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get session information"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{ServiceConfig.SHARED_SERVICES}/session/{session_id}")
            response.raise_for_status()
            return response.json()

# Initialize FastAPI app
app = FastAPI(
    title="Travel Planning Gateway", 
    version="2.0.0",
    description="Simplified gateway with integrated security validation"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize gateway
gateway = TravelGateway()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "travel-gateway"}

@app.post("/travel/plan", response_model=TravelPlanningResponse)
@handle_errors
async def plan_travel(request: TravelPlanningRequest):
    """Main travel planning endpoint"""
    result = await gateway.process_input(request.user_input, request.session_id)
    return TravelPlanningResponse(**result)

@app.get("/travel/session/{session_id}")
@handle_errors
async def get_session_info(session_id: str):
    """Get session information"""
    return await gateway.get_session_info(session_id)

@app.get("/")
async def root():
    return {
        "message": "Travel Planning Gateway",
        "version": "2.0.0",
        "features": [
            "Binary Intent Classification",
            "Intelligent Requirements Gathering", 
            "Integrated Security Validation",
            "Trust Score Calculation"
        ],
        "endpoints": [
            "/health",
            "/travel/plan", 
            "/travel/session/{session_id}"
        ],
        "services": {
            "intent_requirements": "http://localhost:8001",
            "shared_services": "http://localhost:8004"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)