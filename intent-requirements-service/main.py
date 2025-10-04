# intent-requirements-service/main.py

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import json
import re
import copy
import yaml
from pathlib import Path
from crewai import Agent, Task, Crew
from colorama import Fore, Style, init
from datetime import datetime, timedelta
import uuid


# Colorama for colored terminal output
init(autoreset=True)

from configs.config import config as app_config
from configs.config import config 
os.environ["CREWAI_TRACING_ENABLED"] = str(config.CREWAI_TRACING_ENABLED).lower()

class IntentRequest(BaseModel):
    user_input: str
    session_context: Optional[Dict[str, Any]] = Field(default=None)

class IntentResponse(BaseModel):
    intent: str

class RequirementsRequest(BaseModel):
    user_input: str
    intent: str
    session_context: Optional[Dict[str, Any]] = Field(default=None)

class RequirementsResponse(BaseModel):
    response: str
    intent: str
    requirements_extracted: bool
    requirements_data: Optional[Dict[str, Any]] = Field(default=None)

# Session storage with caching
SESSION_CACHE = {}

def load_config_file(filename: str) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    config_path = Path(__file__).parent / 'configs' / filename
    if config_path.exists():
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    return {}

class IntentRequirementsService:
    def __init__(self):
        # Load configurations
        self.agents_config = load_config_file('agents_config.yaml')
        self.tasks_config = load_config_file('tasks_config.yaml')
        
        print(f"{Fore.MAGENTA}🚀 INITIALIZING TRAVEL SERVICE")
        print(f"{Fore.MAGENTA}Loaded agents config: {len(self.agents_config)} agents")
        print(f"{Fore.MAGENTA}Loaded tasks config: {len(self.tasks_config)} tasks{Style.RESET_ALL}")
        
        # Create specialized agents
        self.intent_agent = self._create_intent_agent()
        self.requirements_agent = self._create_requirements_agent()
        
        # Target JSON structure
        self.target_json_template = {
            "requirements": {
                "destination_city": None,
                "trip_dates": {
                    "start_date": None,
                    "end_date": None
                },
                "duration_days": None,
                "budget_total_sgd": None,
                "pace": None,
                "optional": {
                    "eco_preferences": None,
                    "dietary_preferences": None,
                    "interests": [],
                    "uninterests": [],
                    "accessibility_needs": None,
                    "accommodation_location": {
                        "neighborhood": None
                    },
                    "group_type": None
                }
            }
        }
        
        print(f"{Fore.GREEN}✅ SERVICE INITIALIZED SUCCESSFULLY{Style.RESET_ALL}")
    
    def _create_intent_agent(self) -> Agent:
        """Create binary intent classification agent"""
        config = self.agents_config.get('intent_classifier', {})
        print(f"{Fore.YELLOW}🤖 Creating Intent Classification Agent")
        
        # Create agent without memory to avoid Pydantic issues
        return Agent(
            role=config.get('role', 'Intent Classifier'),
            goal=config.get('goal', 'Binary intent classification'),
            backstory=config.get('backstory', 'Expert classifier'),
            verbose=config.get('verbose', False),
            allow_delegation=config.get('allow_delegation', False),
            memory=False,  # Disable memory to avoid Pydantic issues
            max_iter=config.get('max_iter', 1),
            max_execution_time=config.get('max_execution_time', 30)
        )
    
    def _create_requirements_agent(self) -> Agent:
        """Create intelligent requirements gathering agent"""
        config = self.agents_config.get('requirements_gatherer', {})
        print(f"{Fore.YELLOW}🤖 Creating Requirements Gathering Agent")
        
        # Create agent without memory initially to avoid Pydantic issues
        return Agent(
            role=config.get('role', 'Requirements Collector'),
            goal=config.get('goal', 'Intelligent requirements gathering'),
            backstory=config.get('backstory', 'Expert at gathering travel information'),
            verbose=config.get('verbose', False),
            allow_delegation=config.get('allow_delegation', False),
            memory=False,  # Disable memory to avoid Pydantic issues
            max_iter=config.get('max_iter', 3),
            max_execution_time=config.get('max_execution_time', 60)
        )
    
    def _get_session_data(self, session_id: str) -> Dict[str, Any]:
        """Get or create cached session data"""
        if session_id not in SESSION_CACHE:
            print(f"{Fore.BLUE}📝 Creating new session: {session_id}")
            SESSION_CACHE[session_id] = {
                "conversation_history": [],
                "requirements": copy.deepcopy(self.target_json_template),
                "phase": "initial",
                "last_updated": None
            }
        return SESSION_CACHE[session_id]
    
    def _cleanup_old_sessions(self):
        """Remove sessions older than 24 hours"""
        current_time = datetime.now()
        expired_sessions = [
            sid for sid, data in SESSION_CACHE.items()
            if current_time - data.get("last_updated", current_time) > timedelta(hours=24)
        ]
        for sid in expired_sessions:
            del SESSION_CACHE[sid]
    
    def _update_session(self, session_id: str, user_input: str, agent_response: str, requirements: Dict = None):
        """Update session with conversation and requirements"""
        session = self._get_session_data(session_id)
        session["conversation_history"].append({"role": "user", "message": user_input})
        session["conversation_history"].append({"role": "agent", "message": agent_response})
        
        if requirements:
            session["requirements"] = requirements
        
        # Keep only last 10 messages for memory efficiency
        if len(session["conversation_history"]) > 10:
            session["conversation_history"] = session["conversation_history"][-10:]
    
    async def classify_intent(self, user_input: str) -> str:
        """Binary intent classification: greeting or planning"""
        try:
            task_config = self.tasks_config.get('binary_intent_classification', {})
            prompt = task_config.get('description', '').format(
                user_input=user_input,
                max_tokens=app_config.MAX_TOKENS
            )
            
            task = Task(
                description=prompt,
                agent=self.intent_agent,
                expected_output=task_config.get('expected_output', 'Intent classification')
            )
            
            # Use kickoff() with proper error handling
            crew = Crew(agents=[self.intent_agent], tasks=[task], verbose=False, process_timeout=None)
            result = str(crew.kickoff()).lower().strip()
            
            print(f"{Fore.CYAN}🎯 Intent Classification Result: {result}{Style.RESET_ALL}")
            
            if "greeting" in result:
                return "greeting"
            elif "other" in result:
                return "other"
            else:
                return "planning"
                
        except Exception as e:
            print(f"{Fore.RED}❌ Intent classification error: {e}{Style.RESET_ALL}")
            # Fallback classification
            user_lower = user_input.lower()
            if any(word in user_lower for word in ["hello", "hi", "hey", "good morning", "how are you"]):
                return "greeting"
            elif any(word in user_lower for word in ["travel", "trip", "visit", "go", "plan", "book"]):
                return "planning"
            else:
                return "other"
        
    async def gather_requirements(self, user_input: str, intent: str, session_id: str) -> Dict:
        
        session = self._get_session_data(session_id)
        
        # Handle off-topic conversations
        if intent == "other":
            return await self._handle_other_intent(user_input, session_id)
        
        # Continue with existing logic
        if intent == "greeting":
            return await self._handle_greeting(user_input, session_id)
        else:  # planning
            return await self._handle_planning(user_input, session_id)
    
    async def _handle_greeting(self, user_input: str, session_id: str) -> Dict:
        """Handle greeting and transition to planning"""
        try:
            task_config = self.tasks_config.get('greeting_to_planning_transition', {})
            prompt = task_config.get('description', '').format(user_input=user_input)
            
            task = Task(
                description=prompt,
                agent=self.requirements_agent,
                expected_output=task_config.get('expected_output', 'Greeting with planning question')
            )
            
            crew = Crew(agents=[self.requirements_agent], tasks=[task], verbose=False, process_timeout=None)
            response = str(crew.kickoff())
            
            # Update session and move to collecting phase
            session = self._get_session_data(session_id)
            session["phase"] = "initial"
            self._update_session(session_id, user_input, response)
            
            result = {
                "response": response,
                "intent": "greeting",
                "requirements_extracted": False,
                "requirements_data": session["requirements"]
            }
            
            return result
            
        except Exception as e:
            print(f"{Fore.RED}❌ Greeting handling error: {type(e).__name__}: {e}{Style.RESET_ALL}")
    
    async def _handle_planning(self, user_input: str, session_id: str) -> Dict:
        """Handle planning with comprehensive requirements collection"""
        try:
            session = self._get_session_data(session_id)
            
            # Prepare conversation history
            conversation_history = "\n".join([
                f"{msg['role']}: {msg['message']}" 
                for msg in session["conversation_history"][-6:]
            ])
            
            task_config = self.tasks_config.get('comprehensive_requirements_collection', {})
            prompt = task_config.get('description', '').format(
                user_input=user_input,
                conversation_history=conversation_history,
                current_requirements=json.dumps(session["requirements"], indent=2),
                phase=session["phase"],
                target_json=json.dumps(self.target_json_template, indent=2),
                max_tokens=app_config.MAX_TOKENS
            )
            
            task = Task(
                description=prompt,
                agent=self.requirements_agent,
                expected_output=task_config.get('expected_output', 'Requirements extraction')
            )
            
            crew = Crew(agents=[self.requirements_agent], tasks=[task], verbose=False)
            result = str(crew.kickoff())
            
            # Parse result using advanced regex
            json_match = re.search(r'EXTRACTED_JSON:\s*(\{.*?\})\s*(?=RESPONSE:|$)', result, re.DOTALL)
            response_match = re.search(r'RESPONSE:\s*(.*?)(?=\nPHASE:|$)', result, re.DOTALL)
            phase_match = re.search(r'PHASE:\s*(\w+)', result)
            
            # Extract components
            response_text = response_match.group(1).strip() if response_match else "Let me help you plan your trip!"
            new_phase = phase_match.group(1) if phase_match else session["phase"]
            
            # Update requirements if JSON found
            updated_requirements = session["requirements"]
            if json_match:
                try:
                    extracted_json = json.loads(json_match.group(1))
                    print(f"📊 EXTRACTED JSON:")
                    print(json.dumps(extracted_json, indent=2))
                    updated_requirements = extracted_json
                    session["requirements"] = updated_requirements

                except json.JSONDecodeError as e:
                    print(f"{Fore.YELLOW}⚠️ JSON parsing failed, using existing requirements: {e}{Style.RESET_ALL}")
            
            # Check completion
            requirements_extracted = self._check_completion(updated_requirements)
            if requirements_extracted:
                new_phase = "complete"
                response_text += "\n\nExcellent! I have all the information needed for your sustainable travel planning."
            
            # Update session
            session["phase"] = new_phase
            self._update_session(session_id, user_input, response_text, updated_requirements)
            
            final_result = {
                "response": response_text,
                "intent": "planning",
                "requirements_extracted": requirements_extracted,
                "requirements_data": updated_requirements
            }
            
            return final_result
            
        except Exception as e:
            print(f"{Fore.RED}❌ ERROR IN PLANNING: {str(e)}{Style.RESET_ALL}")
            import traceback
            traceback.print_exc()
            # Fallback response
            session = self._get_session_data(session_id)
            return {
                "response": "I'd be happy to help you plan your sustainable travel! Could you tell me where you'd like to go and when?",
                "intent": "planning", 
                "requirements_extracted": False,
                "requirements_data": session["requirements"]
            }

    async def _handle_other_intent(self, user_input: str, session_id: str) -> Dict:
        """Handle off-topic conversations with fixed redirect"""
        session = self._get_session_data(session_id)
        
        # Check if we have any collected requirements to reference
        reqs = session["requirements"]["requirements"]
        has_data = any([
            reqs.get("destination_city"),
            reqs.get("trip_dates", {}).get("start_date"),
            reqs.get("budget_total_sgd")
        ])
        
        if has_data:
            response = "I'd love to chat, but let's focus on planning your trip first. What other travel details can you share with me?"
        else:
            response = "I'm here to help you plan sustainable travel. Where would you like to go for your next trip?"
        
        return {
            "response": response,
            "intent": "other",
            "requirements_extracted": False,
            "requirements_data": session["requirements"]
        }
        
    def _check_completion(self, requirements: Dict) -> bool:
        reqs = requirements.get("requirements", {})
        trip_dates = reqs.get("trip_dates", {})
        
        required_fields = [
            reqs.get("destination_city"),
            trip_dates.get("start_date"),
            trip_dates.get("end_date"),
            reqs.get("duration_days"),
            reqs.get("budget_total_sgd"),
            reqs.get("pace")
        ]
        
        completion_status = all(field is not None and field != "" for field in required_fields)
        
        return completion_status

# Initialize service
app = FastAPI(title="Enhanced Travel Requirements Service", version="2.0.0")
service = IntentRequirementsService()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "enhanced-travel-requirements"}

@app.post("/classify-intent", response_model=IntentResponse)
async def classify_intent(request: IntentRequest):
    try:
        if not request.user_input.strip():
            raise HTTPException(status_code=400, detail="User input cannot be empty")
        
        intent = await service.classify_intent(request.user_input)
        return IntentResponse(intent=intent)
    except Exception as e:
        print(f"{Fore.RED}❌ INTENT CLASSIFICATION ERROR: {str(e)}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"Intent classification failed: {str(e)}")

@app.post("/gather-requirements", response_model=RequirementsResponse)
async def gather_requirements(request: RequirementsRequest):
    try:
        session_id = (request.session_context or {}).get("session_id") or f"auto_{uuid.uuid4().hex[:8]}"
        result = await service.gather_requirements(request.user_input, request.intent, session_id)
        return RequirementsResponse(**result)
    except Exception as e:
        print(f"{Fore.RED}❌ REQUIREMENTS GATHERING ERROR: {str(e)}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"Requirements gathering failed: {str(e)}")

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    return service._get_session_data(session_id)

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in SESSION_CACHE:
        del SESSION_CACHE[session_id]
        return {"message": "Session cleared"}
    return {"message": "Session not found"}

@app.get("/")
async def root():
    return {
        "message": "Enhanced Travel Requirements Service",
        "version": "2.0.0",
        "intents": ["greeting", "planning"],
        "features": ["Binary Intent Classification", "Intelligent Requirements Collection", "Enhanced Terminal Output", "Memory & Caching", "Edge Case Handling"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)