import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
    AGENT_NAME = os.getenv("AGENT_NAME")
    DEBUG = os.getenv("DEBUG")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS"))
    CREWAI_TRACING_ENABLED = os.getenv("CREWAI_TRACING_ENABLED")

config = Config()