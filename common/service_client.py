# common/service_client.py 

import os
import json
import requests
import boto3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session = requests.Session()
_session.mount("http://", HTTPAdapter(max_retries=Retry(
    total=2, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504]
)))
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504]
)))

DOWNSTREAM_MODE = os.getenv("DOWNSTREAM_MODE")
AWS_REGION = os.getenv("AWS_REGION")

# For HTTP mode (local dev)
INTENT_BASE_URL  = os.getenv("INTENT_SERVICE_URL")
SHARED_BASE_URL  = os.getenv("SHARED_SERVICES_URL")

# For Lambda mode (deploy)
INTENT_LAMBDA  = os.getenv("INTENT_SERVICE_LAMBDA")
SHARED_LAMBDA  = os.getenv("SHARED_SERVICES_LAMBDA")

# Debug logging
print("=" * 60)
print("[SERVICE_CLIENT] Configuration:")
print(f"  DOWNSTREAM_MODE     : {DOWNSTREAM_MODE}")
print(f"  AWS_REGION          : {AWS_REGION}")
print(f"  INTENT_BASE_URL     : {INTENT_BASE_URL}")
print(f"  SHARED_BASE_URL     : {SHARED_BASE_URL}")
print(f"  INTENT_LAMBDA       : {INTENT_LAMBDA}")
print(f"  SHARED_LAMBDA       : {SHARED_LAMBDA}")
print("=" * 60)

_lambda = None
def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=AWS_REGION)
    return _lambda

def _invoke_lambda(function_name: str, method: str, path: str, body: dict, *, direct: bool = False):
    """
    Invoke a downstream Lambda.

    - direct=True  -> send a simple event shape consumed by the function's lambda_handler
                      (which internally routes via FastAPI TestClient). This avoids Mangum entirely.
    - direct=False -> send an API Gateway HTTP API v2-shaped event, for Mangum handlers.

    Includes comprehensive error handling and logging.
    """
    if direct:
        event = {
            "path": path,
            "httpMethod": method,
            "body": body,  
        }
    else:
        event = {
            "version": "2.0",
            "routeKey": f"{method} {path}",
            "rawPath": path,
            "rawQueryString": "",
            "cookies": [],
            "headers": {
                "content-type": "application/json",
                "x-forwarded-for": "127.0.0.1",
                "user-agent": "lambda-invoke",
            },
            "queryStringParameters": {},
            "pathParameters": {},
            "requestContext": {
                "http": {
                    "method": method,
                    "path": path,
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",  
                    "userAgent": "lambda-invoke",
                }
            },
            "isBase64Encoded": False,
            "body": json.dumps(body) if body is not None else None,
        }

    try:
        print(f"🔄 Invoking Lambda: {function_name} {method} {path}")
        start_time = __import__('time').time()

        resp = _lambda_client().invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode("utf-8"),
        )

        elapsed = __import__('time').time() - start_time
        print(f"⏱️ Lambda {function_name} invocation took {elapsed:.2f}s")

        # Lambda execution error (handled by AWS runtime)
        if resp.get('FunctionError'):
            payload_text = resp["Payload"].read().decode("utf-8")
            print(f"❌ Lambda execution error in {function_name}:")
            print(f"   Error type: {resp.get('FunctionError')}")
            print(f"   Error payload (first 1000 chars): {payload_text[:1000]}")
            try:
                data = json.loads(payload_text)
                if isinstance(data, dict):
                    error_msg = data.get('errorMessage', str(data))
                    error_type = data.get('errorType', 'Unknown')
                    print(f"   Error message: {error_msg}")
                    print(f"   Error type: {error_type}")
                    return {"success": False, "error": f"Lambda error ({error_type}): {error_msg}", "error_type": error_type}
            except json.JSONDecodeError:
                pass
            return {"success": False, "error": f"Lambda error: {payload_text[:500]}"}

        # Normal payload
        payload_text = resp["Payload"].read().decode("utf-8")
        print(f"✅ Lambda {function_name} responded: {len(payload_text)} bytes")

        try:
            gw = json.loads(payload_text)

            # APIGW proxy response
            if isinstance(gw, dict) and "body" in gw:
                status_code = gw.get("statusCode", 200)
                if status_code >= 400:
                    print(f"⚠️ Lambda returned error status: {status_code}")
                    error_body = gw.get("body", "Unknown error")
                    try:
                        error_data = json.loads(error_body) if isinstance(error_body, str) else error_body
                        return {"success": False, "error": f"HTTP {status_code}: {error_data}", "status_code": status_code}
                    except Exception:
                        return {"success": False, "error": f"HTTP {status_code}: {error_body}", "status_code": status_code}

                body_content = json.loads(gw["body"]) if isinstance(gw["body"], str) else gw["body"]
                return body_content

            # Direct JSON (already the response body)
            return gw

        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error from {function_name}: {e}")
            print(f"   Raw payload (first 500 chars): {payload_text[:500]}")
            return {"success": False, "error": f"Invalid JSON response: {str(e)}", "raw_preview": payload_text[:200]}

    except Exception as e:
        print(f"❌ Exception invoking {function_name}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Lambda invocation failed: {str(e)}", "exception_type": type(e).__name__}

# -------- Public helpers your api-gateway can use --------

def classify_intent(payload: dict):
    """Classify user intent (greeting vs planning)"""
    if DOWNSTREAM_MODE == "LAMBDA":
        # Use direct path implemented in intent-requirements-service.lambda_handler
        return _invoke_lambda(INTENT_LAMBDA, "POST", "/classify-intent", payload, direct=True)
    try:
        r = _session.post(f"{INTENT_BASE_URL}/classify-intent", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error calling intent service: {e}")
        return {"success": False, "error": str(e)}

def gather_requirements(payload: dict):
    """Gather travel requirements from conversation"""
    if DOWNSTREAM_MODE == "LAMBDA":
        # Hit the alias that your lambda_handler routes to the same FastAPI logic
        return _invoke_lambda(INTENT_LAMBDA, "POST", "/intent/requirements", payload, direct=True)
    try:
        r = _session.post(f"{INTENT_BASE_URL}/gather-requirements", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error calling requirements service: {e}")
        return {"success": False, "error": str(e)}

def create_session(payload: dict):
    """Create new session"""
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "POST", "/session/create", payload)  # APIGW v2 event
    try:
        r = _session.post(f"{SHARED_BASE_URL}/session/create", json=payload, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error creating session: {e}")
        return {"success": False, "error": str(e)}

def update_session(session_id: str, updates: dict):
    """Update existing session"""
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "PUT", f"/session/{session_id}", updates)  # APIGW v2 event
    try:
        r = _session.put(f"{SHARED_BASE_URL}/session/{session_id}", json=updates, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error updating session: {e}")
        return {"success": False, "error": str(e)}

def get_session(session_id: str):
    """Get session data"""
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "GET", f"/session/{session_id}", {})  # APIGW v2 event
    try:
        r = _session.get(f"{SHARED_BASE_URL}/session/{session_id}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error getting session: {e}")
        return {"success": False, "error": str(e)}

def validate_input(payload: dict):
    """Validate user input for security"""
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "POST", "/security/validate-input", payload)  # APIGW v2 event
    try:
        r = _session.post(f"{SHARED_BASE_URL}/security/validate-input", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error validating input: {e}")
        # Fail open for input validation (allow request to proceed)
        return {"is_safe": True, "error": str(e)}

def validate_output(payload: dict):
    """Validate assistant output for security"""
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "POST", "/security/validate-output", payload)  # APIGW v2 event
    try:
        r = _session.post(f"{SHARED_BASE_URL}/security/validate-output", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"❌ HTTP error validating output: {e}")
        # Fail open for output validation (allow response to proceed)
        return {"is_safe": True, "error": str(e)}
