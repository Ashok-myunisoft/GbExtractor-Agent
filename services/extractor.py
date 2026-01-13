import json
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config import MODEL_NAME, TEMPERATURE, OPENAI_API_KEY


default_llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=TEMPERATURE,
    api_key=OPENAI_API_KEY,
)

json_llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=0,
    api_key=OPENAI_API_KEY,
    response_format={"type": "json_object"},
)


def safe_json_parse(text: str) -> dict:
    text = re.sub(r"```json|```", "", text).strip()
    if not text:
        raise ValueError("LLM returned empty response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError("Invalid JSON from LLM")


def extract_using_template(
    document_text: str,
    prompt_template: str,
    doc_type: str,
):
    final_prompt = f"""
{prompt_template}

DOCUMENT TEXT:
{document_text}
"""

    # Bank uses strict JSON mode
    if doc_type == "bank_statement":
        json_guard = (
            "IMPORTANT: Respond ONLY in valid JSON. "
            "No explanations, no markdown.\n\n"
        )
        response = json_llm.invoke(
            [HumanMessage(content=json_guard + final_prompt)]
        )
        return safe_json_parse(response.content)

    # PO / SO / Classifier
    response = default_llm.invoke(
        [HumanMessage(content=final_prompt)]
    )
    return safe_json_parse(response.content)
