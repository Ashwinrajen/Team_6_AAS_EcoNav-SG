# tests/test_api_gateway.py
"""Tests for API Gateway functionality"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api-gateway'))

@pytest.mark.unit
@pytest.mark.asyncio
class TestTravelGateway:
    """Test Travel Gateway orchestration"""
    
    async def test_process_input_new_session(self, sample_user_input):
        """Test processing input with new session creation"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main.create_session', return_value={"session_id": "new-123"}), \
             patch('main.validate_input', return_value={"is_safe": True}), \
             patch('main.classify_intent', return_value={"intent": "planning"}), \
             patch('main.gather_requirements', return_value={
                 "response": "Great! Where would you like to go?",
                 "requirements_extracted": False,
                 "completion_status": "incomplete",
                 "requirements_data": {},
                 "interests": [],
                 "optional_progress": "0/6"
             }), \
             patch('main.validate_output', return_value={"is_safe": True}), \
             patch('main.update_session', return_value={}):
            
            result = await gateway.process_input(sample_user_input["planning"])
        
        assert result["success"] is True
        assert result["session_id"] == "new-123"
        assert result["intent"] == "planning"
    
    async def test_process_input_existing_session(self, sample_user_input, sample_session_id):
        """Test processing input with existing session"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main.validate_input', return_value={"is_safe": True}), \
             patch('main.classify_intent', return_value={"intent": "planning"}), \
             patch('main.gather_requirements', return_value={
                 "response": "Got it!",
                 "requirements_extracted": False,
                 "completion_status": "incomplete",
                 "requirements_data": {},
                 "interests": [],
                 "optional_progress": "0/6"
             }), \
             patch('main.validate_output', return_value={"is_safe": True}), \
             patch('main.update_session', return_value={}):
            
            result = await gateway.process_input(
                sample_user_input["planning"],
                session_id=sample_session_id
            )
        
        assert result["session_id"] == sample_session_id
    
    async def test_process_input_blocked(self, sample_user_input):
        """Test processing with blocked input"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main.create_session', return_value={"session_id": "test-123"}), \
             patch('main.validate_input', return_value={"is_safe": False, "blocked_reason": "injection"}):
            
            result = await gateway.process_input(sample_user_input["malicious"])
        
        assert result["success"] is False
        assert result["conversation_state"] == "input_blocked"
    
    async def test_process_input_complete_requirements(self, sample_user_input, sample_session_id, sample_requirements):
        """Test processing when requirements are complete"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main.validate_input', return_value={"is_safe": True}), \
             patch('main.classify_intent', return_value={"intent": "planning"}), \
             patch('main.gather_requirements', return_value={
                 "response": "Perfect! All information collected.",
                 "requirements_extracted": True,
                 "completion_status": "all_complete",
                 "requirements_data": sample_requirements,
                 "interests": ["gardens", "museums"],
                 "optional_progress": "6/6"
             }), \
             patch('main.validate_output', return_value={"is_safe": True}), \
             patch('main.update_session', return_value={}), \
             patch('main._store_final_json_in_s3', return_value="final/test.json"), \
             patch('main._get_session_from_s3', return_value={
                 "conversation_history": [
                     {"role": "user", "message": "I want to visit Singapore"}
                 ]
             }), \
             patch('main._call_planning_agent', return_value={"status": "success"}):
            
            result = await gateway.process_input(
                sample_user_input["complete_planning"],
                session_id=sample_session_id
            )
        
        assert result["collection_complete"] is True
        assert result["final_json_s3_key"] is not None
        assert result["planning_agent_status"] == "success"
    
    async def test_error_handling(self, sample_user_input):
        """Test error handling in gateway"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main.create_session', side_effect=Exception("Connection error")):
            result = await gateway.process_input(sample_user_input["planning"])
        
        assert result["success"] is False
        assert "error" in result


@pytest.mark.unit
class TestAPIGatewayEndpoints:
    """Test API Gateway endpoints"""
    
    def test_health_endpoint(self):
        """Test health check endpoint"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api-gateway'))
        from main import app
        
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "mode" in data
    
    def test_root_endpoint(self):
        """Test root endpoint"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api-gateway'))
        from main import app
        
        client = TestClient(app)
        
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "features" in data
        assert "routes" in data
    
    def test_plan_travel_endpoint(self, sample_user_input):
        """Test /travel/plan endpoint"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api-gateway'))
        from main import app, gateway
        
        client = TestClient(app)
        
        mock_result = {
            "success": True,
            "response": "Great! Where would you like to go?",
            "session_id": "test-123",
            "intent": "planning",
            "conversation_state": "collecting_requirements",
            "trust_score": 1.0,
            "collection_complete": False
        }
        
        with patch.object(gateway, 'process_input', return_value=mock_result):
            response = client.post(
                "/travel/plan",
                json={
                    "user_input": sample_user_input["planning"],
                    "session_id": None
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "response" in data
        assert "session_id" in data
    
    def test_get_session_info_endpoint(self, sample_session_id):
        """Test /travel/session/{session_id} endpoint"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api-gateway'))
        from main import app
        
        client = TestClient(app)
        
        mock_session = {
            "session_id": sample_session_id,
            "trust_score": 1.0,
            "conversation_state": "collecting_requirements"
        }
        
        with patch('main.get_session', return_value=mock_session):
            response = client.get(f"/travel/session/{sample_session_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == sample_session_id


@pytest.mark.unit
class TestServiceClient:
    """Test service client for downstream calls"""
    
    def test_classify_intent_http_mode(self, sample_user_input):
        """Test intent classification via HTTP"""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))
        from service_client import classify_intent
        
        with patch.dict(os.environ, {"DOWNSTREAM_MODE": "HTTP"}), \
             patch('service_client._session.post') as mock_post:
            
            mock_response = Mock()
            mock_response.json.return_value = {"intent": "planning"}
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response
            
            result = classify_intent({"user_input": sample_user_input["planning"]})
            
            assert result["intent"] == "planning"
    
    def test_gather_requirements_http_mode(self, sample_user_input):
        """Test requirements gathering via HTTP"""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))
        from service_client import gather_requirements
        
        with patch.dict(os.environ, {"DOWNSTREAM_MODE": "HTTP"}), \
             patch('service_client._session.post') as mock_post:
            
            mock_response = Mock()
            mock_response.json.return_value = {
                "response": "Great!",
                "requirements_extracted": False,
                "completion_status": "incomplete",
                "interests": []
            }
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response
            
            result = gather_requirements({
                "user_input": sample_user_input["planning"],
                "intent": "planning"
            })
            
            assert "response" in result
    
    def test_service_client_error_handling(self, sample_user_input):
        """Test service client error handling"""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))
        from service_client import classify_intent
        
        with patch.dict(os.environ, {"DOWNSTREAM_MODE": "HTTP"}), \
             patch('service_client._session.post', side_effect=Exception("Connection error")):
            
            result = classify_intent({"user_input": sample_user_input["planning"]})
            
            assert result["success"] is False
            assert "error" in result


@pytest.mark.unit
class TestFinalJSONGeneration:
    """Test final JSON generation for downstream agents"""
    
    def test_build_final_json_complete(self, sample_session_id, sample_requirements):
        """Test building final JSON with complete requirements"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main._get_session_from_s3', return_value={
            "conversation_history": [
                {"role": "user", "message": "I want to visit Singapore"},
                {"role": "agent", "message": "Great!"}
            ]
        }):
            final_json = gateway._build_final_json(
                session_id=sample_session_id,
                requirements_data=sample_requirements,
                interests=["gardens", "museums"],
                status_code=200
            )
        
        assert final_json["status_code"] == 200
        assert final_json["session_id"] == sample_session_id
        assert "interest" in final_json
        assert "message" in final_json
        assert "requirements" in final_json
        assert len(final_json["interest"]) == 2
    
    def test_build_final_json_with_error(self, sample_session_id):
        """Test building final JSON when error occurs"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        with patch('main._get_session_from_s3', side_effect=Exception("S3 error")):
            final_json = gateway._build_final_json(
                session_id=sample_session_id,
                requirements_data={},
                interests=[],
                status_code=500
            )
        
        assert final_json["status_code"] == 500
        assert "error" in final_json


@pytest.mark.integration
@pytest.mark.asyncio
class TestEndToEndFlow:
    """Test end-to-end conversation flow"""
    
    async def test_complete_conversation_flow(self):
        """Test complete conversation from greeting to requirements complete"""
        from main import TravelGateway
        
        gateway = TravelGateway()
        
        # Mock all downstream services
        with patch('main.create_session', return_value={"session_id": "e2e-123"}), \
             patch('main.validate_input', return_value={"is_safe": True}), \
             patch('main.validate_output', return_value={"is_safe": True}), \
             patch('main.update_session', return_value={}):
            
            # Step 1: Greeting
            with patch('main.classify_intent', return_value={"intent": "greeting"}), \
                 patch('main.gather_requirements', return_value={
                     "response": "Hello! Where would you like to go?",
                     "requirements_extracted": False,
                     "completion_status": "incomplete",
                     "requirements_data": {},
                     "interests": [],
                     "optional_progress": "0/6"
                 }):
                
                result1 = await gateway.process_input("Hello!")
                assert result1["intent"] == "greeting"
                session_id = result1["session_id"]
            
            # Step 2: Provide destination
            with patch('main.classify_intent', return_value={"intent": "planning"}), \
                 patch('main.gather_requirements', return_value={
                     "response": "When would you like to go?",
                     "requirements_extracted": False,
                     "completion_status": "incomplete",
                     "requirements_data": {"requirements": {"destination_city": "Singapore"}},
                     "interests": [],
                     "optional_progress": "0/6"
                 }):
                
                result2 = await gateway.process_input("I want to visit Singapore", session_id)
                assert result2["session_id"] == session_id
            
            # Step 3: Complete information
            with patch('main.classify_intent', return_value={"intent": "planning"}), \
                 patch('main.gather_requirements', return_value={
                     "response": "Perfect! All collected.",
                     "requirements_extracted": True,
                     "completion_status": "all_complete",
                     "requirements_data": {"requirements": {}},
                     "interests": ["gardens"],
                     "optional_progress": "6/6"
                 }), \
                 patch('main._store_final_json_in_s3', return_value="final/test.json"), \
                 patch('main._get_session_from_s3', return_value={"conversation_history": []}), \
                 patch('main._call_planning_agent', return_value={"status": "success"}):
                
                result3 = await gateway.process_input(
                    "December 20-25, 2 adults 1 child, 2000 SGD, relaxed",
                    session_id
                )
                assert result3["collection_complete"] is True
                assert result3["final_json_s3_key"] is not None
