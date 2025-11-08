import streamlit as st
import httpx
import asyncio
from typing import Dict, Any, Optional
import time
import boto3
import json
from botocore.config import Config

# Configuration
USE_DIRECT_LAMBDA = True
ORCHESTRATOR_LAMBDA_NAME = "stp-api-gateway-prod"
API_GATEWAY_URL = "https://fwjpkz62bk.execute-api.ap-southeast-1.amazonaws.com"
S3_BUCKET_NAME = "iss-travel-planner"
AWS_REGION = "ap-southeast-1"

class TravelGatewayClient:
    """Simplified client for travel gateway API with direct Lambda support"""
    
    def __init__(self):
        self.gateway_url = API_GATEWAY_URL
        self.use_direct_lambda = USE_DIRECT_LAMBDA
        
        self.gateway_url = API_GATEWAY_URL
        self.use_direct_lambda = USE_DIRECT_LAMBDA

        self.s3_client = boto3.client('s3', region_name=AWS_REGION)
        
        if self.use_direct_lambda:
            # Configure with longer timeout
            config = Config(
                read_timeout=900,  # 15 minutes
                connect_timeout=10
            )
            self.lambda_client = boto3.client(
                'lambda', 
                region_name='ap-southeast-1',
                config=config  # ← Add config
            )
    
    def process_input(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Process input via API Gateway or direct Lambda"""
        if self.use_direct_lambda:
            # Check if this might trigger completion
            is_likely_completion = self._check_if_completion(session_id)
            
            if is_likely_completion:
                # Use async invocation for completion
                return self._invoke_lambda_async(user_input, session_id)
            else:
                # Use sync invocation for normal chat
                return self._invoke_lambda_sync(user_input, session_id)
        else:
            return asyncio.run(self._process_input_async(user_input, session_id))

    def get_pdf_download_url(self, pdf_s3_key: str) -> str:
        """Generate presigned URL for PDF download"""
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': S3_BUCKET_NAME,
                    'Key': pdf_s3_key
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
            return url
        except Exception as e:
            print(f"Error generating download URL: {e}")
            return None
    
    def _check_if_completion(self, session_id: str) -> bool:
        """Check if session is close to completion"""
        if not session_id:
            return False
        
        try:
            # Get session info to check completion status
            info = self.get_session_info(session_id)
            
            # If mandatory already complete, next message might trigger full completion
            conversation_state = info.get("data", {}).get("conversation_state", "")
            return conversation_state == "requirements_complete"
        except:
            return False
    
    def _invoke_lambda_async(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Async Lambda invocation for long-running operations"""
        try:
            payload = self._build_lambda_payload(user_input, session_id)
            
            # Use Event invocation (fire and forget)
            response = self.lambda_client.invoke(
                FunctionName=ORCHESTRATOR_LAMBDA_NAME,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
            
            # Return immediate acknowledgment
            return {
                "success": True,
                "response": "✅ All requirements collected! Processing your complete travel plan...\n\n⏳ This may take 2-5 minutes. Click '🔄 Check Status' in the sidebar to see progress.",
                "session_id": session_id,
                "intent": "processing",
                "conversation_state": "processing",
                "trust_score": 1.0,
                "collection_complete": True,
                "processing": True
            }
        except Exception as e:
            return self._create_error_response(str(e), session_id)
    
    def _invoke_lambda_sync(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Sync Lambda invocation for normal chat"""
        try:
            payload = self._build_lambda_payload(user_input, session_id)
            
            # Use RequestResponse for sync
            response = self.lambda_client.invoke(
                FunctionName=ORCHESTRATOR_LAMBDA_NAME,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload),
                # Use custom config for longer timeout
            )
            
            # Parse response
            response_payload = json.loads(response['Payload'].read())
            
            if 'body' in response_payload:
                body = json.loads(response_payload['body'])
                return body
            else:
                return response_payload
                
        except Exception as e:
            return self._create_error_response(str(e), session_id)
    
    def _build_lambda_payload(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Build Mangum-compatible event payload"""
        return {
            "version": "2.0",
            "routeKey": "POST /travel/plan",
            "rawPath": "/travel/plan",
            "rawQueryString": "",
            "headers": {
                "content-type": "application/json"
            },
            "requestContext": {
                "accountId": "123456789012",
                "apiId": "lambda-direct",
                "domainName": "lambda.direct",
                "http": {
                    "method": "POST",
                    "path": "/travel/plan",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1"
                },
                "requestId": f"direct-{int(time.time())}",
                "routeKey": "POST /travel/plan",
                "stage": "$default",
                "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime()),
                "timeEpoch": int(time.time())
            },
            "body": json.dumps({
                "user_input": user_input,
                "session_id": session_id
            }),
            "isBase64Encoded": False
        }
    
    def check_processing_status(self, session_id: str) -> Dict[str, Any]:
        """Check if processing is complete by looking for results in S3"""
        try:
            # List objects in planner_agent folder for this session
            response = self.s3_client.list_objects_v2(
                Bucket=S3_BUCKET_NAME,
                Prefix=f"planner_agent/",
                MaxKeys=100
            )
            
            if 'Contents' not in response:
                return {"status": "processing", "message": "No results yet"}
            
            # Find the most recent file for this session
            session_files = [
                obj for obj in response['Contents']
                if session_id in obj['Key'] and obj['Key'].endswith('.json')
            ]
            
            if not session_files:
                return {"status": "processing", "message": "Still processing..."}
            
            # Get the most recent file
            latest_file = sorted(session_files, key=lambda x: x['LastModified'], reverse=True)[0]
            
            # Read the file
            obj = self.s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=latest_file['Key'])
            data = json.loads(obj['Body'].read().decode('utf-8'))
            
            # ✅ CHANGED: Get presigned URL from response
            pdf_presigned_url = data.get("s3_pdf_presigned_url")
            pdf_s3_key = data.get("s3_pdf_key")
            pdf_available = bool(pdf_presigned_url or pdf_s3_key)
            
            return {
                "status": "completed",
                "data": data,
                "s3_key": latest_file['Key'],
                "last_modified": latest_file['LastModified'].isoformat(),
                "pdf_s3_key": pdf_s3_key,
                "pdf_presigned_url": pdf_presigned_url,  # ✅ ADD THIS
                "pdf_available": pdf_available
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _process_input_async(self, user_input: str, session_id: str = None) -> Dict[str, Any]:
        """Async implementation for API Gateway"""
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
        if self.use_direct_lambda:
            return self._get_session_info_lambda(session_id)
        else:
            return asyncio.run(self._get_session_info_async(session_id))
    
    def _get_session_info_lambda(self, session_id: str) -> Dict[str, Any]:
        """Get session info via direct Lambda invocation"""
        try:
            payload = {
                "version": "2.0",
                "routeKey": f"GET /travel/session/{session_id}",
                "rawPath": f"/travel/session/{session_id}",
                "rawQueryString": "",
                "headers": {},
                "requestContext": {
                    "accountId": "123456789012",
                    "apiId": "lambda-direct",
                    "domainName": "lambda.direct",
                    "http": {
                        "method": "GET",
                        "path": f"/travel/session/{session_id}",
                        "protocol": "HTTP/1.1",
                        "sourceIp": "127.0.0.1"
                    },
                    "requestId": f"direct-{int(time.time())}",
                    "routeKey": f"GET /travel/session/{session_id}",
                    "stage": "$default",
                    "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime()),
                    "timeEpoch": int(time.time())
                },
                "pathParameters": {
                    "session_id": session_id
                },
                "isBase64Encoded": False
            }
            
            response = self.lambda_client.invoke(
                FunctionName=ORCHESTRATOR_LAMBDA_NAME,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            
            response_payload = json.loads(response['Payload'].read())
            
            if 'body' in response_payload:
                body = json.loads(response_payload['body'])
                return body
            else:
                return response_payload
                
        except Exception:
            return {"error": "Session not found", "trust_score": 1.0, "conversation_state": "unknown"}
    
    async def _get_session_info_async(self, session_id: str) -> Dict[str, Any]:
        """Async session info retrieval for API Gateway"""
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
    
    if "processing_status" not in st.session_state:
        st.session_state.processing_status = None

    if "pdf_s3_key" not in st.session_state:
        st.session_state.pdf_s3_key = None

    if "pdf_presigned_url" not in st.session_state:
        st.session_state.pdf_presigned_url = None

def display_sidebar():
    """Display sidebar with session info and controls"""
    with st.sidebar:
        st.header("Session Info")
        
        # Show connection method
        connection_method = "🔗 Direct Lambda" if USE_DIRECT_LAMBDA else "🌐 API Gateway"
        st.caption(f"Connection: {connection_method}")
        
        # Session metrics
        if st.session_state.session_id:
            try:
                info = st.session_state.gateway_client.get_session_info(st.session_state.session_id)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Messages", len(st.session_state.messages) // 2)
                
                # Conversation state
                state = info.get("data", {}).get("conversation_state", "unknown")
                st.info(f"State: {state.replace('_', ' ').title()}")
                
                # Show completion status
                if st.session_state.collection_complete:
                    st.success("✅ Collection Complete!")

                    if st.session_state.pdf_s3_key:
                        st.divider()
                        st.markdown("### 📄 Your Itinerary")
                        
                        if st.button("📥 Download PDF", key="download_pdf_btn", use_container_width=True, type="primary"):
                            with st.spinner("Generating download link..."):
                                # ✅ CHANGED: Use presigned URL if available
                                if hasattr(st.session_state, 'pdf_presigned_url') and st.session_state.pdf_presigned_url:
                                    download_url = st.session_state.pdf_presigned_url
                                else:
                                    download_url = st.session_state.gateway_client.get_pdf_download_url(
                                        st.session_state.pdf_s3_key
                                    )
                                
                                if download_url:
                                    st.markdown(f"[🔗 Click here to download your itinerary]({download_url})")
                                    st.success("✅ Download link ready!")
                                else:
                                    st.error("❌ Could not generate download link. PDF may still be processing.")
                        
                        st.caption("Your personalized travel itinerary PDF")
                    
                    if st.button("🔄 Check Processing Status", key="check_status_btn", use_container_width=True):
                        with st.spinner("Checking status..."):
                            status = st.session_state.gateway_client.check_processing_status(
                                st.session_state.session_id
                            )
                            st.session_state.processing_status = status
                            st.rerun()

                    # ✅ ADD THIS ENTIRE SECTION:
                    if st.session_state.processing_status:
                        status = st.session_state.processing_status
                        if status.get("status") == "completed":
                            st.success("🎉 Your itinerary is ready!")
                            
                            # Store both key AND presigned URL
                            if status.get("pdf_available"):
                                st.session_state.pdf_s3_key = status.get("pdf_s3_key")
                                st.session_state.pdf_presigned_url = status.get("pdf_presigned_url")
                                st.rerun()
                            
                            with st.expander("📄 View Results"):
                                st.json(status.get("data"))
                        
                        elif status.get("status") == "processing":
                            st.info("⏳ Still processing...")
                        
                        else:
                            st.warning(f"Status: {status.get('message', 'Unknown')}")

                    # Show final JSON info if available
                    if st.session_state.final_json_info:
                        with st.expander("📋 Final JSON Info"):
                            st.json(st.session_state.final_json_info)

            except Exception as e:
                st.warning(f"Could not load session info: {e}")
        else:
            st.info("No active session")
        
        st.divider()
        
        # Control buttons
        st.markdown("### Actions")
        
        if st.button("🆕 New Session", key="new_session_btn", use_container_width=True, type="primary"):
            # Reset everything
            st.session_state.session_id = None
            st.session_state.messages = []
            st.session_state.collection_complete = False
            st.session_state.final_json_info = None
            st.session_state.mandatory_complete = False
            st.session_state.optional_progress = "0/6"
            st.session_state.retrieval_agent_data = None
            st.session_state.processing_status = None
            st.rerun()
        
        st.caption("Starts a completely new travel planning session")
        
        st.divider()
        
        if st.button("🧹 Clear Chat", key="clear_chat_btn", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        
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
    
    # Show completion banner
    if st.session_state.collection_complete:
        st.success("🎉 **All requirements collected!** Your complete travel plan is being generated.")
        st.info("💡 Click **🔄 Check Processing Status** in the sidebar to see progress.")
    elif st.session_state.get("mandatory_complete", False):
        optional_progress = st.session_state.get("optional_progress", "0/6")
        st.info(f"✅ **Core details captured!** Optional fields: {optional_progress}")
        st.caption("💬 Keep chatting to add preferences")
    
    # Display message history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            
            if message["role"] == "assistant" and "metadata" in message:
                metadata = message["metadata"]
                meta_parts = []
                if metadata.get("intent"):
                    meta_parts.append(f"Intent: {metadata['intent']}")
                if meta_parts:
                    st.caption(" | ".join(meta_parts))

def process_user_input(user_input: str):
    """Process user input and update chat"""
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    with st.chat_message("user"):
        st.write(user_input)
    
    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            result = st.session_state.gateway_client.process_input(
                user_input, st.session_state.session_id
            )
        
        if not st.session_state.session_id and result.get("session_id"):
            st.session_state.session_id = result["session_id"]
        
        if result.get("completion_status") == "mandatory_complete":
            st.session_state.mandatory_complete = True
            st.session_state.optional_progress = result.get("optional_progress", "0/6")

        if result.get("collection_complete", False):
            st.session_state.collection_complete = True
            
            st.session_state.final_json_info = {
                "session_id": result.get("session_id"),
                "s3_key": result.get("final_json_s3_key"),
                "planning_agent_status": result.get("planning_agent_status"),
                "pdf_s3_key": result.get("pdf_s3_key") 
            }
            
            if result.get("pdf_s3_key"):
                st.session_state.pdf_s3_key = result.get("pdf_s3_key")
            
            if result.get("retrieval_agent"):
                st.session_state.retrieval_agent_data = result.get("retrieval_agent")
            
            st.balloons()
        
        response_text = result.get("response", "No response received")
        st.write(response_text)
        
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
        
        if result.get("success"):
            intent = result.get("intent", "unknown")
            state = result.get("conversation_state", "unknown")
            
            if result.get("collection_complete"):
                st.success(f"✅ Complete | Intent: {intent} | State: {state}")
            else:
                st.caption(f"Intent: {intent} | State: {state}")
        else:
            st.error("Processing failed - please try again")
    
    if result.get("collection_complete", False):
        st.rerun()

def display_help_section():
    """Display help information"""
    with st.expander("ℹ️ How to use"):
        st.markdown("""
        ### Travel Planning Assistant
        
        1. **Chat normally** - Tell me about your travel plans
        2. **Provide details** - Destination, dates, budget, travelers, pace
        3. **Add preferences** - Interests, dietary needs, eco preferences (optional)
        4. **Get your plan** - Processing takes 2-5 minutes after collection completes
        5. **Check status** - Use the sidebar button to see progress
        
        Example: "I want to visit Singapore from Dec 20-25 with 2 adults, budget 2000 SGD, relaxed pace"
        """)

def main():
    """Main application"""
    st.set_page_config(
        page_title="Travel Planning Assistant",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    initialize_session()
    
    st.title("✈️ Travel Planning Assistant")
    
    if st.session_state.collection_complete:
        st.caption("✅ Requirements complete - Processing your itinerary!")
    else:
        st.caption("AI-powered travel planning")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        display_chat_interface()
    
    with col2:
        display_sidebar()
        display_help_section()
    
    if not st.session_state.collection_complete:
        user_input = st.chat_input("Ask me about travel planning...")
        if user_input:
            process_user_input(user_input)
    else:
        st.chat_input("Processing complete - Start new session", disabled=True)

if __name__ == "__main__":
    main()