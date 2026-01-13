from pypdf import PdfReader
from pdf2image import convert_from_bytes
import base64
import httpx
import os
from io import BytesIO


MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = "pixtral-12b"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


def image_to_base64(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


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

        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json",
        }

        for img in images[:5]:
            img_b64 = image_to_base64(img)

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

            ocr_text += response.json()["choices"][0]["message"]["content"] + "\n"

        text = ocr_text

    return text
