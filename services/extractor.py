import json
import re
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from config import MODEL_NAME, TEMPERATURE, OPENAI_API_KEY


# =============================
# LIMIT SETTINGS
# =============================

MAX_INPUT_CHARS = 4000
MAX_OUTPUT_TOKENS = 1500
RETRY_COUNT = 3


# =============================
# LLM INITIALIZATION
# =============================

default_llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=TEMPERATURE,
    api_key=OPENAI_API_KEY,
    max_tokens=MAX_OUTPUT_TOKENS,
    timeout=60,
)

json_llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=0,
    api_key=OPENAI_API_KEY,
    max_tokens=MAX_OUTPUT_TOKENS,
    timeout=60,
    response_format={"type": "json_object"},
)


# =============================
# RETRY FUNCTION
# =============================

def invoke_with_retry(llm, message):

    for attempt in range(RETRY_COUNT):

        try:
            return llm.invoke(message)

        except Exception as e:

            if attempt == RETRY_COUNT - 1:
                raise e

            time.sleep(1)


# =============================
# SAFE JSON PARSER
# =============================

def safe_json_parse(text: str) -> dict:

    text = re.sub(r"```json|```", "", text).strip()

    if not text:
        raise ValueError("LLM returned empty response")

    try:
        return json.loads(text)

    except json.JSONDecodeError:

        # Try to recover truncated JSON safely
        last_brace = text.rfind("}")

        if last_brace != -1:

            truncated = text[:last_brace + 1]

            try:
                return json.loads(truncated)
            except:
                pass

        raise ValueError(
            "Invalid or truncated JSON from LLM due to token limit"
        )


# =============================
# MAIN EXTRACTION FUNCTION
# =============================

def extract_using_template(
    document_text: str,
    prompt_template: str,
    doc_type: str,
):

    # Limit input size
    document_text = document_text[:MAX_INPUT_CHARS]

    output_guard = """
IMPORTANT RULES:
- Respond ONLY in valid JSON
- No explanations
- No markdown
- Limit transactions to maximum 50 per response
"""

    final_prompt = f"""
{prompt_template}

{output_guard}

DOCUMENT TEXT:
{document_text}
"""

    message = [HumanMessage(content=final_prompt)]

    # Bank statement strict JSON mode
    if doc_type == "bank_statement":

        response = invoke_with_retry(
            json_llm,
            message
        )

        return safe_json_parse(response.content)

    # Other documents
    response = invoke_with_retry(
        default_llm,
        message
    )

    return safe_json_parse(response.content)