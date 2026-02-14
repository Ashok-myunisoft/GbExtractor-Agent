import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = "gpt-4o-mini"
TEMPERATURE = 0

MAX_INPUT_CHARS = 4000
MAX_OUTPUT_TOKENS = 1500
CLASSIFIER_INPUT_LIMIT = 2000
CHUNK_SIZE = 2000
