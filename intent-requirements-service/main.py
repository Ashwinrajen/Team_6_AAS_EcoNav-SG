# intent-requirements-service/main.py

import os
import os
os.environ['HOME'] = '/tmp'
os.environ['TMPDIR'] = '/tmp'

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
from decimal import Decimal

import asyncio
from langchain_openai import ChatOpenAI
import httpx

# Colorama for colored terminal output
init(autoreset=True)

from configs.config import config as app_config
from configs.config import config

# centralised persistence (DynamoDB or in-memory depending on USE_DDB)
from memory_store import get_memory, put_memory

# -------------------------------------------------
# Pydantic models
# -------------------------------------------------
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
    completion_status: str = Field(default="incomplete")  # NEW
    interests: list = Field(default_factory=list)         # NEW

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def load_config_file(filename: str) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    config_path = Path(__file__).parent / 'configs' / filename
    if config_path.exists():
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    return {}

def _from_ddb(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, list):
        return [_from_ddb(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    return obj

def _print_extracted_json(extracted_json: Dict[str, Any], session_id: str):
    """Print extracted JSON to terminal for visibility"""
    print("\n" + "=" * 80)
    print(f"📊 EXTRACTED REQUIREMENTS FOR SESSION: {session_id}")
    print("=" * 80)
    print(json.dumps(extracted_json, indent=2, ensure_ascii=False))
    print("=" * 80 + "\n")

def _extract_interests(requirements: Dict[str, Any]) -> list:
    """Extract interests from requirements optional fields"""
    try:
        reqs = requirements.get("requirements", {})
        optional = reqs.get("optional", {})
        interests = optional.get("interests", [])
        
        # Ensure it's a list
        if isinstance(interests, list):
            return [str(i).strip() for i in interests if i]
        return []
    except Exception as e:
        print(f"⚠️ Error extracting interests: {e}")
        return []

# -------------------------------------------------
# Service
# -------------------------------------------------
class IntentRequirementsService:
    def __init__(self):
        # Load configurations
        self.agents_config = load_config_file('agents_config.yaml')
        self.tasks_config = load_config_file('tasks_config.yaml')
        self.llm = self._build_llm()
        
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
                "travelers": {  
                    "adults": None,
                    "children": None
                },
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

    def _build_llm(self):
        http = httpx.Client(timeout=httpx.Timeout(25.0, connect=5.0, read=25.0, write=10.0))
        return ChatOpenAI(
            model=app_config.OPENAI_MODEL_NAME,   # now gpt-4o-mini
            temperature=0.2,
            max_tokens=min(app_config.MAX_TOKENS, 600),
            max_retries=1,                        # small retry to avoid transient blips
            http_client=http,
        )

    async def _run_crew(self, crew, timeout: int):
        # run in a worker thread, but still enforce an async timeout
        return await asyncio.wait_for(asyncio.to_thread(crew.kickoff), timeout=timeout)

    def _create_intent_agent(self) -> Agent:
        c = self.agents_config.get('intent_classifier', {})
        return Agent(
            role=c.get('role', 'Intent Classifier'),
            goal=c.get('goal', 'Binary intent classification'),
            backstory=c.get('backstory', 'Expert classifier'),
            verbose=False,
            allow_delegation=False,
            memory=False,
            max_iter=1,
            max_execution_time=15,   # tighter
            llm=self.llm,
        )
    
    def _create_requirements_agent(self) -> Agent:
        c = self.agents_config.get('requirements_gatherer', {})
        return Agent(
            role=c.get('role', 'Requirements Collector'),
            goal=c.get('goal', 'Intelligent requirements gathering'),
            backstory=c.get('backstory', 'Expert at gathering travel information'),
            verbose=False,
            allow_delegation=False,
            memory=False,
            max_iter=1,              # ← set to 1 for speed; Crew still used
            max_execution_time=25,   # ← keep modest
            llm=self.llm,
        )
    
    # ---------- SESSION PERSISTENCE (via memory_store) ----------
    def _get_session_data(self, session_id: str) -> Dict[str, Any]:
        """Load session memory from store (DDB/in-memory)"""
        mem = get_memory(session_id, self.target_json_template)
        # Ensure expected shape
        mem.setdefault("conversation_history", [])
        mem.setdefault("requirements", copy.deepcopy(self.target_json_template))
        mem.setdefault("phase", "initial")
        return mem
    
    def _update_session(
        self,
        session_id: str,
        user_input: str,
        agent_response: str,
        requirements: Dict = None,
        phase: Optional[str] = None,
        conversation_history: list = None
    ):
        """Persist conversation + requirements with minimal mutation"""
        # Load fresh session data if history not provided
        if conversation_history is None:
            session = self._get_session_data(session_id)
            conversation_history = session.get("conversation_history", []).copy()  # ← COPY IT
            reqs = requirements or session.get("requirements", copy.deepcopy(self.target_json_template))
            new_phase = phase or session.get("phase", "initial")
        else:
            # CRITICAL: Make a copy to avoid mutating the original
            conversation_history = conversation_history.copy()  # ← COPY IT
            reqs = requirements if requirements is not None else copy.deepcopy(self.target_json_template)
            new_phase = phase if phase is not None else "initial"
        
        # Append new messages to the COPY
        conversation_history.append({"role": "user", "message": user_input})
        conversation_history.append({"role": "agent", "message": agent_response})
        
        # Persist the updated copy
        put_memory(session_id, conversation_history, reqs, new_phase)
    
    # ---------- AGENT WORK ----------
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
            
            crew = Crew(
                agents=[self.intent_agent], 
                tasks=[task], 
                verbose=False, 
                memory=False,  
                process_timeout=12
            )
            result = str(await self._run_crew(crew, timeout=15)).lower().strip()

            
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
        
    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """Deep merge two dictionaries, with update taking precedence for non-null values"""
        result = base.copy()
        
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursively merge nested dicts
                result[key] = self._deep_merge(result[key], value)
            elif value is not None:
                # Update with non-null values
                result[key] = value
            # Skip if value is None (don't overwrite existing with null)
        
        return result
    
    async def _handle_greeting(self, user_input: str, session_id: str) -> Dict:
        """Handle greeting and transition to planning"""
        session = self._get_session_data(session_id) 
        try:
            task_config = self.tasks_config.get('greeting_to_planning_transition', {})
            prompt = task_config.get('description', '').format(user_input=user_input)
            
            task = Task(
                description=prompt,
                agent=self.requirements_agent,
                expected_output=task_config.get('expected_output', 'Greeting with planning question')
            )
            
            crew = Crew(
                agents=[self.requirements_agent], 
                tasks=[task], 
                verbose=False,
                memory=False,  
                process_timeout=18
            )
            response = str(await self._run_crew(crew, timeout=20))
            
            # Move/keep phase as "initial"
            self._update_session(session_id, user_input, response, requirements=None, phase="initial", conversation_history=session["conversation_history"])
            session = self._get_session_data(session_id)
            
            result = {
                "response": response,
                "intent": "greeting",
                "requirements_extracted": False,
                "requirements_data": session["requirements"],
                "completion_status": "incomplete",  
                "interests": []                     
            }
            return result
            
        except Exception as e:
            print(f"{Fore.RED}❌ Greeting handling error: {type(e).__name__}: {e}{Style.RESET_ALL}")
            # graceful fallback
            fallback = "Hello! I'm helping you plan your trip. Where would you like to go and when?"
            self._update_session(session_id, user_input, fallback, requirements=None, phase="initial", conversation_history=session["conversation_history"])
            session = self._get_session_data(session_id)
            return {
                "response": fallback,
                "intent": "greeting",
                "requirements_extracted": False,
                "requirements_data": session["requirements"],
                "completion_status": "incomplete", 
                "interests": []                    
            }
        
    # Add this function before _handle_planning
    def _normalize_field_names(self, data: Dict) -> Dict:
        """Normalize field names to match expected schema"""
        if not isinstance(data, dict):
            return data
        
        normalized = {}
        field_mappings = {
            'dest': 'destination_city',
            'destination': 'destination_city',
            'location': 'destination_city',
            'startDate': 'start_date',
            'endDate': 'end_date',
            'budgetSGD': 'budget_total_sgd',
            'budget': 'budget_total_sgd',
        }
        
        for key, value in data.items():
            new_key = field_mappings.get(key, key)
            normalized[new_key] = self._normalize_field_names(value) if isinstance(value, dict) else value
        
        return normalized
    
    async def _handle_planning(self, user_input: str, session_id: str) -> Dict:
        """Handle planning with comprehensive requirements collection"""
        try:
            session = self._get_session_data(session_id)
            
            # Prepare conversation history (last ~6 turns)
            conversation_history = "\n".join([
                f"{msg['role']}: {msg['message']}" 
                for msg in session["conversation_history"][-10:]
            ])
            
            task_config = self.tasks_config.get('comprehensive_requirements_collection', {})
            safe_requirements = _from_ddb(session["requirements"])
            prompt = task_config.get('description', '').format(
                user_input=user_input,
                conversation_history=conversation_history,
                current_requirements=json.dumps(safe_requirements, indent=2),
                phase=session["phase"],
                target_json=json.dumps(self.target_json_template, indent=2),
                max_tokens=app_config.MAX_TOKENS
            )
            
            task = Task(
                description=prompt,
                agent=self.requirements_agent,
                expected_output=task_config.get('expected_output', 'Requirements extraction')
            )
            
            crew = Crew(
                agents=[self.requirements_agent], 
                tasks=[task], 
                verbose=True,
                memory=False,
                process_timeout=120
            )
            result = str(await self._run_crew(crew, timeout=125))
            
            # Parse result using advanced regex
            json_match = re.search(r'EXTRACTED_JSON:\s*(\{.*?\})\s*RESPONSE:', result, re.DOTALL | re.MULTILINE)
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
                    
                    # Validate and normalize structure
                    if "requirements" in extracted_json:
                        extracted_reqs = extracted_json["requirements"]
                    else:
                        print("⚠️ Wrapping extracted JSON in requirements key")
                        extracted_reqs = extracted_json

                    # Check session for double-nesting and fix
                    session_reqs = session["requirements"]
                    if "requirements" in session_reqs:
                        print("⚠️ Fixing double-nested session requirements")
                        session_reqs = session_reqs["requirements"]

                    # Merge at the requirements level
                    merged_reqs = self._deep_merge(session_reqs, extracted_reqs)

                    # Always wrap in requirements key for consistency
                    updated_requirements = {"requirements": merged_reqs}
                except json.JSONDecodeError as e:
                    print(f"{Fore.YELLOW}⚠️ JSON parsing failed, using existing requirements: {e}{Style.RESET_ALL}")
            # if json_match:
            #     try:
            #         extracted_json = json.loads(json_match.group(1))
                    
            #         # Extract the inner requirements object for merging
            #         if "requirements" in extracted_json:
            #             extracted_reqs = extracted_json["requirements"]
            #         else:
            #             print("⚠️ Invalid JSON structure - missing 'requirements' key")
            #             extracted_reqs = extracted_json
                    
            #         # Fix if session has double nesting
            #         session_reqs = session["requirements"]
            #         if "requirements" in session_reqs:
            #             print("⚠️ Fixing double-nested session requirements")
            #             session_reqs = session_reqs["requirements"]

            #         # Merge with existing to avoid data loss
            #         updated_requirements = self._deep_merge(
            #             session_reqs, 
            #             extracted_reqs  # ← Use extracted_reqs, not extracted_json!
            #         )
            #     except json.JSONDecodeError as e:
            #         print(f"{Fore.YELLOW}⚠️ JSON parsing failed, using existing requirements: {e}{Style.RESET_ALL}")

            # Extract interests BEFORE using it
            interests = _extract_interests(updated_requirements)

            # Check completion status
            completion_info = self._check_completion(updated_requirements)
            mandatory_complete = completion_info["mandatory_complete"]
            all_complete = completion_info["all_complete"]
            optional_filled = completion_info["optional_filled"]

            # Determine completion status
            if all_complete:
                completion_status = "all_complete"
                new_phase = "complete"
                
                # REMOVE the question-asking part when complete
                question_patterns = [
                    r"could you (?:please )?(?:share|tell|provide|let me know)[^?]*\?",
                    r"(?:what|which|how much|how many)[^?]*\?",
                    r"please (?:share|tell|provide)[^?]*\?",
                    r"now,?\s+(?:could|can|would)[^?]*\?",
                    r"if there'?s anything else[^.]*\.",  # ← ADD THIS
                    r"feel free to let me know[^.]*\.",   # ← ADD THIS
                ]
                
                for pattern in question_patterns:
                    response_text = re.sub(pattern, "", response_text, flags=re.IGNORECASE)
                
                # Clean up formatting
                response_text = re.sub(r'\s+', ' ', response_text).strip()
                response_text = re.sub(r'\.\s*\.', '.', response_text)
                
                # ADD automatic completion message
                if not response_text.endswith("!"):
                    response_text = response_text.rstrip('.') + "!"
                
                response_text += "\n\n🎉 Perfect! All information collected. Your travel plan is being prepared now!"

            # Determine completion status
            if all_complete:
                completion_status = "all_complete"
                new_phase = "complete"
                response_text += "\n\n🎉 Perfect! All information collected. Your complete travel plan is ready!"
            elif mandatory_complete:
                completion_status = "mandatory_complete"
                new_phase = "optional"
            else:
                completion_status = "incomplete"
                new_phase = session["phase"]
            
            if mandatory_complete:
                print(f"\n{Fore.GREEN}{'=' * 80}")
                if all_complete:
                    print(f"🎉 ALL REQUIREMENTS COMPLETE FOR SESSION: {session_id}")
                else:
                    print(f"✅ MANDATORY REQUIREMENTS COMPLETE FOR SESSION: {session_id}")
                    print(f"📊 Optional fields: {optional_filled}/6 filled")
                print(f"🎯 Interests: {interests}")
                print(f"{'=' * 80}{Style.RESET_ALL}\n")

            
            # Persist updates
            self._update_session(
                session_id,
                user_input,
                response_text,
                requirements=updated_requirements,
                phase=new_phase,
                conversation_history=session["conversation_history"]  # ← ADD THIS LINE
            )
            
            final_result = {
                "response": response_text,
                "intent": "planning",
                "requirements_extracted": mandatory_complete,
                "requirements_data": updated_requirements,
                "completion_status": completion_status,
                "interests": interests,
                "optional_progress": f"{optional_filled}/6"  # NEW
            }
            return final_result
            
        except Exception as e:
            print(f"{Fore.RED}❌ ERROR IN PLANNING: {str(e)}{Style.RESET_ALL}")
            import traceback
            traceback.print_exc()
            # Fallback response
            session = self._get_session_data(session_id)
            fallback = "I'd be happy to help you plan your sustainable travel! Could you tell me where you'd like to go and when?"
            self._update_session(session_id, user_input, fallback, requirements=session["requirements"], phase=session.get("phase","initial"), conversation_history=session["conversation_history"])
            return {
                "response": fallback,
                "intent": "planning", 
                "requirements_extracted": False,
                "requirements_data": session["requirements"],
                "completion_status": "incomplete",  
                "interests": []                     
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
        
        # Persist the assistant response in the history as well
        self._update_session(session_id, user_input, response, requirements=session["requirements"], phase=session.get("phase","initial"), conversation_history=session["conversation_history"])
        
        return {
            "response": response,
            "intent": "other",
            "requirements_extracted": False,
            "requirements_data": session["requirements"],
            "completion_status": "incomplete",  
            "interests": []                    
        }

    def _check_completion(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Check if requirements collection is complete"""

        reqs = requirements.get("requirements", {})
        optional = reqs.get("optional", {})
        
        # Required fields check
        required_fields = {
            "destination_city": reqs.get("destination_city"),
            "start_date": reqs.get("trip_dates", {}).get("start_date"),
            "end_date": reqs.get("trip_dates", {}).get("end_date"),
            "adults": reqs.get("travelers", {}).get("adults"),
            "budget": reqs.get("budget_total_sgd"),
            "pace": reqs.get("pace")
        }
        
        mandatory_complete = all(v is not None and v != "" for v in required_fields.values())
        
        # Optional fields check
        optional_fields = {
            "eco_preferences": optional.get("eco_preferences"),
            "dietary_preferences": optional.get("dietary_preferences"),
            "interests": optional.get("interests"),
            "uninterests": optional.get("uninterests"),
            "accessibility_needs": optional.get("accessibility_needs"),
            "accommodation_location": optional.get("accommodation_location", {}),  # ← ADD THIS
            "group_type": optional.get("group_type")
        }

        # Count filled optional fields - be more strict
        optional_filled = 0
        if optional_fields["eco_preferences"]: optional_filled += 1
        if optional_fields["dietary_preferences"]: optional_filled += 1
        if optional_fields["interests"] and len(optional_fields["interests"]) > 0: optional_filled += 1
        if optional_fields["uninterests"] and len(optional_fields["uninterests"]) > 0: optional_filled += 1
        if optional_fields["accessibility_needs"]: optional_filled += 1
        # Check if accommodation_location has neighborhood filled
        if optional_fields["accommodation_location"] and optional_fields["accommodation_location"].get("neighborhood"): optional_filled += 1  # ← ADD THIS
        if optional_fields["group_type"]: optional_filled += 1

        all_complete = mandatory_complete and optional_filled == 7  # ← CHANGE TO 7
        
        return {
            "mandatory_complete": mandatory_complete,
            "all_complete": all_complete,
            "optional_filled": optional_filled,
            "optional_total": 7  # ← CHANGE TO 7
        }
    
# -------------------------------------------------
# FastAPI wiring
# -------------------------------------------------
app = FastAPI(title="Enhanced Travel Requirements Service", version="2.0.0")
service = IntentRequirementsService()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "enhanced-travel-requirements"}

@app.post("/classify-intent", response_model=IntentResponse)
async def classify_intent_endpoint(request: IntentRequest):
    """Classify user intent"""
    try:
        # Validate input
        if not request.user_input or not request.user_input.strip():
            raise HTTPException(status_code=400, detail="user_input cannot be empty")
        
        intent = await service.classify_intent(request.user_input)
        return IntentResponse(intent=intent)
    except HTTPException:
        raise  # Re-raise validation errors
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
    
# >>> alias endpoint compatible with gateway's fan-out in local/prod
@app.post("/intent/requirements")
async def intent_requirements_alias(request: RequirementsRequest):
    # Delegate to the same logic as /gather-requirements
    return await gather_requirements(request)

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    return service._get_session_data(session_id)

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Reset session memory to a clean slate (works for both in-memory and DynamoDB)."""
    # Write an empty memory record (effectively 'clears' it)
    empty_reqs = copy.deepcopy(service.target_json_template)
    put_memory(session_id, conversation_history=[], requirements=empty_reqs, phase="initial")
    return {"message": "Session cleared"}

@app.get("/")
async def root():
    return {
        "message": "Enhanced Travel Requirements Service",
        "version": "2.0.0",
        "intents": ["greeting", "planning", "other"],
        "features": [
            "Binary Intent Classification",
            "Intelligent Requirements Collection",
            "Enhanced Terminal Output",
            "Memory & Caching",
            "Edge Case Handling"
        ]
    }

# Lambda adapter supports both API Gateway proxy and direct Invoke
from mangum import Mangum
_mangum = Mangum(app)

def lambda_handler(event, context):
    """
    Supports:
    1) API Gateway/HttpApi proxy events (handled by Mangum)
    2) Direct lambda invokes (e.g., from ApiGatewayFn) with a simple shape:
       {"path": "/intent/requirements", "body": {...}}
    """
    # Direct invoke contract (used by ApiGatewayFn in LAMBDA mode)
    if isinstance(event, dict) and "path" in event:
        path = event.get("path", "")
        raw_body = event.get("body")
        if isinstance(raw_body, str):
            try:
                body = json.loads(raw_body)
            except Exception:
                body = {}
        else:
            body = raw_body or {}

        if path == "/intent/requirements":
            # Build a Pydantic request object and call the FastAPI handler
            req = RequirementsRequest(**body)
            # Use a TestClient to re-use FastAPI routing
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                resp = c.post("/intent/requirements", json=req.model_dump())
                # Return the parsed JSON (not the full APIGW proxy object)
                return resp.json()

        if path == "/classify-intent":
            req = IntentRequest(**body)
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                resp = c.post("/classify-intent", json=req.model_dump())
                return resp.json()

    # Fallback to API Gateway/HttpApi proxy handling
    return _mangum(event, context)


# Local dev entrypoint
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)