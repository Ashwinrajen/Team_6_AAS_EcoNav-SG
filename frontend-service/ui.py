# frontend-service/ui.py

import streamlit as st
import httpx
import asyncio
from typing import Dict, Any, Optional
import time

# Configuration
API_GATEWAY_URL = "http://localhost:8000"

class TravelGatewayClient:
    """Simplified client for travel gateway API"""
    
    def __init__(self):
        self.gateway_url = API_GATEWAY_URL
    
    def process_input(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Process input via API Gateway"""
        return asyncio.run(self._process_input_async(user_input, session_id))
    
    async def _process_input_async(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Async implementation"""
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.gateway_url}/travel/plan",
                    json={"user_input": user_input, "session_id": session_id}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                return self._create_error_response(str(e), session_id)
    
    def get_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get session information"""
        return asyncio.run(self._get_session_info_async(session_id))
    
    async def _get_session_info_async(self, session_id: str) -> Dict[str, Any]:
        """Async session info retrieval"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(f"{self.gateway_url}/travel/session/{session_id}")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return {"error": "Session not found", "trust_score": 1.0, "conversation_state": "unknown"}
    
    def _create_error_response(self, error: str, session_id: str = None) -> Dict[str, Any]:
        """Create standardized error response"""
        return {
            "success": False,
            "response": f"Connection error: {error}. Please check if services are running.",
            "session_id": session_id or "unknown",
            "intent": "error",
            "conversation_state": "error",
            "trust_score": 0.0
        }

def initialize_session():
    """Initialize session state with defaults"""
    if "gateway_client" not in st.session_state:
        st.session_state.gateway_client = TravelGatewayClient()
    
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    
    if "messages" not in st.session_state:
        st.session_state.messages = []

def display_sidebar():
    """Display sidebar with session info and controls"""
    with st.sidebar:
        st.header("Session Info")
        
        # Session metrics
        if st.session_state.session_id:
            info = st.session_state.gateway_client.get_session_info(st.session_state.session_id)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Messages", len(st.session_state.messages) // 2)
            with col2:
                trust_score = info.get("trust_score", 1.0)
                st.metric("Trust Score", f"{trust_score:.2f}")
            
            # Conversation state
            state = info.get("conversation_state", "unknown")
            st.info(f"State: {state.replace('_', ' ').title()}")
        else:
            st.info("No active session")
        
        st.divider()
        
        # Control buttons
        if st.button("New Session", use_container_width=True):
            st.session_state.session_id = None
            st.session_state.messages = []
            st.rerun()
        
        if st.button("Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

def display_chat_interface():
    """Main chat interface"""
    st.subheader("Chat with Travel Assistant")
    
    # Display message history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            
            # Show metadata for assistant messages
            if message["role"] == "assistant" and "metadata" in message:
                metadata = message["metadata"]
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    if metadata.get("intent"):
                        st.caption(f"Intent: {metadata['intent']}")
                
                with col2:
                    if metadata.get("trust_score"):
                        st.caption(f"Trust: {metadata['trust_score']:.2f}")

def process_user_input(user_input: str):
    """Process user input and update chat"""
    # Add user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # Show user message
    with st.chat_message("user"):
        st.write(user_input)
    
    # Process with assistant
    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            result = st.session_state.gateway_client.process_input(
                user_input, st.session_state.session_id
            )
        
        # Update session ID if created
        if not st.session_state.session_id and result.get("session_id"):
            st.session_state.session_id = result["session_id"]
        
        # Display response
        response_text = result.get("response", "No response received")
        st.write(response_text)
        
        # Add to message history with metadata
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "metadata": {
                "intent": result.get("intent"),
                "conversation_state": result.get("conversation_state"),
                "trust_score": result.get("trust_score"),
                "success": result.get("success", False)
            }
        })
        
        # Show status indicators
        if result.get("success"):
            intent = result.get("intent", "unknown")
            st.caption(f"Intent: {intent} | State: {result.get('conversation_state', 'unknown')}")
        else:
            st.error("Processing failed - please try again")

def display_help_section():
    """Display help and usage information"""
    with st.expander("How to use this system"):
        st.markdown("""
        **Travel Planning Assistant Features:**
        
        **Intent Classification:**
        - Understands greetings, travel planning requests, and other topics
        - Redirects off-topic conversations back to travel
        
        **Requirements Gathering:**
        - Collects destination, dates, budget, and preferences
        - Adapts questions based on your responses
        - Handles changes and corrections naturally
        
        **Security & Trust:**
        - Validates inputs and outputs for safety
        - Calculates trust scores based on interaction history
        - Blocks inappropriate or harmful content
        
        **Example Conversations:**
        - "Hello, I want to plan a trip"
        - "I need help planning a vacation to Japan for next month"
        - "What's a good budget for a week in Europe?"
        - "I want to visit Singapore in December for 5 days"
        """)

def main():
    """Main application"""
    # Page configuration
    st.set_page_config(
        page_title="Travel Planning Assistant",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Header
    st.title("✈️ Travel Planning Assistant")
    st.caption("AI-powered travel planning with intelligent conversation")
    
    # Initialize
    initialize_session()
    
    # Layout
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Main chat interface
        display_chat_interface()
    
    with col2:
        display_sidebar()
        display_help_section()
    
    if user_input := st.chat_input("Ask me about travel planning..."):
        process_user_input(user_input)

if __name__ == "__main__":
    main()