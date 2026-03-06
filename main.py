from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Annotated

from services.pdf_loader import (
    extract_text_from_pdf_bytes,
    extract_text_from_image_bytes,
    extract_text_from_xml_bytes,
)
from services.extractor import extract_using_template

import re


app = FastAPI(title="PDF → JSON Extractor")


# =============================
# CORS
# =============================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================
# TEMPLATE MAP
# =============================

TEMPLATE_MAP = {
    "purchase_order": "templates/purchase_order.prompt",
    "sales_order": "templates/sales_order.prompt",
    "bank_statement": "templates/bank_statement.prompt",
    "payslip": "templates/payslip.prompt",
    "activity_register": "templates/activity_register.prompt",
    "visiting_card": "templates/visiting_card.prompt",
    "invoice": "templates/universal.prompt",
    "receipt": "templates/universal.prompt",
}


# =============================
# SAFE CHUNK FUNCTION (FIXED)
# Splits by transaction count instead of characters
# =============================

DATE_PATTERN = r"\d{2}[/.-]\d{2}[/.-]\d{4}|\d{2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s\d{4}"


def chunk_text_by_transactions(text: str, max_transactions: int = 12):

    lines = text.splitlines()

    chunks = []
    current_chunk = ""
    transaction_count = 0

    for line in lines:

        # Detect new transaction start (using updated regex)
        if re.match(DATE_PATTERN, line.strip()):

            # If we reached the limit, split NOW before adding the new transaction
            # This ensures the previous chunk ends cleanly with full transactions
            if transaction_count >= max_transactions:
                chunks.append(current_chunk)
                current_chunk = ""
                transaction_count = 0

            transaction_count += 1

        current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk)

    return chunks


# =============================
# FILE TYPE DETECTION
# =============================

def detect_file_type(filename: str, content_type: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return "pdf"
    if ext == "xml":
        return "xml"
    if ext in ("jpg", "jpeg", "png"):
        return "image"
    # Fallback to content-type header
    if "pdf" in content_type:
        return "pdf"
    if "xml" in content_type:
        return "xml"
    if "image" in content_type:
        return "image"
    return "unsupported"


# =============================
# SINGLE FILE PROCESSOR
# =============================

async def process_single_file(file: UploadFile) -> dict:

    file_name = file.filename or "unknown"

    try:

        file_bytes = await file.read()

        if not file_bytes:
            return {"file_name": file_name, "error": "Empty file"}

        # ---------- Detect and extract text ----------
        file_type = detect_file_type(file_name, file.content_type or "")

        if file_type == "pdf":
            document_text = extract_text_from_pdf_bytes(file_bytes)
        elif file_type == "xml":
            document_text = extract_text_from_xml_bytes(file_bytes)
        elif file_type == "image":
            document_text = extract_text_from_image_bytes(file_bytes)
        else:
            return {"file_name": file_name, "error": f"Unsupported file type: {file_name.rsplit('.', 1)[-1] if '.' in file_name else 'unknown'}"}

        if not document_text or len(document_text.strip()) < 50:
            return {"file_name": file_name, "error": "Unable to extract text from file"}

        # ---------- Classify ----------
        with open("templates/classifier.prompt", "r", encoding="utf-8") as f:
            classifier_prompt = f.read()

        classification = extract_using_template(
            document_text=document_text[:5000],
            prompt_template=classifier_prompt,
            doc_type="classifier",
        )

        doc_type = classification.get("document_type")

        # =============================
        # BANK STATEMENT (UNCHANGED)
        # =============================

        if doc_type == "bank_statement":

            with open(TEMPLATE_MAP["bank_statement"], "r", encoding="utf-8") as f:
                extraction_prompt = f.read()

            chunks = chunk_text_by_transactions(
                document_text,
                max_transactions=12
            )

            bank_header = {
                "bank_name": None,
                "account_number": None,
                "account_holder_name": None,
                "ifsc_code": None,
                "branch_name": None,
                "statement_period": {
                    "from": None,
                    "to": None,
                },
                "opening_balance": None,
                "closing_balance": None,
            }

            all_transactions = []

            for chunk in chunks:

                result = extract_using_template(
                    document_text=chunk,
                    prompt_template=extraction_prompt,
                    doc_type="bank_statement",
                )

                # Merge header safely
                for key in bank_header:

                    if key == "statement_period":

                        if result.get("statement_period"):

                            if not bank_header["statement_period"]["from"]:
                                bank_header["statement_period"]["from"] = result["statement_period"].get("from")

                            if not bank_header["statement_period"]["to"]:
                                bank_header["statement_period"]["to"] = result["statement_period"].get("to")

                    else:

                        if bank_header[key] is None and result.get(key) is not None:
                            bank_header[key] = result[key]

                all_transactions.extend(
                    result.get("transactions", [])
                )

            return {
                "file_name": file_name,
                "document_type": "bank_statement",
                "extracted_data": {
                    **bank_header,
                    "transactions": all_transactions,
                },
            }

        # =============================
        # KNOWN TYPES (PO / SO / PAYSLIP / ACTIVITY / VISITING CARD / INVOICE / RECEIPT)
        # =============================

        if doc_type in TEMPLATE_MAP:

            with open(TEMPLATE_MAP[doc_type], "r", encoding="utf-8") as f:
                extraction_prompt = f.read()

            extracted_json = extract_using_template(
                document_text=document_text,
                prompt_template=extraction_prompt,
                doc_type=doc_type,
            )

            return {
                "file_name": file_name,
                "document_type": doc_type,
                "extracted_data": extracted_json,
            }

        # =============================
        # UNKNOWN / UNIVERSAL FALLBACK
        # =============================

        with open("templates/universal.prompt", "r", encoding="utf-8") as f:
            universal_prompt = f.read()

        extracted_json = extract_using_template(
            document_text=document_text,
            prompt_template=universal_prompt,
            doc_type="unknown",
        )

        inferred_type = extracted_json.pop("document_type", None) or "unknown"

        return {
            "file_name": file_name,
            "document_type": inferred_type,
            "extracted_data": extracted_json,
        }

    except Exception as e:

        return {
            "file_name": file_name,
            "error": str(e),
        }


# =============================
# MAIN API
# =============================

@app.post("/gbaiapi/ice_upload")
async def upload_pdf(files: Annotated[List[UploadFile], File()]):

    results = []

    for file in files:
        result = await process_single_file(file)
        results.append(result)

    return {"files": results}


# =============================
# RUN SERVER
# =============================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8005
    )
