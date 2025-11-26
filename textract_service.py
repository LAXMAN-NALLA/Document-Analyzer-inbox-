from dotenv import load_dotenv
load_dotenv()

import os
import logging
import boto3
import pdfplumber
import pandas as pd
from docx import Document
from PIL import Image
from io import BytesIO
from botocore.exceptions import ClientError, NoRegionError, NoCredentialsError

# Initialize AWS Textract client conditionally
textract_client = None
try:
    if (os.getenv("AWS_ACCESS_KEY_ID") and 
        os.getenv("AWS_SECRET_ACCESS_KEY") and 
        os.getenv("AWS_REGION")):
        
        textract_client = boto3.client(
            "textract",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION")
        )
        logging.info("AWS Textract client initialized successfully")
    else:
        logging.warning("AWS credentials not found. Textract OCR will not be available.")
        logging.warning("Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION environment variables")
except Exception as e:
    logging.warning(f"Failed to initialize AWS Textract client: {e}")
    textract_client = None

def extract_text_from_upload(file_path: str, file_bytes: bytes) -> str:
    """Extracts text from various formats. Falls back to AWS Textract OCR for scanned documents/images."""

    ext = file_path.lower()

    # 1. Extract text from digital PDFs
    if ext.endswith(".pdf"):
        try:
            with pdfplumber.open(file_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            if full_text.strip():
                logging.info("Successfully extracted text using pdfplumber.")
                return full_text.strip()
        except Exception as e:
            logging.warning(f"pdfplumber failed: {e}. Falling back to Textract.")

    # 2. Extract text from Word documents (.docx)
    elif ext.endswith(".docx"):
        try:
            doc = Document(file_path)
            full_text = "\n".join([para.text for para in doc.paragraphs])
            if full_text.strip():
                logging.info("Successfully extracted text from DOCX.")
                return full_text.strip()
        except Exception as e:
            logging.warning(f"python-docx failed: {e}. Falling back to Textract.")

    # 3. Extract from Excel and CSV (.xlsx, .csv)
    elif ext.endswith(".xlsx") or ext.endswith(".csv"):
        try:
            if ext.endswith(".csv"):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            full_text = df.to_string(index=False)
            if full_text.strip():
                logging.info("Successfully extracted text from Excel/CSV.")
                return full_text.strip()
        except Exception as e:
            logging.warning(f"pandas failed to extract table: {e}. Falling back to Textract.")

    # 4. Extract from plain text files (.txt)
    elif ext.endswith(".txt"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                full_text = f.read()
            if full_text.strip():
                logging.info("Successfully extracted text from TXT file.")
                return full_text.strip()
        except Exception as e:
            logging.warning(f"Failed to read TXT file: {e}. Falling back to Textract.")

    # 5. Extract from images (.png, .jpg, .jpeg)
    elif ext.endswith((".png", ".jpg", ".jpeg")):
        try:
            image = Image.open(BytesIO(file_bytes))
            if image.mode != "RGB":
                image = image.convert("RGB")
            logging.info("Image opened successfully. Using Textract.")
            # Skip PIL OCR — go directly to Textract for better multilingual OCR
        except Exception as e:
            logging.warning(f"PIL failed to open image: {e}. Falling back to Textract.")

    # 6. Fallback: AWS Textract (for scans, images, poor PDFs, RTF, PPTX, ODT)
    if textract_client is not None:
        logging.info("Using AWS Textract for OCR extraction.")
        try:
            # Validate file size for Textract (max 10MB)
            if len(file_bytes) > 10 * 1024 * 1024:
                logging.error(f"File too large for Textract: {len(file_bytes)} bytes (max 10MB)")
                return ""
            
            # Validate file format for Textract
            if not ext.endswith(('.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
                logging.warning(f"File format {ext} may not be supported by Textract")
            
            response = textract_client.detect_document_text(
                Document={"Bytes": file_bytes}
            )
            
            if 'Blocks' not in response:
                logging.warning("No text blocks found in Textract response")
                return ""
                
            text_blocks = [block['Text'] for block in response['Blocks'] if block['BlockType'] == 'LINE']
            if not text_blocks:
                logging.warning("No text lines found in Textract response")
                return ""
                
            extracted_text = "\n".join(text_blocks)
            logging.info(f"Successfully extracted {len(extracted_text)} characters using Textract")
            return extracted_text
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidParameterException':
                logging.error(f"AWS Textract invalid parameters: {e}")
                return ""
            elif error_code == 'DocumentTooLargeException':
                logging.error(f"Document too large for Textract: {e}")
                return ""
            elif error_code == 'UnsupportedDocumentException':
                logging.error(f"Unsupported document format for Textract: {e}")
                return ""
            else:
                logging.error(f"AWS Textract API error ({error_code}): {e}")
                return ""
        except Exception as e:
            logging.error(f"Unexpected Textract error: {e}")
            return ""
    else:
        logging.error("AWS Textract not available. Cannot process scanned documents or images.")
        logging.error("Please configure AWS credentials and region to enable OCR functionality.")
        return ""
