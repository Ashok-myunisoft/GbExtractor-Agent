
import sys
import os
import base64
import json
from unittest.mock import MagicMock, patch

# 1. Mock 'runpod' before importing handler
sys.modules["runpod"] = MagicMock()
sys.modules["runpod.serverless"] = MagicMock()

# 2. Mock services to avoid real API calls and dependency issues
# We need to mock them in sys.modules so that when 'handler' (and 'main') imports them, they get the mocks.
# However, 'main.py' imports 'services.pdf_loader' and 'services.extractor'.
# We need to make sure these exist in sys.modules.

mock_pdf_loader = MagicMock()
mock_extractor = MagicMock()

sys.modules["services"] = MagicMock()
sys.modules["services.pdf_loader"] = mock_pdf_loader
sys.modules["services.extractor"] = mock_extractor

# Define the mock functions
def mock_extract_text(pdf_bytes):
    return "Sample PDF Text\nDate: 01/01/2023\nTransaction 1\nDate: 02/01/2023\nTransaction 2"

mock_pdf_loader.extract_text_from_pdf_bytes.side_effect = mock_extract_text

def mock_extract_template(document_text, prompt_template, doc_type):
    if doc_type == "classifier":
        return {"document_type": "bank_statement"}
    elif doc_type == "bank_statement":
        return {
            "statement_period": {"from": "01/01/2023", "to": "31/01/2023"},
            "transactions": [{"date": "01/01/2023", "desc": "Txn 1"}, {"date": "02/01/2023", "desc": "Txn 2"}]
        }
    return {}

mock_extractor.extract_using_template.side_effect = mock_extract_template

# 3. Create dummy templates if they don't exist, or mock open()
# handler.py reads templates/classifier.prompt and TEMPLATE_MAP files.
# We can use 'pyfakefs' or just mock 'builtins.open'.
# Let's mock 'builtins.open' for the template reading.

# 4. Import handler
try:
    import handler
except ImportError as e:
    print(f"Error importing handler: {e}")
    sys.exit(1)

# 5. Define the test
def test_handler():
    print("Running handler test...")

    # Create a dummy job input
    # base64 encoded "dummy"
    pdf_b64 = base64.b64encode(b"dummy pdf content").decode("utf-8")
    
    job = {
        "input": {
            "pdf_base64": pdf_b64
        }
    }

    # Mock open to return dummy template content
    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        mock_file = MagicMock()
        mock_file.read.return_value = "Dummy Template Content"
        mock_file.__enter__.return_value = mock_file
        mock_open.return_value = mock_file

        # Check if templates directories exist, if not, os.path.exists might fail in handler
        # handler checks: if not os.path.exists(classifier_path): return ...
        # We need to mock os.path.exists to return True for templates
        
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = True
            
            # Run handler
            result = handler.handler(job)
            
            print("\nHandler Result:")
            print(json.dumps(result, indent=2))
            
            # Assertions
            if result.get("error"):
                print("FAILED: Handler returned error.")
            elif result.get("document_type") == "bank_statement":
                print("SUCCESS: Identified bank_statement and returned data.")
            else:
                print("FAILED: Unexpected result.")

if __name__ == "__main__":
    test_handler()
