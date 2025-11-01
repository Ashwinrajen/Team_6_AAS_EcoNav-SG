# shared-services/security_pipeline.py

import os
import asyncio
import hashlib
from typing import Dict, Any
from datetime import datetime

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


class SecurityPipeline:
    """
    Security & policy guardrails using OpenAI Moderation API.
    - Toggle via GUARDRAILS_ENABLED=true|false
    - Per-call timeout via GUARDRAILS_TIMEOUT (seconds)
    - Uses OpenAI Moderation API when enabled, otherwise falls back to local checks
    """

    def __init__(self):
        # Feature flags / runtime knobs
        self.enabled: bool = os.getenv("GUARDRAILS_ENABLED")
        self.timeout_s: int = int(os.getenv("GUARDRAILS_TIMEOUT"))
        
        # Travel-specific keywords for context validation
        self.travel_keywords = [
            "travel", "trip", "vacation", "destination", "hotel", "flight",
            "budget", "plan", "visit", "tour", "accommodation", "booking",
            "itinerary", "tourist", "sightseeing", "passport", "visa"
        ]
        
        self.off_topic_keywords = [
            "politics", "election", "medical", "legal", "financial", "stock",
            "cryptocurrency", "programming", "code", "homework", "essay"
        ]

        # Initialize OpenAI client only if enabled
        if self.enabled:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not found (required when GUARDRAILS_ENABLED=true).")
            
            self.client = AsyncOpenAI(api_key=api_key)
            print(f"[SecurityPipeline] OpenAI Moderation enabled (timeout={self.timeout_s}s)")
        else:
            self.client = None
            print("[SecurityPipeline] Guardrails disabled via GUARDRAILS_ENABLED=false")

    # -------------------------
    # Public API
    # -------------------------
    async def validate_input(self, text: str, user_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Validate user input using OpenAI Moderation API.
        When disabled or on error/timeout, returns a safe fallback.
        """
        if not self.enabled or self.client is None:
            return self._fallback_validation(text)

        try:
            # Run both moderation and travel-context checks in parallel
            moderation_result, context_result = await asyncio.gather(
                self._check_moderation(text),
                self._check_travel_context(text),
                return_exceptions=True
            )
            
            # Handle exceptions from parallel execution
            if isinstance(moderation_result, Exception):
                print(f"[SecurityPipeline] Moderation error: {moderation_result}")
                return self._fallback_validation(text)
            
            if isinstance(context_result, Exception):
                print(f"[SecurityPipeline] Context check error: {context_result}")
                context_result = {"is_travel_related": True, "reason": None}  # Fail open
            
            # Combine results
            is_safe = moderation_result["is_safe"] and context_result["is_travel_related"]
            risk_score = max(moderation_result["risk_score"], 
                           0.0 if context_result["is_travel_related"] else 0.7)
            
            blocked_reason = None
            if not moderation_result["is_safe"]:
                blocked_reason = f"content_policy_violation: {moderation_result.get('violation_categories', [])}"
            elif not context_result["is_travel_related"]:
                blocked_reason = f"off_topic: {context_result.get('reason', 'unrelated to travel')}"
            
            return {
                "is_safe": is_safe,
                "risk_score": risk_score,
                "threats_found": 0 if is_safe else 1,
                "cleaned_input": text.strip(),
                "moderation_details": moderation_result.get("details", {}),
                "travel_context": context_result,
                "blocked_reason": blocked_reason,
                "guardrail_active": True,
            }
            
        except Exception as e:
            print(f"[SecurityPipeline] validate_input error/timeout: {e}")
            return self._fallback_validation(text)

    async def validate_output(self, response_text: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Validate assistant output using OpenAI Moderation API.
        When disabled or on error/timeout, returns a safe fallback.
        """
        if not self.enabled or self.client is None:
            return self._fallback_output_validation(response_text)

        try:
            moderation_result = await self._check_moderation(response_text)
            
            if isinstance(moderation_result, Exception):
                print(f"[SecurityPipeline] Output moderation error: {moderation_result}")
                return self._fallback_output_validation(response_text)
            
            is_safe = moderation_result["is_safe"]
            
            return {
                "is_safe": is_safe,
                "risk_score": moderation_result["risk_score"],
                "threats_found": 0 if is_safe else 1,
                "cleaned_input": response_text.strip(),
                "moderation_details": moderation_result.get("details", {}),
                "blocked_reason": f"content_policy_violation: {moderation_result.get('violation_categories', [])}" if not is_safe else None,
                "travel_compliant": True,  # Assume output is travel-related
                "privacy_safe": not self._contains_sensitive_data(response_text),
                "filtered_response": "[CONTENT FILTERED]" if not is_safe else response_text,
                "guardrail_active": True,
            }
            
        except Exception as e:
            print(f"[SecurityPipeline] validate_output error/timeout: {e}")
            return self._fallback_output_validation(response_text)

    def generate_content_hash(self, content: str) -> str:
        """Small helper for integrity/debugging."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # -------------------------
    # OpenAI Moderation
    # -------------------------
    async def _check_moderation(self, text: str) -> Dict[str, Any]:
        """
        Call OpenAI Moderation API to check for policy violations.
        Returns dict with is_safe, risk_score, and details.
        """
        try:
            response = await asyncio.wait_for(
                self.client.moderations.create(input=text),
                timeout=self.timeout_s
            )
            
            result = response.results[0]
            
            # Check if any category is flagged
            is_safe = not result.flagged
            
            # Calculate risk score based on category scores
            categories = result.categories
            category_scores = result.category_scores
            
            # Get highest score across all categories
            risk_score = 0.0
            violation_categories = []
            
            if result.flagged:
                # Collect flagged categories
                for category, flagged in categories.model_dump().items():
                    if flagged:
                        violation_categories.append(category)
                        # Get the score for this category
                        score = getattr(category_scores, category, 0.0)
                        risk_score = max(risk_score, score)
            
            return {
                "is_safe": is_safe,
                "risk_score": min(risk_score, 1.0),  # Ensure 0-1 range
                "violation_categories": violation_categories,
                "details": {
                    "flagged": result.flagged,
                    "categories": categories.model_dump(),
                    "category_scores": category_scores.model_dump()
                }
            }
            
        except asyncio.TimeoutError:
            print(f"[SecurityPipeline] Moderation API timeout after {self.timeout_s}s")
            raise
        except Exception as e:
            print(f"[SecurityPipeline] Moderation API error: {e}")
            raise

    async def _check_travel_context(self, text: str) -> Dict[str, Any]:
        """
        Check if input is travel-related or off-topic.
        Uses keyword matching for fast, local validation.
        """
        text_lower = text.lower()
        
        # Very short inputs (greetings, simple responses) should pass
        if len(text.split()) < 5:
            return {"is_travel_related": True, "reason": None}
        
        # Check for travel keywords
        has_travel_keywords = any(keyword in text_lower for keyword in self.travel_keywords)
        
        # Check for off-topic keywords
        has_off_topic_keywords = any(keyword in text_lower for keyword in self.off_topic_keywords)
        
        # If has travel keywords, it's related
        if has_travel_keywords:
            return {"is_travel_related": True, "reason": None}
        
        # If has off-topic keywords and no travel keywords, it's off-topic
        if has_off_topic_keywords and not has_travel_keywords:
            return {
                "is_travel_related": False,
                "reason": "Contains non-travel topics (politics, programming, etc.)"
            }
        
        # For ambiguous cases, allow it (fail open)
        return {"is_travel_related": True, "reason": None}

    def _contains_sensitive_data(self, text: str) -> bool:
        """Check for sensitive data patterns in text."""
        sensitive_patterns = [
            "password", "credit card", "ssn", "social security",
            "api key", "secret", "token", "private key"
        ]
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in sensitive_patterns)

    # -------------------------
    # Fallbacks (fast & local)
    # -------------------------
    def _fallback_validation(self, text: str) -> Dict[str, Any]:
        """
        Very lightweight input checks: prompt-injection keywords & obvious off-topic markers.
        """
        text_lower = text.lower()
        
        # Check for prompt injection patterns - MORE COMPREHENSIVE
        injection_patterns = [
            "ignore previous", 
            "ignore all previous",
            "forget instructions",
            "forget previous",
            "forget all previous",
            "disregard previous",
            "disregard all previous",
            "system override", 
            "system prompt",
            "developer mode", 
            "admin access",
            "admin mode",
            "root access",
            "bypass safety",
            "bypass security", 
            "jailbreak",
            "enable admin",
            "enable developer",
            "override instructions",
            "new instructions"
        ]
        
        threats = sum(1 for pattern in injection_patterns if pattern in text_lower)
        
        # Check for extremely off-topic content
        very_off_topic = [
            "politics", "election", "medical advice", "legal advice",
            "financial advice", "write my homework", "write my essay"
        ]
        
        off_topic_threats = sum(1 for pattern in very_off_topic if pattern in text_lower)
        total_threats = threats + off_topic_threats
        is_safe = total_threats == 0
        
        return {
            "is_safe": is_safe,
            "risk_score": min(1.0, total_threats * 0.4),
            "threats_found": total_threats,
            "cleaned_input": text.strip(),
            "blocked_reason": "potential_injection" if threats > 0 else "off_topic" if off_topic_threats > 0 else None,
            "guardrail_active": False,  # Using fallback
        }

    def _fallback_output_validation(self, response_text: str) -> Dict[str, Any]:
        """
        Lightweight output checks for sensitive strings.
        """
        has_sensitive = self._contains_sensitive_data(response_text)

        return {
            "is_safe": not has_sensitive,
            "risk_score": 0.8 if has_sensitive else 0.1,
            "threats_found": 1 if has_sensitive else 0,
            "cleaned_input": response_text.strip(),
            "blocked_reason": "sensitive_data" if has_sensitive else None,
            "travel_compliant": True,
            "privacy_safe": not has_sensitive,
            "filtered_response": "[SENSITIVE DATA REDACTED]" if has_sensitive else response_text,
            "guardrail_active": False,  # Using fallback
        }