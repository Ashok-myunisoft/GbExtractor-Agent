import runpod
import base64
import os
import sys
import json
from pathlib import Path
from services.pdf_loader import extract_text_from_pdf_bytes
from services.extractor import extract_using_template
# Importing from main to reuse the logic and constants
from main import chunk_text_by_transactions, TEMPLATE_MAP

# Add the current directory to path to ensure imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def validate_file_paths():
    """Validate that all required template files exist"""
    # Get absolute paths
    base_dir = Path(__file__).parent.absolute()
    classifier_path = base_dir / "templates" / "classifier.prompt"
    
    if not classifier_path.exists():
        # Try alternative locations
        alt_paths = [
            Path("/app/templates/classifier.prompt"),
            Path("/templates/classifier.prompt"),
            Path("templates/classifier.prompt")
        ]
        
        for alt_path in alt_paths:
            if alt_path.exists():
                return str(alt_path)
        
        raise FileNotFoundError(f"Classifier template not found. Checked: {classifier_path}, {alt_paths}")
    
    return str(classifier_path)

def safe_base64_decode(b64_string, max_size_mb=10):
    """Safely decode base64 with size validation"""
    # Check approximate size before decoding
    approx_size = len(b64_string) * 3 / 4  # Base64 is ~33% larger
    if approx_size > max_size_mb * 1024 * 1024:
        raise ValueError(f"File too large: ~{approx_size / (1024*1024):.1f}MB > {max_size_mb}MB limit")
    
    try:
        # Add padding if needed
        b64_string = b64_string.strip()
        padding = 4 - (len(b64_string) % 4)
        if padding != 4:
            b64_string += '=' * padding
        
        return base64.b64decode(b64_string)
    except Exception as e:
        raise ValueError(f"Invalid base64: {str(e)}")

def chunk_large_text(text, max_chars=10000):
    """Split very large text into chunks for processing"""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    # Try to split at sentence boundaries
    sentences = text.replace('\n', ' ').split('. ')
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_chars:
            current_chunk += sentence + '. '
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + '. '
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def handler(job):
    """
    RunPod Handler for GBExtractor Agent
    """
    job_id = job.get("id", "unknown")
    print(f"Starting job {job_id}")
    
    # Add heartbeat for long-running jobs
    def heartbeat():
        print(f"Job {job_id}: Still processing...")

    try:
        # Validate input structure
        if "input" not in job:
            return {"error": "Missing 'input' field in job", "status": "error"}
        
        input_data = job["input"]
        
        # Check for both possible input formats
        pdf_b64 = input_data.get("pdf_base64") or input_data.get("file_base64")
        
        if not pdf_b64:
            print(f"Job {job_id}: Missing pdf_base64")
            return {
                "error": "Missing PDF file. Provide 'pdf_base64' in input",
                "status": "error"
            }

        # Validate file paths at start
        try:
            classifier_path = validate_file_paths()
        except FileNotFoundError as e:
            print(f"Job {job_id}: {str(e)}")
            return {"error": str(e), "status": "error"}

        # Decode base64 with size limit
        try:
            pdf_bytes = safe_base64_decode(pdf_b64, max_size_mb=10)
            print(f"Job {job_id}: Decoded {len(pdf_bytes)} bytes")
        except ValueError as e:
            print(f"Job {job_id}: Base64 error - {str(e)}")
            return {"error": str(e), "status": "error"}

        # Extract text from PDF
        heartbeat()
        document_text = extract_text_from_pdf_bytes(pdf_bytes)

        if not document_text or len(document_text.strip()) < 50:
            print(f"Job {job_id}: Extraction failed or text too short")
            return {
                "error": "Unable to extract text from PDF or text too short",
                "status": "error"
            }

        print(f"Job {job_id}: Extracted {len(document_text)} characters")

        # =============================
        # CLASSIFIER
        # =============================
        heartbeat()
        with open(classifier_path, "r", encoding="utf-8") as f:
            classifier_prompt = f.read()

        # Use first 3000 chars for classification (increased from 2000)
        classification = extract_using_template(
            document_text=document_text[:3000],
            prompt_template=classifier_prompt,
            doc_type="classifier",
        )

        doc_type = classification.get("document_type")
        print(f"Job {job_id}: Detected type: {doc_type}")

        if not doc_type or doc_type not in TEMPLATE_MAP:
            return {
                "error": "Unknown document type",
                "detected": doc_type,
                "status": "error"
            }

        # =============================
        # LOAD EXTRACTION PROMPT
        # =============================
        template_file = TEMPLATE_MAP[doc_type]
        
        # Convert to absolute path
        if not os.path.isabs(template_file):
            template_file = os.path.join(os.path.dirname(__file__), template_file)
        
        if not os.path.exists(template_file):
            return {
                "error": f"Template file not found: {template_file}",
                "status": "error"
            }

        with open(template_file, "r", encoding="utf-8") as f:
            extraction_prompt = f.read()

        # =============================
        # BANK STATEMENT LOGIC
        # =============================
        if doc_type == "bank_statement":
            heartbeat()
            
            # Adjust chunk size based on document length
            max_transactions = 12
            if len(document_text) > 50000:
                max_transactions = 8  # Smaller chunks for very large docs
            
            chunks = chunk_text_by_transactions(
                document_text,
                max_transactions=max_transactions
            )
            
            print(f"Job {job_id}: Processing {len(chunks)} chunks")

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

            for i, chunk in enumerate(chunks):
                heartbeat()  # Heartbeat for each chunk
                print(f"Job {job_id}: Processing chunk {i+1}/{len(chunks)}")
                
                try:
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

                    transactions = result.get("transactions", [])
                    all_transactions.extend(transactions)
                    
                except Exception as chunk_error:
                    print(f"Job {job_id}: Error in chunk {i+1}: {str(chunk_error)}")
                    # Continue with next chunk instead of failing completely

            print(f"Job {job_id}: Extracted {len(all_transactions)} transactions")
            
            # Remove duplicates based on transaction ID or date+amount+description
            unique_transactions = []
            seen = set()
            for t in all_transactions:
                # Create a simple fingerprint for deduplication
                fingerprint = f"{t.get('date', '')}_{t.get('amount', '')}_{t.get('description', '')[:50]}"
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    unique_transactions.append(t)
            
            if len(unique_transactions) != len(all_transactions):
                print(f"Job {job_id}: Removed {len(all_transactions) - len(unique_transactions)} duplicate transactions")
            
            return {
                "document_type": "bank_statement",
                "status": "success",
                "data": {
                    **bank_header,
                    "transactions": unique_transactions,
                },
                "metadata": {
                    "chunks_processed": len(chunks),
                    "total_transactions": len(unique_transactions)
                }
            }

        # =============================
        # OTHER DOCUMENT TYPES (PO/SO/INVOICE)
        # =============================
        heartbeat()
        
        # For very large documents, chunk them for processing
        if len(document_text) > 15000:
            text_chunks = chunk_large_text(document_text, max_chars=10000)
            print(f"Job {job_id}: Processing {len(text_chunks)} text chunks")
            
            combined_result = {}
            for i, chunk in enumerate(text_chunks):
                heartbeat()
                print(f"Job {job_id}: Processing chunk {i+1}/{len(text_chunks)}")
                
                chunk_result = extract_using_template(
                    document_text=chunk,
                    prompt_template=extraction_prompt,
                    doc_type=doc_type,
                )
                
                # Merge results (simple merge - overwrite with later chunks)
                combined_result.update(chunk_result)
            
            extracted_json = combined_result
        else:
            extracted_json = extract_using_template(
                document_text=document_text,
                prompt_template=extraction_prompt,
                doc_type=doc_type,
            )

        print(f"Job {job_id}: Extraction complete")
        return {
            "document_type": doc_type,
            "status": "success",
            "data": extracted_json,
        }

    except Exception as e:
        print(f"Job {job_id}: Critical error - {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "error": str(e),
            "status": "error",
            "error_type": type(e).__name__
        }

# Optional: Add warmup handler for faster cold starts
def warmup():
    """Pre-load models/templates to speed up cold starts"""
    print("Warming up handler...")
    try:
        # Validate all template files exist
        validate_file_paths()
        
        # Check all extraction templates
        base_dir = Path(__file__).parent.absolute()
        for doc_type, template_path in TEMPLATE_MAP.items():
            if not os.path.isabs(template_path):
                template_path = os.path.join(base_dir, template_path)
            if os.path.exists(template_path):
                print(f"Found template for {doc_type}: {template_path}")
            else:
                print(f"Warning: Template not found for {doc_type}: {template_path}")
        
        print("Warmup complete")
    except Exception as e:
        print(f"Warmup error: {str(e)}")

if __name__ == "__main__":
    # Run warmup on cold start
    warmup()
    
    # Start the serverless handler
    runpod.serverless.start({"handler": handler})