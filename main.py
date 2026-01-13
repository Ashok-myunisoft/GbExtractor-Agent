from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

from services.pdf_loader import extract_text_from_pdf_bytes
from services.extractor import extract_using_template


from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI( title="PDF → JSON Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          
    allow_credentials=False,      
    allow_methods=["*"],
    allow_headers=["*"],
)


TEMPLATE_MAP = {
    "purchase_order": "templates/purchase_order.prompt",
    "sales_order": "templates/sales_order.prompt",
    "bank_statement": "templates/bank_statement.prompt",
}


def chunk_text(text: str, max_chars: int = 4000):
    chunks, current = [], ""
    for line in text.splitlines():
        if len(current) + len(line) > max_chars:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks


@app.post("/gbaiapi/ice_upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        # 1️⃣ Read PDF bytes
        pdf_bytes = await file.read()
        if not pdf_bytes:
            return JSONResponse(status_code=400, content={"error": "Empty file"})

        # 2️⃣ Extract text
        document_text = extract_text_from_pdf_bytes(pdf_bytes)
        if not document_text or len(document_text.strip()) < 50:
            return JSONResponse(
                status_code=400,
                content={"error": "Unable to extract text from PDF"}
            )

        # 3️⃣ Detect document type
        with open("templates/classifier.prompt", "r", encoding="utf-8") as f:
            classifier_prompt = f.read()

        classification = extract_using_template(
            document_text=document_text,
            prompt_template=classifier_prompt,
            doc_type="classifier",
        )

        doc_type = classification.get("document_type")
        if doc_type not in TEMPLATE_MAP:
            return JSONResponse(
                status_code=400,
                content={"error": "Unknown document type", "detected": doc_type},
            )

        # 4️⃣ Load extraction prompt
        with open(TEMPLATE_MAP[doc_type], "r", encoding="utf-8") as f:
            extraction_prompt = f.read()

        # ==================================================
        # 5️⃣ BANK STATEMENT (HEADER + TRANSACTIONS)
        # ==================================================
        if doc_type == "bank_statement":
            chunks = chunk_text(document_text)

            bank_header = {
                "bank_name": None,
                "account_number": None,
                "account_holder_name": None,
                "ifsc_code": None,
                "branch_name": None,
                "statement_period": {"from": None, "to": None},
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

                # Merge header (first non-null wins)
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

                all_transactions.extend(result.get("transactions", []))

            return {
                "document_type": "bank_statement",
                "data": {
                    **bank_header,
                    "transactions": all_transactions,
                },
            }

        # ==================================================
        # 6️⃣ PO / SO (SINGLE PASS)
        # ==================================================
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
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
