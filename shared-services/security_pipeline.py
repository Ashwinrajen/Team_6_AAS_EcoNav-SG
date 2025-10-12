# shared-services/security_pipeline.py

import os
import asyncio
import hashlib
from typing import Dict, Any
from pathlib import Path

from dotenv import load_dotenv

# NeMo Guardrails
from nemoguardrails import RailsConfig, LLMRails


class SecurityPipeline:
    """
    Security & policy guardrails with fast-fallback.
    - Toggle via GUARDRAILS_ENABLED=true|false
    - Per-call timeout via GUARDRAILS_TIMEOUT (seconds)
    - Uses NeMo Guardrails when enabled, otherwise falls back to local checks
    """

    def __init__(self):
        load_dotenv()

        # Feature flags / runtime knobs
        self.enabled: bool = os.getenv("GUARDRAILS_ENABLED", "true").lower() == "true"
        self.timeout_s: int = int(os.getenv("GUARDRAILS_TIMEOUT", "20"))

        # Initialize rails only if enabled
        if self.enabled:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not found (required when GUARDRAILS_ENABLED=true).")

            config_path = Path(__file__).parent / "guardrails_config"
            config = RailsConfig.from_path(str(config_path))
            self.rails = LLMRails(config)
            print(f"[SecurityPipeline] NeMo Guardrails enabled (timeout={self.timeout_s}s)")
        else:
            self.rails = None
            print("[SecurityPipeline] NeMo Guardrails disabled via GUARDRAILS_ENABLED=false")

    # -------------------------
    # Public API
    # -------------------------
    async def validate_input(self, text: str, user_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Validate user input. When disabled or on error/timeout, returns a safe fallback.
        """
        if not self.enabled or self.rails is None:
            return self._fallback_validation(text)

        try:
            response = await self._with_timeout(
                self.rails.generate_async(messages=[{"role": "user", "content": text}])
            )
            content = (response or {}).get("content", "") if isinstance(response, dict) else ""
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
            print(f"[SecurityPipeline] validate_input error/timeout: {e}")
            return self._fallback_validation(text)

    async def validate_output(self, response_text: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        Validate assistant output. When disabled or on error/timeout, returns a safe fallback.
        """
        if not self.enabled or self.rails is None:
            return self._fallback_output_validation(response_text)

        try:
            messages = [
                {"role": "user", "content": "Help me plan a trip"},
                {"role": "assistant", "content": response_text}
            ]
            validation_response = await self._with_timeout(self.rails.generate_async(messages=messages))
            content = (validation_response or {}).get("content", "") if isinstance(validation_response, dict) else ""
            is_blocked = "I apologize, but I cannot provide that information" in content

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
                "guardrail_active": True,
            }
        except Exception as e:
            print(f"[SecurityPipeline] validate_output error/timeout: {e}")
            return self._fallback_output_validation(response_text)

    def generate_content_hash(self, content: str) -> str:
        """Small helper for integrity/debugging."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # -------------------------
    # Internals
    # -------------------------
    async def _with_timeout(self, coro):
        """
        Wrap any awaitable with asyncio timeout defined by GUARDRAILS_TIMEOUT.
        """
        return await asyncio.wait_for(coro, timeout=self.timeout_s)

    def _build_validation_result(
        self,
        is_safe: bool,
        risk_score: float,
        text: str,
        response_content: str,
        blocked_reason: str | None = None,
    ) -> Dict[str, Any]:
        """Standardized validation result."""
        return {
            "is_safe": is_safe,
            "risk_score": risk_score,
            "threats_found": 0 if is_safe else 1,
            "cleaned_input": text.strip(),
            "guardrail_response": response_content,
            "blocked_reason": blocked_reason,
        }

    # -------------------------
    # Fallbacks (fast & local)
    # -------------------------
    def _fallback_validation(self, text: str) -> Dict[str, Any]:
        """
        Very lightweight input checks: prompt-injection keywords & obvious off-topic markers.
        """
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
        """
        Lightweight output checks for sensitive strings.
        """
        sensitive_data = ["password", "credit card", "ssn", "social security"]
        has_sensitive = any(pattern in response_text.lower() for pattern in sensitive_data)

        return {
            "is_safe": not has_sensitive,
            "risk_score": 0.8 if has_sensitive else 0.1,
            "threats_found": 1 if has_sensitive else 0,
            "cleaned_input": response_text.strip(),
            "guardrail_response": "Fallback validation used",
            "blocked_reason": "sensitive_data" if has_sensitive else None,
            "travel_compliant": True,
            "privacy_safe": not has_sensitive,
            "filtered_response": "[SENSITIVE DATA REDACTED]" if has_sensitive else response_text,
            "guardrail_active": False,
        }
