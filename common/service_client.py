# common/service_client.py
import os
import json
import requests
import boto3

import os, json, requests, boto3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# resilient session to avoid transient slowdowns
_session = requests.Session()
_session.mount("http://", HTTPAdapter(max_retries=Retry(
    total=2, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504]
)))
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=2, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504]
)))


DOWNSTREAM_MODE = os.getenv("DOWNSTREAM_MODE", "HTTP").upper()  # HTTP | LAMBDA
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")

# For HTTP mode (local dev)
INTENT_BASE_URL  = os.getenv("INTENT_SERVICE_URL",  "http://localhost:8001")
SHARED_BASE_URL  = os.getenv("SHARED_SERVICES_URL", "http://localhost:8004")

# For Lambda mode (deploy)
INTENT_LAMBDA  = os.getenv("INTENT_SERVICE_LAMBDA",  "intent-requirements-service")
SHARED_LAMBDA  = os.getenv("SHARED_SERVICES_LAMBDA", "shared-services")

_lambda = None
def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=AWS_REGION)
    return _lambda

def _invoke_lambda(function_name: str, method: str, path: str, body: dict):
    """
    Invoke a FastAPI+Mangum lambda by simulating an API Gateway (HTTP API v2) event.
    """
    event = {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"method": method, "path": path}},
        "isBase64Encoded": False,
        "body": json.dumps(body) if body is not None else None,
    }
    resp = _lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    payload = resp["Payload"].read().decode("utf-8")
    # Mangum returns {"statusCode":200,"body":"..."} as a JSON string
    try:
        gw = json.loads(payload)
        if isinstance(gw, dict) and "body" in gw:
            # body itself is a JSON string
            return json.loads(gw["body"])
        return gw
    except Exception:
        return {"success": False, "error": payload}

# -------- Public helpers your api-gateway can use --------
    
def classify_intent(payload: dict):
    if DOWNSTREAM_MODE == "LAMBDA":
        # (keep as you have)
        return _invoke_lambda(INTENT_LAMBDA, "POST", "/classify-intent", payload)
    r = _session.post(f"{INTENT_BASE_URL}/classify-intent", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def gather_requirements(payload: dict):
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(INTENT_LAMBDA, "POST", "/gather-requirements", payload)
    r = _session.post(f"{INTENT_BASE_URL}/gather-requirements", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def create_session(payload: dict):
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "POST", "/session/create", payload)
    r = _session.post(f"{SHARED_BASE_URL}/session/create", json=payload, timeout=20)  # was 10
    r.raise_for_status()
    return r.json()

def update_session(session_id: str, updates: dict):
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "PUT", f"/session/{session_id}", updates)
    r = _session.put(f"{SHARED_BASE_URL}/session/{session_id}", json=updates, timeout=20)  # was 10
    r.raise_for_status()
    return r.json()

def get_session(session_id: str):
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "GET", f"/session/{session_id}", {})
    r = _session.get(f"{SHARED_BASE_URL}/session/{session_id}", timeout=15)  # was 10
    r.raise_for_status()
    return r.json()

def validate_input(payload: dict):
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "POST", "/security/validate-input", payload)
    r = _session.post(f"{SHARED_BASE_URL}/security/validate-input", json=payload, timeout=20)  # was 10
    r.raise_for_status()
    return r.json()

def validate_output(payload: dict):
    if DOWNSTREAM_MODE == "LAMBDA":
        return _invoke_lambda(SHARED_LAMBDA, "POST", "/security/validate-output", payload)
    r = _session.post(f"{SHARED_BASE_URL}/security/validate-output", json=payload, timeout=45)  # was 10
    r.raise_for_status()
    return r.json()