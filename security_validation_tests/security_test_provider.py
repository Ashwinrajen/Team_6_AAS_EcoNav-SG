#!/usr/bin/env python3
import os
import sys
import asyncio
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared-services'))
os.environ.setdefault("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "test-key"))
os.environ.setdefault("GUARDRAILS_ENABLED", "true")
os.environ.setdefault("GUARDRAILS_TIMEOUT", "5")
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

from security_pipeline import SecurityPipeline

# Initialize pipeline once at module level
pipeline = SecurityPipeline()

def call_api(prompt: str, options=None, context=None):
    """Promptfoo provider function - must be at module level"""
    try:
        vars_dict = context.get('vars', {}) if context else {}
        user_input = vars_dict.get('user_input', prompt)
        test_category = vars_dict.get('test_category', 'general')
        
        if test_category == 'output_validation' or 'OUTPUT_TEST:' in user_input:
            result = asyncio.run(pipeline.validate_output(user_input.replace('OUTPUT_TEST:', '').strip()))
        else:
            result = asyncio.run(pipeline.validate_input(user_input))
        
        # Return plain dict - promptfoo will serialize it
        return {"output": result}
    except Exception as e:
        return {"output": {"is_safe": True, "error": str(e)}}