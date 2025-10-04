# shared-services/security_pipeline.py

import os
from dotenv import load_dotenv

import hashlib
from typing import Dict, Any
from pathlib import Path
from nemoguardrails import RailsConfig, LLMRails

class SecurityPipeline:
    """Simplified security pipeline using NVIDIA NeMo Guardrails"""
    
    def __init__(self):
        load_dotenv() 
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY environment variable not found")
        
        config_path = Path(__file__).parent / "guardrails_config"
        config = RailsConfig.from_path(str(config_path))
        self.rails = LLMRails(config)
        print("NeMo Guardrails Security Pipeline initialized")
    
    async def validate_input(self, text: str, user_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Validate input using NeMo Guardrails with fallback"""
        try:
            response = await self.rails.generate_async(
                messages=[{"role": "user", "content": text}]
            )
            
            content = response.get("content", "")
            is_blocked = any(phrase in content for phrase in [
                "I can only help with travel planning",
                "I apologize, but I cannot provide that information"
            ])
            
            return self._build_validation_result(
                is_safe=not is_blocked,
                risk_score=0.8 if is_blocked else 0.1,
                text=text,
                response_content=content,
                blocked_reason="policy_violation" if is_blocked else None
            )
            
        except Exception as e:
            print(f"NeMo Guardrails validation error: {e}")
            return self._fallback_validation(text)
    
    async def validate_output(self, response_text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Validate output using NeMo Guardrails with fallback"""
        try:
            messages = [
                {"role": "user", "content": "Help me plan a trip"},
                {"role": "assistant", "content": response_text}
            ]
            
            validation_response = await self.rails.generate_async(messages=messages)
            content = validation_response.get("content", "")
            
            is_blocked = "I apologize, but I cannot provide that information" in content
            
            # Use consistent structure with _build_validation_result
            return {
                "is_safe": not is_blocked,
                "risk_score": 0.7 if is_blocked else 0.1,
                "threats_found": 1 if is_blocked else 0,  
                "cleaned_input": response_text.strip(),    
                "guardrail_response": content,             
                "blocked_reason": "policy_violation" if is_blocked else None,  
                "travel_compliant": not is_blocked,
                "privacy_safe": True,
                "filtered_response": content if is_blocked else response_text,
                "guardrail_active": True
            }
            
        except Exception as e:
            print(f"NeMo Guardrails output validation error: {e}")
            return self._fallback_output_validation(response_text)
    
    def _build_validation_result(self, is_safe: bool, risk_score: float, text: str, 
                               response_content: str, blocked_reason: str = None) -> Dict[str, Any]:
        """Build standardized validation result"""
        return {
            "is_safe": is_safe,
            "risk_score": risk_score,
            "threats_found": 0 if is_safe else 1,
            "cleaned_input": text.strip(),
            "guardrail_response": response_content,
            "blocked_reason": blocked_reason
        }
    
    def _fallback_validation(self, text: str) -> Dict[str, Any]:
        """Simple fallback validation when NeMo fails"""
        text_lower = text.lower()
        
        threat_patterns = [
            "ignore previous", "system override", "forget instructions",
            "developer mode", "admin access", "bypass safety"
        ]
        
        threats = sum(1 for pattern in threat_patterns if pattern in text_lower)
        is_safe = threats == 0
        
        return self._build_validation_result(
            is_safe=is_safe,
            risk_score=min(1.0, threats * 0.4),
            text=text,
            response_content="Fallback validation used",
            blocked_reason="potential_injection" if threats > 0 else None
        )

    def _fallback_output_validation(self, response_text: str) -> Dict[str, Any]:
        """Simple fallback for output validation"""
        sensitive_data = ["password", "credit card", "ssn", "social security"]
        has_sensitive = any(pattern in response_text.lower() for pattern in sensitive_data)
        
        return {
            "is_safe": not has_sensitive,
            "risk_score": 0.8 if has_sensitive else 0.1,
            "threats_found": 1 if has_sensitive else 0,  # Add this field
            "cleaned_input": response_text.strip(),      # Add this field  
            "guardrail_response": "Fallback validation used",  # Add this field
            "blocked_reason": "sensitive_data" if has_sensitive else None,  # Add this field
            # Keep existing fields
            "travel_compliant": True,
            "privacy_safe": not has_sensitive,
            "filtered_response": "[SENSITIVE DATA REDACTED]" if has_sensitive else response_text,
            "guardrail_active": False
        }
    
    def generate_content_hash(self, content: str) -> str:
        """Generate hash for content integrity verification"""
        return hashlib.sha256(content.encode()).hexdigest()[:16]