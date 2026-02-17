
import runpod
import base64
import os
from services.pdf_loader import extract_text_from_pdf_bytes
from services.extractor import extract_using_template
# Imporing from main to reuse the logic and constants
from main import chunk_text_by_transactions, TEMPLATE_MAP

def handler(job):
    """
    RunPod Handler for GBExtractor Agent
    """
    try:
        input_data = job["input"]

        # Expecting the PDF file as a base64 encoded string in "pdf_base64"
        pdf_b64 = input_data.get("pdf_base64")
        
        if not pdf_b64:
            return {"error": "Missing 'pdf_base64' in input"}

        try:
            pdf_bytes = base64.b64decode(pdf_b64)
        except Exception:
            return {"error": "Invalid base64 string provided"}

        # Logic replicated from main.py upload_pdf
        document_text = extract_text_from_pdf_bytes(pdf_bytes)

        if not document_text or len(document_text.strip()) < 50:
            return {"error": "Unable to extract text from PDF or text too short"}

        # =============================
        # CLASSIFIER
        # =============================
        classifier_path = "templates/classifier.prompt"
        if not os.path.exists(classifier_path):
             return {"error": f"Classifier template not found at {classifier_path}"}

        with open(classifier_path, "r", encoding="utf-8") as f:
            classifier_prompt = f.read()

        classification = extract_using_template(
            document_text=document_text[:2000],
            prompt_template=classifier_prompt,
            doc_type="classifier",
        )

        doc_type = classification.get("document_type")

        if doc_type not in TEMPLATE_MAP:
            return {
                "error": "Unknown document type",
                "detected": doc_type,
            }

        # =============================
        # LOAD EXTRACTION PROMPT
        # =============================
        template_file = TEMPLATE_MAP[doc_type]
        if not os.path.exists(template_file):
            return {"error": f"Template file not found: {template_file}"}

        with open(template_file, "r", encoding="utf-8") as f:
            extraction_prompt = f.read()

        # =============================
        # BANK STATEMENT LOGIC
        # =============================
        if doc_type == "bank_statement":
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
        # PO / SO LOGIC
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
        return {"error": str(e)}

runpod.serverless.start({"handler": handler})
