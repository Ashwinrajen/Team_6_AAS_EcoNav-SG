import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
    AGENT_NAME = os.getenv("AGENT_NAME", "UserOrchestrator")
    DEBUG = os.getenv("DEBUG", "false").lower() == "false"
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "300"))
    CREWAI_TRACING_ENABLED = os.getenv("CREWAI_TRACING_ENABLED", "true").lower() == "true"

config = Config()