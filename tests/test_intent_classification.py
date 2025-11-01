# tests/test_intent_classification.py
"""Tests for intent classification functionality"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))

@pytest.mark.unit
@pytest.mark.asyncio
class TestIntentClassification:
    """Test intent classification agent"""
    
    @pytest.fixture
    def mock_crew_result(self):
        """Mock CrewAI crew kickoff result"""
        async def mock_kickoff():
            return "planning"
        return mock_kickoff
    
    async def test_greeting_classification(self, sample_user_input, mock_crew_result):
        """Test classification of greeting inputs"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch.object(service, '_run_crew', return_value="greeting"):
            result = await service.classify_intent(sample_user_input["greeting"])
            assert result == "greeting"
    
    async def test_planning_classification(self, sample_user_input, mock_crew_result):
        """Test classification of planning inputs"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch.object(service, '_run_crew', return_value="planning"):
            result = await service.classify_intent(sample_user_input["planning"])
            assert result == "planning"
    
    async def test_other_classification(self, sample_user_input, mock_crew_result):
        """Test classification of off-topic inputs"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch.object(service, '_run_crew', return_value="other"):
            result = await service.classify_intent(sample_user_input["off_topic"])
            assert result == "other"
    
    async def test_fallback_classification_greeting(self, sample_user_input):
        """Test fallback classification when LLM fails - greeting"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        # Mock crew to raise exception, forcing fallback
        with patch.object(service, '_run_crew', side_effect=Exception("LLM timeout")):
            result = await service.classify_intent("hello there")
            assert result == "greeting"
    
    async def test_fallback_classification_planning(self, sample_user_input):
        """Test fallback classification when LLM fails - planning"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch.object(service, '_run_crew', side_effect=Exception("LLM timeout")):
            result = await service.classify_intent("I want to travel to Paris")
            assert result == "planning"
    
    async def test_fallback_classification_other(self, sample_user_input):
        """Test fallback classification when LLM fails - other"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch.object(service, '_run_crew', side_effect=Exception("LLM timeout")):
            result = await service.classify_intent("what's the weather?")
            assert result == "other"
    
    @pytest.mark.parametrize("user_input,expected_intent", [
        ("Hello!", "greeting"),
        ("Hi there", "greeting"),
        ("Good morning", "greeting"),
        ("I want to visit Tokyo", "planning"),
        ("Plan a trip to London", "planning"),
        ("Book a vacation", "planning"),
        ("2 adults and 1 child", "planning"),
        ("My budget is 2000 SGD", "planning"),
        ("From December 20 to 25", "planning"),
        ("I prefer vegetarian food", "planning"),
        ("What's AI?", "other"),
        ("Tell me a joke", "other"),
    ])
    async def test_various_inputs(self, user_input, expected_intent):
        """Test various input patterns"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        with patch.object(service, '_run_crew', return_value=expected_intent):
            result = await service.classify_intent(user_input)
            assert result == expected_intent
    
    async def test_empty_input_handling(self):
        """Test handling of empty input"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        # Empty strings should be handled gracefully
        with patch.object(service, '_run_crew', return_value="other"):
            result = await service.classify_intent("")
            assert result in ["greeting", "planning", "other"]
    
    async def test_long_input_handling(self):
        """Test handling of very long inputs"""
        from main import IntentRequirementsService
        
        service = IntentRequirementsService()
        
        long_input = "I want to visit Singapore " * 100  # Very long input
        
        with patch.object(service, '_run_crew', return_value="planning"):
            result = await service.classify_intent(long_input)
            assert result == "planning"


@pytest.mark.unit
class TestIntentAPI:
    """Test intent classification API endpoints"""
    
    def test_classify_intent_endpoint_success(self, sample_user_input):
        """Test successful intent classification via API"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))
        from main import app
        
        client = TestClient(app)
        
        with patch('main.service.classify_intent', return_value="planning"):
            response = client.post(
                "/classify-intent",
                json={
                    "user_input": sample_user_input["planning"],
                    "session_context": {"session_id": "test-123"}
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "planning"
    
    def test_classify_intent_endpoint_empty_input(self):
        """Test API with empty input"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))
        from main import app
        
        client = TestClient(app)
        
        response = client.post(
            "/classify-intent",
            json={"user_input": "", "session_context": {}}
        )
        
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
    
    def test_classify_intent_endpoint_missing_field(self):
        """Test API with missing required field"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'intent-requirements-service'))
        from main import app
        
        client = TestClient(app)
        
        response = client.post(
            "/classify-intent",
            json={"session_context": {}}  # Missing user_input
        )
        
        assert response.status_code == 422  # Validation error
