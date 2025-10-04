# shared-services/transparency.py

from typing import Dict, Any
from datetime import datetime

class TransparencyEngine:
    """Simplified transparency and trust system"""
    
    def __init__(self):
        self.explanations: Dict[str, str] = {}
    
    def calculate_trust_score(self, session_data: Dict[str, Any], user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate trust score based on multiple factors"""
        
        # Calculate individual factor scores
        user_score = self._calculate_user_score(user_context)
        session_score = self._calculate_session_score(session_data)
        security_score = session_data.get("trust_score", 1.0)
        
        # Weighted average (security has higher weight)
        weights = {"user": 0.3, "session": 0.3, "security": 0.4}
        trust_score = (
            user_score * weights["user"] + 
            session_score * weights["session"] + 
            security_score * weights["security"]
        )
        
        return {
            "trust_score": round(trust_score, 2),
            "trust_level": self._get_trust_level(trust_score),
            "factors": {
                "user_history": round(user_score, 2),
                "session_behavior": round(session_score, 2),
                "security_status": round(security_score, 2)
            },
            "calculated_at": datetime.now().isoformat()
        }
    
    def _calculate_user_score(self, user_context: Dict[str, Any]) -> float:
        """Calculate score based on user history"""
        interaction_count = user_context.get("interaction_count", 0)
        trust_level = user_context.get("trust_level", "new")
        
        # Progressive scoring based on interactions
        history_score = min(1.0, interaction_count / 10.0)
        
        # Trust level multipliers
        multipliers = {"new": 0.5, "trusted": 0.8, "verified": 1.0}
        
        return history_score * multipliers.get(trust_level, 0.5)
    
    def _calculate_session_score(self, session_data: Dict[str, Any]) -> float:
        """Calculate score based on current session behavior"""
        error_count = session_data.get("error_count", 0)
        success_metrics = session_data.get("success_metrics", {})
        
        # Positive activity score
        responses = success_metrics.get("responses_generated", 0)
        coordinations = success_metrics.get("coordinations_successful", 0)
        positive_score = min(1.0, (responses + coordinations) / 5.0)
        
        # Error penalty (capped at 50% reduction)
        error_penalty = min(0.5, error_count * 0.15)
        
        return max(0.1, positive_score - error_penalty)  # Minimum 0.1 score
    
    def _get_trust_level(self, score: float) -> str:
        """Convert numeric score to categorical trust level"""
        if score >= 0.8: return "high"
        elif score >= 0.6: return "medium"  
        elif score >= 0.4: return "low"
        else: return "untrusted"
    
    def explain_decision(self, decision_id: str, reasoning_data: Dict[str, Any]) -> str:
        """Generate human-readable decision explanation"""
        
        # Extract reasoning components
        plan = reasoning_data.get("coordination_plan", {})
        extracted = reasoning_data.get("extracted_info", {})
        intent = reasoning_data.get("intent", "unknown")
        
        # Build explanation based on available data
        explanation_parts = ["I processed your request because:"]
        
        # Add intent-based reasoning
        if intent == "planning":
            explanation_parts.append("you're planning travel")
        elif intent == "greeting":
            explanation_parts.append("you greeted me")
        else:
            explanation_parts.append("I detected a travel-related query")
        
        # Add coordination reasoning if available
        if plan:
            if plan.get("needs_multiple_agents"):
                explanation_parts.append("your request requires multiple specialized agents")
            elif plan.get("complexity") == "high":
                explanation_parts.append("your request involves complex travel planning")
        
        # Add extracted information
        if extracted:
            info_items = []
            for key in ["destination", "dates", "budget"]:
                if extracted.get(key):
                    info_items.append(f"{key}: {extracted[key]}")
            
            if info_items:
                explanation_parts.append(f"I identified {', '.join(info_items)}")
        
        # Combine explanation parts
        explanation = ". ".join(explanation_parts) + "."
        
        # Store for future reference
        self.explanations[decision_id] = explanation
        return explanation
    
    def get_transparency_report(self, session_id: str) -> Dict[str, Any]:
        """Generate comprehensive transparency report"""
        return {
            "session_id": session_id,
            "report_generated_at": datetime.now().isoformat(),
            "transparency_metrics": {
                "explanations_provided": len(self.explanations),
                "transparency_level": "full",
                "decision_tracking": "enabled"
            },
            "available_data": {
                "trust_scores": "available",
                "decision_explanations": "available", 
                "session_analytics": "available"
            }
        }
    
    def clear_old_explanations(self, max_age_hours: int = 24) -> int:
        """Clean up old explanations to prevent memory bloat"""
        # Simple cleanup - in production, you'd check timestamps
        if len(self.explanations) > 100:
            # Keep only the 50 most recent
            sorted_keys = sorted(self.explanations.keys())
            old_keys = sorted_keys[:-50]
            for key in old_keys:
                del self.explanations[key]
            return len(old_keys)
        return 0