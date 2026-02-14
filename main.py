from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

from fastapi.middleware.cors import CORSMiddleware

from services.pdf_loader import extract_text_from_pdf_bytes
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
# MAIN API
# =============================

@app.post("/gbaiapi/ice_upload")
async def upload_pdf(file: UploadFile = File(...)):

    try:

        pdf_bytes = await file.read()

        if not pdf_bytes:

            return JSONResponse(
                status_code=400,
                content={"error": "Empty file"}
            )


        document_text = extract_text_from_pdf_bytes(pdf_bytes)

        if not document_text or len(document_text.strip()) < 50:

            return JSONResponse(
                status_code=400,
                content={"error": "Unable to extract text from PDF"}
            )


        # =============================
        # CLASSIFIER
        # =============================

        with open("templates/classifier.prompt", "r", encoding="utf-8") as f:
            classifier_prompt = f.read()


        classification = extract_using_template(
            document_text=document_text[:2000],
            prompt_template=classifier_prompt,
            doc_type="classifier",
        )


        doc_type = classification.get("document_type")


        if doc_type not in TEMPLATE_MAP:

            return JSONResponse(
                status_code=400,
                content={
                    "error": "Unknown document type",
                    "detected": doc_type,
                },
            )


        # =============================
        # LOAD EXTRACTION PROMPT
        # =============================

        with open(TEMPLATE_MAP[doc_type], "r", encoding="utf-8") as f:
            extraction_prompt = f.read()


        # =============================
        # BANK STATEMENT (FIXED)
        # =============================

        if doc_type == "bank_statement":

            # FIX: use transaction-based chunking
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
                "document_type": "bank_statement",
                "data": {
                    **bank_header,
                    "transactions": all_transactions,
                },
            }


        # =============================
        # PO / SO (UNCHANGED)
        # =============================

        extracted_json = extract_using_template(
            document_text=document_text,
            prompt_template=extraction_prompt,
            doc_type=doc_type,
        )


        return {
            "document_type": doc_type,
            "data": extracted_json,
        }


    except Exception as e:

        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


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
