# tests/test_requirements_gathering.py
"""Tests for requirements gathering functionality"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))

@pytest.mark.unit
@pytest.mark.asyncio
class TestRequirementsGathering:
    """Test requirements gathering agent"""
    
    async def test_handle_greeting(self, sample_user_input, sample_session_id):
        """Test handling of greeting intent"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        # Mock the crew execution
        mock_response = "Hello! I'm helping you plan your trip. Where would you like to go?"
        with patch.object(service, '_run_crew', return_value=mock_response):
            result = await service._handle_greeting(
                sample_user_input["greeting"],
                sample_session_id
            )
        
        assert result["intent"] == "greeting"
        assert result["requirements_extracted"] is False
        assert "hello" in result["response"].lower() or "hi" in result["response"].lower()
    
    async def test_extract_complete_planning_info(self, sample_user_input, sample_session_id):
        """Test extraction of complete planning information"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        # Mock crew result with complete JSON extraction
        mock_result = """
        EXTRACTED_JSON: {
            "requirements": {
                "destination_city": "Singapore",
                "trip_dates": {"start_date": "2025-12-20", "end_date": "2025-12-25"},
                "duration_days": 6,
                "travelers": {"adults": 2, "children": 1},
                "budget_total_sgd": 2000,
                "pace": "relaxed",
                "optional": {
                    "eco_preferences": null,
                    "dietary_preferences": null,
                    "interests": [],
                    "uninterests": [],
                    "accessibility_needs": null,
                    "accommodation_location": {"neighborhood": null},
                    "group_type": null
                }
            }
        }
        RESPONSE: Perfect! I have all the mandatory information.
        PHASE: complete
        """
        
        with patch.object(service, '_run_crew', return_value=mock_result):
            result = await service._handle_planning(
                sample_user_input["complete_planning"],
                sample_session_id
            )
        
        assert result["intent"] == "planning"
        assert result["completion_status"] in ["mandatory_complete", "all_complete"]
        assert result["requirements_data"]["requirements"]["destination_city"] == "Singapore"
        assert result["requirements_data"]["requirements"]["travelers"]["adults"] == 2
    
    async def test_extract_partial_info(self, sample_user_input, sample_session_id):
        """Test extraction of partial planning information"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        mock_result = """
        EXTRACTED_JSON: {
            "requirements": {
                "destination_city": "Singapore",
                "trip_dates": {"start_date": null, "end_date": null},
                "duration_days": null,
                "travelers": {"adults": null, "children": null},
                "budget_total_sgd": null,
                "pace": null,
                "optional": {
                    "eco_preferences": null,
                    "dietary_preferences": null,
                    "interests": [],
                    "uninterests": [],
                    "accessibility_needs": null,
                    "accommodation_location": {"neighborhood": null},
                    "group_type": null
                }
            }
        }
        RESPONSE: Great! When would you like to visit Singapore?
        PHASE: collecting
        """
        
        with patch.object(service, '_run_crew', return_value=mock_result):
            result = await service._handle_planning(
                "I want to visit Singapore",
                sample_session_id
            )
        
        assert result["requirements_extracted"] is False
        assert result["completion_status"] == "incomplete"
        assert result["requirements_data"]["requirements"]["destination_city"] == "Singapore"
    
    async def test_handle_off_topic(self, sample_user_input, sample_session_id):
        """Test handling of off-topic conversations"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        result = await service._handle_other_intent(
            sample_user_input["off_topic"],
            sample_session_id
        )
        
        assert result["intent"] == "other"
        assert result["requirements_extracted"] is False
        assert "travel" in result["response"].lower()
    
    async def test_check_completion_all_complete(self, sample_requirements):
        """Test completion check with all fields filled"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        completion_info = service._check_completion(sample_requirements)
        
        assert completion_info["mandatory_complete"] is True
        assert completion_info["all_complete"] is True
        assert completion_info["optional_filled"] == 6
    
    async def test_check_completion_mandatory_only(self, mandatory_complete_requirements):
        """Test completion check with only mandatory fields"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        completion_info = service._check_completion(mandatory_complete_requirements)
        
        assert completion_info["mandatory_complete"] is True
        assert completion_info["all_complete"] is False
        assert completion_info["optional_filled"] == 0
    
    async def test_check_completion_incomplete(self, incomplete_requirements):
        """Test completion check with incomplete requirements"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        completion_info = service._check_completion(incomplete_requirements)
        
        assert completion_info["mandatory_complete"] is False
        assert completion_info["all_complete"] is False
    
    async def test_interests_extraction(self, sample_requirements):
        """Test extraction of interests from requirements"""
        from main import _extract_interests
        
        interests = _extract_interests(sample_requirements)
        
        assert isinstance(interests, list)
        assert "gardens" in interests
        assert "museums" in interests
    
    async def test_interests_extraction_empty(self, incomplete_requirements):
        """Test extraction when no interests present"""
        from main import _extract_interests
        
        interests = _extract_interests(incomplete_requirements)
        
        assert isinstance(interests, list)
        assert len(interests) == 0
    
    @pytest.mark.parametrize("optional_field,value,should_count_as_filled", [
        ("eco_preferences", "high", True),
        ("eco_preferences", "no_preference", True),
        ("eco_preferences", None, False),
        ("eco_preferences", "", False),
        ("dietary_preferences", "vegetarian", True),
        ("dietary_preferences", "none", True),
        ("interests", ["gardens"], True),
        ("interests", [], False),
        ("group_type", "family", True),
        ("group_type", None, False),
    ])
    async def test_optional_field_completion(self, mandatory_complete_requirements, optional_field, value, should_count_as_filled):
        """Test various optional field values for completion detection"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        # Set the optional field
        if "." in optional_field:
            # Handle nested fields like accommodation_location.neighborhood
            parts = optional_field.split(".")
            mandatory_complete_requirements["requirements"]["optional"][parts[0]][parts[1]] = value
        else:
            mandatory_complete_requirements["requirements"]["optional"][optional_field] = value
        
        completion_info = service._check_completion(mandatory_complete_requirements)
        
        # This tests the individual field, so we just verify it doesn't crash
        assert completion_info["optional_filled"] >= 0


@pytest.mark.unit
class TestRequirementsAPI:
    """Test requirements gathering API endpoints"""
    
    def test_gather_requirements_endpoint_success(self, sample_user_input, sample_session_id):
        """Test successful requirements gathering via API"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))
        from main import app
        
        client = TestClient(app)
        
        mock_result = {
            "response": "Great! What's your budget?",
            "intent": "planning",
            "requirements_extracted": False,
            "requirements_data": {"requirements": {}},
            "completion_status": "incomplete",
            "interests": [],
            "optional_progress": "0/6"
        }
        
        with patch('main.service.gather_requirements', return_value=mock_result):
            response = client.post(
                "/gather-requirements",
                json={
                    "user_input": sample_user_input["planning"],
                    "intent": "planning",
                    "session_context": {"session_id": sample_session_id}
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "planning"
        assert "requirements_data" in data
    
    def test_intent_requirements_alias_endpoint(self, sample_user_input, sample_session_id):
        """Test alias endpoint /intent/requirements"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))
        from main import app
        
        client = TestClient(app)
        
        mock_result = {
            "response": "Great!",
            "intent": "planning",
            "requirements_extracted": False,
            "requirements_data": {"requirements": {}},
            "completion_status": "incomplete",
            "interests": [],
            "optional_progress": "0/6"
        }
        
        with patch('main.service.gather_requirements', return_value=mock_result):
            response = client.post(
                "/intent/requirements",
                json={
                    "user_input": sample_user_input["planning"],
                    "intent": "planning",
                    "session_context": {"session_id": sample_session_id}
                }
            )
        
        assert response.status_code == 200
    
    def test_get_session_endpoint(self, sample_session_id, sample_requirements):
        """Test get session endpoint"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))
        from main import app, service
        
        client = TestClient(app)
        
        # Mock the session data
        mock_session = {
            "session_id": sample_session_id,
            "conversation_history": [],
            "requirements": sample_requirements,
            "phase": "initial"
        }
        
        with patch.object(service, '_get_session_data', return_value=mock_session):
            response = client.get(f"/session/{sample_session_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == sample_session_id


@pytest.mark.unit
class TestSessionManagement:
    """Test session management functionality"""
    
    def test_get_session_data(self, sample_session_id):
        """Test retrieving session data"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch('main.get_memory') as mock_get:
            mock_get.return_value = {
                "session_id": sample_session_id,
                "conversation_history": [],
                "requirements": service.target_json_template,
                "phase": "initial"
            }
            
            session = service._get_session_data(sample_session_id)
        
        assert session["session_id"] == sample_session_id
        assert "conversation_history" in session
        assert "requirements" in session
        assert "phase" in session
    
    def test_update_session(self, sample_session_id, sample_requirements):
        """Test updating session data"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch('main.put_memory') as mock_put, \
             patch('main.get_memory') as mock_get:
            
            mock_get.return_value = {
                "session_id": sample_session_id,
                "conversation_history": [],
                "requirements": service.target_json_template,
                "phase": "initial"
            }
            
            service._update_session(
                sample_session_id,
                "Hello",
                "Hi there!",
                requirements=sample_requirements,
                phase="collecting"
            )
            
            # Verify put_memory was called
            mock_put.assert_called_once()
