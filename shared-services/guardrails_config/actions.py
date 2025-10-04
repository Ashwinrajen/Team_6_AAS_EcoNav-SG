from nemoguardrails.actions import action
from typing import Optional

@action(is_system_action=True)
async def self_check_input(context: Optional[dict] = None):
    """Custom input validation logic"""
    user_input = context.get("user_input", "").lower()
    
    # Block obvious prompt injection attempts
    injection_patterns = [
        "ignore previous", "forget instructions", "system override",
        "developer mode", "admin access", "bypass safety"
    ]
    
    if any(pattern in user_input for pattern in injection_patterns):
        return "No"
    
    # Block completely off-topic requests
    travel_keywords = [
        "travel", "trip", "vacation", "destination", "hotel", "flight",
        "budget", "plan", "visit", "tour", "accommodation"
    ]
    
    # If input is very short or contains travel keywords, allow it
    if len(user_input.split()) < 3 or any(keyword in user_input for keyword in travel_keywords):
        return "Yes"
    
    # Block if completely unrelated to travel
    unrelated_keywords = [
        "politics", "medical", "legal", "financial", "relationship",
        "programming", "technical support", "homework"
    ]
    
    if any(keyword in user_input for keyword in unrelated_keywords):
        return "No"
    
    return "Yes"  # Allow by default

@action(is_system_action=True)
async def self_check_output(context: Optional[dict] = None):
    """Custom output validation logic"""
    bot_response = context.get("bot_response", "").lower()
    
    # Block responses with sensitive information
    sensitive_patterns = [
        "password", "credit card", "ssn", "social security",
        "personal information", "private data"
    ]
    
    if any(pattern in bot_response for pattern in sensitive_patterns):
        return "No"
    
    # Ensure response stays on topic
    travel_indicators = [
        "travel", "trip", "destination", "hotel", "vacation",
        "budget", "plan", "visit", "sustainable"
    ]
    
    # If response is travel-related or asking for clarification, allow it
    if any(indicator in bot_response for indicator in travel_indicators) or "help" in bot_response:
        return "Yes"
    
    return "Yes"  # Allow by default for now