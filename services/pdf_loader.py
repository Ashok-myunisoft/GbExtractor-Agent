from pypdf import PdfReader
from pdf2image import convert_from_bytes
from PIL import Image
import base64
import httpx
import os
import xml.etree.ElementTree as ET
from io import BytesIO


MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = "pixtral-12b"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


def image_to_base64(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _call_mistral_ocr(img_b64: str) -> str:
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all readable text from this document image."},
                    {
                        "type": "image_url",
                        "image_url": f"data:image/png;base64,{img_b64}",
                    },
                ],
            }
        ],
    }
    response = httpx.post(MISTRAL_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    text = ""

    # ---------- STEP 1: Native PDF text (from memory) ----------
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception:
        text = ""

    # ---------- STEP 2: OCR fallback (from memory) ----------
    if not text or len(text.strip()) < 300:
        images = convert_from_bytes(pdf_bytes)
        ocr_text = ""

        for img in images[:5]:
            img_b64 = image_to_base64(img)
            ocr_text += _call_mistral_ocr(img_b64) + "\n"

        text = ocr_text

    return text


def extract_text_from_image_bytes(image_bytes: bytes) -> str:
    img = Image.open(BytesIO(image_bytes))
    img_b64 = image_to_base64(img)
    return _call_mistral_ocr(img_b64)


def extract_text_from_xml_bytes(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse XML: {e}")

    lines = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        value = (elem.text or "").strip()
        if value:
            lines.append(f"{tag}: {value}")

    return "\n".join(lines)
