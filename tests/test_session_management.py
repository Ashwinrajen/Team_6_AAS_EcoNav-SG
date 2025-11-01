# tests/test_session_management.py
"""Tests for session management functionality"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from datetime import datetime
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))

@pytest.mark.unit
class TestSessionManagement:
    """Test session management"""
    
    def test_create_session(self, sample_session_id):
        """Test session creation"""
        from main import SessionManager
        
        with patch('main.store_get', return_value=None), \
             patch('main.store_put') as mock_put:
            
            session = SessionManager.ensure_session(user_id="test-user")
            
            assert session["session_id"] is not None
            assert session["user_id"] == "test-user"
            assert session["trust_score"] == 1.0
            assert session["conversation_state"] == "greeting"
            mock_put.assert_called_once()
    
    def test_get_existing_session(self, sample_session_data):
        """Test retrieving existing session"""
        from main import SessionManager
        
        with patch('main.store_get', return_value=sample_session_data):
            session = SessionManager.ensure_session(session_id=sample_session_data["session_id"])
            
            assert session["session_id"] == sample_session_data["session_id"]
            assert session["trust_score"] == sample_session_data["trust_score"]
    
    def test_update_session(self, sample_session_id, sample_session_data):
        """Test session update"""
        from main import SessionManager
        
        updates = {
            "trust_score": 0.95,
            "conversation_state": "collecting_requirements"
        }
        
        with patch('main.store_get', return_value=sample_session_data), \
             patch('main.store_update') as mock_update:
            
            session = SessionManager.ensure_session(
                session_id=sample_session_id,
                updates=updates
            )
            
            assert session["trust_score"] == 0.95
            assert session["conversation_state"] == "collecting_requirements"
            mock_update.assert_called_once()
    
    def test_session_auto_id_generation(self):
        """Test automatic session ID generation"""
        from main import SessionManager
        
        with patch('main.store_get', return_value=None), \
             patch('main.store_put'):
            
            session1 = SessionManager.ensure_session()
            session2 = SessionManager.ensure_session()
            
            assert session1["session_id"] != session2["session_id"]
            assert len(session1["session_id"]) == 8


@pytest.mark.unit
class TestSessionAPI:
    """Test session API endpoints"""
    
    def test_create_session_endpoint(self):
        """Test session creation via API"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))
        from main import app
        
        client = TestClient(app)
        
        response = client.post(
            "/session/create",
            json={"user_id": "test-user"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "trust_score" in data
        assert data["trust_score"] == 1.0
    
    def test_get_session_endpoint(self, sample_session_id, sample_session_data):
        """Test get session via API"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))
        from main import app, SessionManager
        
        client = TestClient(app)
        
        with patch.object(SessionManager, 'ensure_session', return_value=sample_session_data):
            response = client.get(f"/session/{sample_session_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == sample_session_id
        assert "trust_score" in data
        assert "conversation_state" in data
    
    def test_update_session_endpoint(self, sample_session_id):
        """Test update session via API"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))
        from main import app, SessionManager
        
        client = TestClient(app)
        
        updates = {"conversation_state": "requirements_complete"}
        
        with patch.object(SessionManager, 'ensure_session', return_value={"session_id": sample_session_id}):
            response = client.put(
                f"/session/{sample_session_id}",
                json=updates
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Session updated successfully"
    
    def test_delete_session_endpoint(self, sample_session_id):
        """Test delete session via API"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))
        from main import app
        
        client = TestClient(app)
        
        with patch('main.store_get', return_value={"session_id": sample_session_id}), \
             patch('main.store_delete'):
            response = client.delete(f"/session/{sample_session_id}")
        
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
    
    def test_delete_nonexistent_session(self):
        """Test deletion of non-existent session"""
        from fastapi.testclient import TestClient
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))
        from main import app
        
        client = TestClient(app)
        
        with patch('main.store_get', return_value=None):
            response = client.delete("/session/nonexistent")
        
        assert response.status_code == 404


@pytest.mark.unit
class TestS3Storage:
    """Test S3 storage operations"""
    
    def test_put_session_s3(self, sample_session_data):
        """Test storing session in S3"""
        from s3_store import put_session
        import s3_store
        
        # Temporarily enable S3 for this test
        original_use_s3 = s3_store.USE_S3
        s3_store.USE_S3 = True
        
        try:
            with patch('s3_store._s3.put_object') as mock_put:
                put_session(sample_session_data)
                mock_put.assert_called_once()
        finally:
            s3_store.USE_S3 = original_use_s3
    
    def test_get_session_s3(self, sample_session_id, sample_session_data):
        """Test retrieving session from S3"""
        from s3_store import get_session
        import s3_store
        
        # Temporarily enable S3 for this test
        original_use_s3 = s3_store.USE_S3
        s3_store.USE_S3 = True
        
        try:
            mock_response = {
                "Body": Mock(read=Mock(return_value=json.dumps(sample_session_data).encode()))
            }
            
            with patch('s3_store._s3.get_object', return_value=mock_response):
                session = get_session(sample_session_id)
                
                assert session["session_id"] == sample_session_id
                assert session["conversation_state"] == "collecting_requirements"
        finally:
            s3_store.USE_S3 = original_use_s3
    
    def test_get_nonexistent_session_s3(self, sample_session_id):
        """Test retrieving non-existent session from S3"""
        from s3_store import get_session
        from botocore.exceptions import ClientError
        import s3_store
        
        # Temporarily enable S3 for this test
        original_use_s3 = s3_store.USE_S3
        s3_store.USE_S3 = True
        
        try:
            error = ClientError(
                {"Error": {"Code": "NoSuchKey"}},
                "GetObject"
            )
            
            with patch('s3_store._s3.get_object', side_effect=error):
                session = get_session(sample_session_id)
                assert session is None
        finally:
            s3_store.USE_S3 = original_use_s3
    
    def test_update_session_s3(self, sample_session_id, sample_session_data):
        """Test updating session in S3"""
        from s3_store import update_session
        import s3_store
        
        # Temporarily enable S3 for this test
        original_use_s3 = s3_store.USE_S3
        s3_store.USE_S3 = True
        
        try:
            mock_response = {
                "Body": Mock(read=Mock(return_value=json.dumps(sample_session_data).encode()))
            }
            
            with patch('s3_store._s3.get_object', return_value=mock_response), \
                 patch('s3_store._s3.put_object') as mock_put:
                
                updates = {"trust_score": 0.95}
                update_session(sample_session_id, updates)
                
                mock_put.assert_called_once()
        finally:
            s3_store.USE_S3 = original_use_s3
    
    def test_delete_session_s3(self, sample_session_id):
        """Test deleting session from S3"""
        from s3_store import delete_session
        import s3_store
        
        # Temporarily enable S3 for this test
        original_use_s3 = s3_store.USE_S3
        s3_store.USE_S3 = True
        
        try:
            with patch('s3_store._s3.delete_object') as mock_delete:
                delete_session(sample_session_id)
                mock_delete.assert_called_once()
        finally:
            s3_store.USE_S3 = original_use_s3


@pytest.mark.unit
class TestMemoryStore:
    """Test memory store operations"""
    
    def test_get_memory(self, sample_session_id, sample_requirements):
        """Test retrieving memory from store"""
        from memory_store import get_memory
        
        mock_data = {
            "session_id": sample_session_id,
            "conversation_history": [],
            "requirements": sample_requirements,
            "phase": "initial",
            "last_updated": datetime.now().isoformat()
        }
        
        mock_response = {
            "Body": Mock(read=Mock(return_value=json.dumps(mock_data).encode()))
        }
        
        with patch('memory_store._s3.get_object', return_value=mock_response):
            memory = get_memory(sample_session_id)
            
            assert memory["session_id"] == sample_session_id
            assert "conversation_history" in memory
            assert "requirements" in memory
    
    def test_get_memory_not_found(self, sample_session_id):
        """Test retrieving non-existent memory (returns default)"""
        from memory_store import get_memory
        from botocore.exceptions import ClientError
        
        error = ClientError(
            {"Error": {"Code": "NoSuchKey"}},
            "GetObject"
        )
        
        with patch('memory_store._s3.get_object', side_effect=error):
            memory = get_memory(sample_session_id)
            
            # Should return default structure
            assert memory["session_id"] == sample_session_id
            assert memory["conversation_history"] == []
            assert memory["phase"] == "initial"
    
    def test_put_memory(self, sample_session_id, sample_requirements, sample_conversation_history):
        """Test storing memory"""
        from memory_store import put_memory
        import memory_store
        
        # Temporarily enable S3 for this test
        original_use_s3 = memory_store.USE_S3
        memory_store.USE_S3 = True
        
        try:
            with patch('memory_store._s3.put_object') as mock_put:
                put_memory(
                    sample_session_id,
                    sample_conversation_history,
                    sample_requirements,
                    "collecting"
                )
                
                mock_put.assert_called_once()
        finally:
            memory_store.USE_S3 = original_use_s3


@pytest.mark.unit
class TestTransparency:
    """Test transparency and trust scoring"""
    
    def test_calculate_trust_score(self, sample_trust_score_request):
        """Test trust score calculation"""
        from transparency import TransparencyEngine
        
        engine = TransparencyEngine()
        
        result = engine.calculate_trust_score(
            sample_trust_score_request["session_data"],
            sample_trust_score_request["user_context"]
        )
        
        assert "trust_score" in result
        assert "trust_level" in result
        assert "factors" in result
        assert 0 <= result["trust_score"] <= 1
    
    def test_explain_decision(self):
        """Test decision explanation generation"""
        from transparency import TransparencyEngine
        
        engine = TransparencyEngine()
        
        reasoning_data = {
            "intent": "planning",
            "extracted_info": {
                "destination": "Singapore",
                "dates": "Dec 20-25",
                "budget": "2000 SGD"
            }
        }
        
        explanation = engine.explain_decision("decision-123", reasoning_data)
        
        assert isinstance(explanation, str)
        assert len(explanation) > 0
        assert "singapore" in explanation.lower() or "planning" in explanation.lower()
    
    def test_get_transparency_report(self, sample_session_id):
        """Test transparency report generation"""
        from transparency import TransparencyEngine
        
        engine = TransparencyEngine()
        
        report = engine.get_transparency_report(sample_session_id)
        
        assert report["session_id"] == sample_session_id
        assert "transparency_metrics" in report
        assert "available_data" in report
