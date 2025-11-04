# frontend-service/ui.py

import streamlit as st
import httpx
import asyncio
from typing import Dict, Any, Optional
import time

# Configuration
# API_GATEWAY_URL = "http://localhost:8000"
API_GATEWAY_URL = "https://dhn05avgt6.execute-api.ap-southeast-1.amazonaws.com"

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
            "trust_score": 0.0,
            "collection_complete": False
        }

def initialize_session():
    """Initialize session state with defaults"""
    if "gateway_client" not in st.session_state:
        st.session_state.gateway_client = TravelGatewayClient()
    
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "collection_complete" not in st.session_state:
        st.session_state.collection_complete = False
    
    if "final_json_info" not in st.session_state:
        st.session_state.final_json_info = None
    
    if "mandatory_complete" not in st.session_state:
        st.session_state.mandatory_complete = False
    
    if "optional_progress" not in st.session_state:
        st.session_state.optional_progress = "0/6"

    if "retrieval_agent_data" not in st.session_state:
        st.session_state.retrieval_agent_data = None

def display_sidebar():
    """Display sidebar with session info and controls"""
    with st.sidebar:
        st.header("Session Info")
        
        # Session metrics
        if st.session_state.session_id:
            try:
                info = st.session_state.gateway_client.get_session_info(st.session_state.session_id)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Messages", len(st.session_state.messages) // 2)
                # with col2:
                #     trust_score = info.get("trust_score", 1.0)
                #     st.metric("Trust Score", f"{trust_score:.2f}")
                
                # Conversation state
                state = info.get("conversation_state", "unknown")
                st.info(f"State: {state.replace('_', ' ').title()}")
                
                # Show completion status
                if st.session_state.collection_complete:
                    st.success("✅ Collection Complete!")
                    
                    # NEW: Show retrieval agent status
                    if st.session_state.retrieval_agent_data:
                        retrieval_status = st.session_state.retrieval_agent_data.get("status")
                        if retrieval_status == "success":
                            st.success("🌍 Sustainability analysis ready!")
                        elif retrieval_status == "timeout":
                            st.warning("⏱️ Analysis in progress...")
                        else:
                            st.error("❌ Analysis failed")
                    
                    # Show final JSON info if available
                    if st.session_state.final_json_info:
                        with st.expander("📋 Final JSON Info"):
                            st.json(st.session_state.final_json_info)

            except Exception:
                st.warning("Could not load session info")
        else:
            st.info("No active session")
        
        st.divider()
        
        # Control buttons with unique keys
        st.markdown("### Actions")
        
        if st.button("🆕 New Session", key="new_session_btn", use_container_width=True, type="primary"):
            # Reset EVERYTHING for a fresh start
            st.session_state.session_id = None
            st.session_state.messages = []
            st.session_state.collection_complete = False
            st.session_state.final_json_info = None
            st.session_state.mandatory_complete = False
            st.session_state.optional_progress = "0/6"
            st.session_state.retrieval_agent_data = None 
        
        st.caption("Starts a completely new travel planning session")
        
        st.divider()
        
        # CLEAR CHAT: Only clear UI messages, keep session data
        if st.button("🧹 Clear Chat", key="clear_chat_btn", use_container_width=True):
            # Only clear messages, keep session and completion status
            st.session_state.messages = []
            # Streamlit will automatically rerun when session state changes
        
        st.caption("Clears chat display only (keeps session data)")
        
        st.divider()
        
        # Session ID display
        if st.session_state.session_id:
            with st.expander("🔑 Session Details"):
                st.code(st.session_state.session_id)
                st.caption("Current session identifier")

def display_chat_interface():
    """Main chat interface"""
    st.subheader("Chat with Travel Assistant")
    
    # Show completion banner based on status
    if st.session_state.collection_complete:
        st.success("🎉 **All requirements collected!** Your complete travel plan is ready.")
        st.info("💡 Click **🆕 New Session** in the sidebar to plan another trip.")
    elif st.session_state.get("mandatory_complete", False):
        optional_progress = st.session_state.get("optional_progress", "0/6")
        st.info(f"✅ **Core details captured!** Planning in progress. Optional fields: {optional_progress}")
        st.caption("💬 Keep chatting to add preferences (eco, dietary, interests, etc.)")
    
    # Display message history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            
            # Show metadata for assistant messages
            if message["role"] == "assistant" and "metadata" in message:
                metadata = message["metadata"]
                
                # Show metadata in a compact format
                meta_parts = []
                if metadata.get("intent"):
                    meta_parts.append(f"Intent: {metadata['intent']}")
                # if metadata.get("trust_score"):
                #     meta_parts.append(f"Trust: {metadata['trust_score']:.2f}")
                
                if meta_parts:
                    st.caption(" | ".join(meta_parts))

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
        
        # Check for collection completion
        if result.get("completion_status") == "mandatory_complete":
            st.session_state.mandatory_complete = True
            st.session_state.optional_progress = result.get("optional_progress", "0/6")

        # Check for full completion (lock textbox)
        if result.get("collection_complete", False):
            st.session_state.collection_complete = True
            
            # Store final JSON info
            st.session_state.final_json_info = {
                "session_id": result.get("session_id"),
                "s3_key": result.get("final_json_s3_key"),
                "planning_agent_status": result.get("planning_agent_status"),
            }
            
            # NEW: Store retrieval agent data if available
            if result.get("retrieval_agent"):
                st.session_state.retrieval_agent_data = result.get("retrieval_agent")
            
            # Show celebration
            st.balloons()
        
        # Display response
        response_text = result.get("response", "No response received")
        st.write(response_text)
        
        # NEW: Display retrieval agent results if available
        if result.get("retrieval_agent") and result["retrieval_agent"].get("status") == "success":
            display_retrieval_results(result["retrieval_agent"])
        
        # Add to message history with metadata
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "metadata": {
                "intent": result.get("intent"),
                "conversation_state": result.get("conversation_state"),
                "trust_score": result.get("trust_score"),
                "success": result.get("success", False),
                "collection_complete": result.get("collection_complete", False)
            }
        })
        
        # Show status indicators
        if result.get("success"):
            intent = result.get("intent", "unknown")
            state = result.get("conversation_state", "unknown")
            
            if result.get("collection_complete"):
                st.success(f"✅ Complete | Intent: {intent} | State: {state}")
            else:
                st.caption(f"Intent: {intent} | State: {state}")
        else:
            st.error("Processing failed - please try again")
    
    # Force rerun after completion to update UI immediately
    if result.get("collection_complete", False):
        st.rerun()

def display_retrieval_results(retrieval_data: Dict[str, Any]):
    """Display retrieval agent results in a nice format"""
    st.divider()
    
    st.subheader("🌍 Sustainability Analysis")
    
    if retrieval_data.get("status") == "success":
        data = retrieval_data.get("data", {})
        
        # Create tabs for different sections
        tab1, tab2, tab3 = st.tabs(["📊 Summary", "🔍 Details", "📄 Raw Data"])
        
        with tab1:
            st.success("✅ Carbon footprint analysis completed successfully!")
            
            # Display key metrics if available
            if isinstance(data, dict):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if "carbon_footprint" in data:
                        st.metric("Carbon Footprint", f"{data['carbon_footprint']} kg CO₂")
                
                with col2:
                    if "sustainability_score" in data:
                        st.metric("Sustainability Score", f"{data['sustainability_score']}/100")
                
                with col3:
                    if "eco_rating" in data:
                        st.metric("Eco Rating", data['eco_rating'])
                
                # Show recommendations if available
                if "recommendations" in data:
                    st.markdown("#### 💡 Recommendations")
                    for rec in data["recommendations"]:
                        st.info(rec)
        
        with tab2:
            st.markdown("#### Detailed Analysis")
            
            if isinstance(data, dict):
                # Display nested data in expandable sections
                for key, value in data.items():
                    if key not in ["carbon_footprint", "sustainability_score", "eco_rating", "recommendations"]:
                        with st.expander(f"📌 {key.replace('_', ' ').title()}"):
                            if isinstance(value, (dict, list)):
                                st.json(value)
                            else:
                                st.write(value)
            else:
                st.json(data)
        
        with tab3:
            st.markdown("#### Raw Response Data")
            st.json(data)
    
    elif retrieval_data.get("status") == "timeout":
        st.warning("⏱️ Retrieval agent is still processing. Please check back later.")
    
    else:
        st.error(f"❌ Retrieval agent error: {retrieval_data.get('message', 'Unknown error')}")

def display_help_section():
    """Display help and usage information"""
    with st.expander("ℹ️ How to use this system"):
        st.markdown("""
        ### Travel Planning Assistant Features
        
        #### 🎯 Intent Classification
        - Understands greetings, travel planning requests, and other topics
        - Redirects off-topic conversations back to travel
        
        #### 📝 Requirements Gathering
        - **Required:** destination, dates, duration, **travelers (adults/children)**, budget (SGD), pace
        - **Optional:** interests, dietary needs, eco preferences, group type
        - For optional fields: saying "no preference" or "none" counts as answered
        - Adapts questions based on your responses
        - Handles changes and corrections naturally
        
        #### ✅ Completion Detection
        - Automatically detects when all required information is collected
        - Generates final JSON and stores in S3
        - Disables chat input to prevent additional messages
        - Sends data to planning agent for next steps
        
        #### 🔒 Security & Trust
        - Validates inputs and outputs for safety
        - Calculates trust scores based on interaction history
        - Blocks inappropriate or harmful content
        
        #### 💡 Example Conversations
        
        **Simple:**
```
        "Hello!"
        "I want to visit Singapore from Dec 20-25"
        "2 adults and 1 child"
        "Budget is 2000 SGD"
        "Relaxed pace, interested in gardens"
        "No dietary restrictions"
```
        
        **All-in-one:**
```
        "I want to visit Singapore from December 20-25, 2025 
        with my wife and 2 kids, budget of 2000 SGD, relaxed pace, 
        interested in gardens and museums, no dietary preferences"
```
        
        #### 🔄 After Completion
        - Chat input will be **disabled**
        - Click **🆕 New Session** to start planning another trip
        - Click **🧹 Clear Chat** to just clear the display
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
    
    # Initialize session state FIRST
    initialize_session()
    
    # Header
    st.title("✈️ Travel Planning Assistant")
    
    # Dynamic caption based on completion status
    if st.session_state.collection_complete:
        st.caption("✅ Requirements collection complete - Ready for planning!")
    else:
        st.caption("AI-powered travel planning with intelligent conversation")
    
    # Layout
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Main chat interface
        display_chat_interface()
    
    with col2:
        display_sidebar()
        display_help_section()
    
    # Conditional chat input - disable when collection is complete
    if not st.session_state.collection_complete:
        user_input = st.chat_input("Ask me about travel planning...")
        if user_input:
            process_user_input(user_input)
    else:
        # Show disabled state with message
        st.chat_input("Collection complete - Start a new session to continue", disabled=True)

if __name__ == "__main__":
    main()