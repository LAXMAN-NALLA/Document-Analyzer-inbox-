import os
import tempfile
import logging
import asyncio
import time
import signal
import sys
import traceback
import psutil
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
import textract_service
import openai_service

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Document Analysis API")

# Enhanced logging configuration with detailed formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [PID:%(process)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Log startup information
logger.info("=" * 80)
logger.info("Application Starting")
logger.info(f"Python version: {sys.version}")
logger.info(f"Process ID: {os.getpid()}")
logger.info(f"Max file size: {os.getenv('MAX_FILE_SIZE_MB', '100')} MB")
logger.info(f"Max total size: {os.getenv('MAX_TOTAL_SIZE_MB', '2000')} MB")
logger.info(f"Request timeout: {os.getenv('REQUEST_TIMEOUT_SECONDS', '1800')} seconds")
logger.info("=" * 80)

# File size limits (in bytes) - configurable via environment variables
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "100")) * 1024 * 1024  # Default 100MB per file
MAX_TOTAL_SIZE = int(os.getenv("MAX_TOTAL_SIZE_MB", "2000")) * 1024 * 1024  # Default 2GB total for 30 files
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "30"))  # Default 30 files per request

# Request timeout (in seconds) - configurable via environment variables
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "1800"))  # 30 minutes default

# Allowed file extensions
ALLOWED_EXTENSIONS = [".pdf", ".docx", ".csv", ".xlsx", ".png", ".jpg", ".jpeg", ".txt", ".rtf", ".pptx", ".odt"]

# Memory monitoring function (defined early so it can be used during startup)
def log_memory_usage(context: str = ""):
    """Log current memory usage for debugging."""
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        memory_percent = process.memory_percent()
        logger.info(f"Memory usage {context}: {memory_mb:.2f} MB ({memory_percent:.1f}%)")
    except Exception as e:
        logger.warning(f"Could not get memory info: {e}")

# Log memory at startup
log_memory_usage("(startup)")

# Global request timeout handler
class RequestTimeoutHandler:
    def __init__(self, timeout_seconds: int):
        self.timeout_seconds = timeout_seconds
        self.start_time = None
    
    def start(self):
        self.start_time = time.time()
    
    def check_timeout(self):
        if self.start_time and (time.time() - self.start_time) > self.timeout_seconds:
            raise HTTPException(status_code=408, detail="Request timeout exceeded")
    
    def get_remaining_time(self):
        if self.start_time:
            return max(0, self.timeout_seconds - (time.time() - self.start_time))
        return self.timeout_seconds

# Global exception handler for request entity too large
@app.exception_handler(413)
async def request_entity_too_large_handler(request: Request, exc: HTTPException):
    logger.warning(f"Request entity too large: {request.url}")
    log_memory_usage("(413 error)")
    return JSONResponse(
        status_code=413,
        content={
            "error": "Request Entity Too Large",
            "detail": "The uploaded file(s) exceed the maximum allowed size.",
            "max_file_size_mb": MAX_FILE_SIZE // (1024*1024),
            "max_total_size_mb": MAX_TOTAL_SIZE // (1024*1024)
        }
    )

# Global exception handler for all unhandled exceptions
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and log them with full traceback."""
    error_id = time.time()
    logger.error("=" * 80)
    logger.error(f"UNHANDLED EXCEPTION [{error_id}]")
    logger.error(f"URL: {request.method} {request.url}")
    logger.error(f"Exception type: {type(exc).__name__}")
    logger.error(f"Exception message: {str(exc)}")
    logger.error("Full traceback:")
    logger.error(traceback.format_exc())
    log_memory_usage("(unhandled exception)")
    logger.error("=" * 80)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred. Please try again.",
            "error_id": str(error_id)
        }
    )

# Request validation middleware to handle invalid HTTP requests gracefully
class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Middleware to catch and handle invalid HTTP requests gracefully."""
    
    async def dispatch(self, request: StarletteRequest, call_next):
        try:
            # Validate request method
            if request.method not in ["GET", "POST", "OPTIONS", "HEAD"]:
                logger.warning(f"Invalid HTTP method: {request.method} for {request.url}")
                return JSONResponse(
                    status_code=405,
                    content={"error": "Method not allowed", "detail": f"Method {request.method} is not allowed"}
                )
            
            # Validate request path (basic sanity check)
            path = str(request.url.path)
            if len(path) > 2000:  # Prevent path traversal attacks
                logger.warning(f"Path too long: {len(path)} characters")
                return JSONResponse(
                    status_code=400,
                    content={"error": "Bad request", "detail": "Request path too long"}
                )
            
            # Process request
            response = await call_next(request)
            return response
            
        except Exception as e:
            # Catch any malformed request errors
            logger.error(f"Request validation error: {str(e)}")
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=400,
                content={"error": "Bad request", "detail": "Invalid HTTP request format"}
            )

# Add request validation middleware (should be first)
app.add_middleware(RequestValidationMiddleware)

# Add GZip middleware for better performance with large files
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configure CORS - supports both HTTP and HTTPS
# Set ALLOWED_ORIGINS environment variable for production (comma-separated)
# Example: ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
# If not set, defaults to ["*"] for development
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if allowed_origins_env == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS", "PUT", "DELETE"],  # Added OPTIONS for preflight
    allow_headers=["*"],
    expose_headers=["*"],  # Expose headers for CORS
)

def validate_file(file: UploadFile):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )

def validate_file_size(file: UploadFile):
    """Validate file size before processing."""
    if hasattr(file, 'size') and file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size allowed: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

def validate_multiple_files_size(files: List[UploadFile]):
    """Validate total size of multiple files."""
    total_size = 0
    for file in files:
        if hasattr(file, 'size') and file.size:
            total_size += file.size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Total files size too large. Maximum total size allowed: {MAX_TOTAL_SIZE // (1024*1024)}MB"
            )

async def process_single_file(file: UploadFile, timeout_handler: RequestTimeoutHandler) -> dict:
    """Process a single file and return analysis results with timeout handling."""
    tmp_path = None
    try:
        # Check timeout before processing
        timeout_handler.check_timeout()
        
        validate_file(file)
        validate_file_size(file)

        # Save file temporarily to disk
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
            file_bytes = await file.read()
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # Check timeout before text extraction
        timeout_handler.check_timeout()
        
        # 1. Extract text using the hybrid service with timeout
        try:
            log_memory_usage(f"before text extraction - {file.filename}")
            extracted_text = textract_service.extract_text_from_upload(tmp_path, file_bytes)
            log_memory_usage(f"after text extraction - {file.filename}")
        except Exception as e:
            logger.error(f"Text extraction failed for {file.filename}: {str(e)}")
            logger.error(traceback.format_exc())
            log_memory_usage(f"(text extraction error - {file.filename})")
            return {
                "filename": file.filename,
                "error": f"Text extraction failed: {str(e)}",
                "status": "failed"
            }
        
        if not extracted_text or not extracted_text.strip():
            return {
                "filename": file.filename,
                "error": "Failed to extract meaningful text from document.",
                "status": "failed"
            }

        # Check timeout before analysis
        timeout_handler.check_timeout()
        
        # 2. Perform analysis with timeout
        try:
            analysis_result = await asyncio.wait_for(
                openai_service.analyze_document(extracted_text),
                timeout=timeout_handler.get_remaining_time()
            )
        except asyncio.TimeoutError:
            logger.error(f"Analysis timeout for {file.filename}")
            log_memory_usage(f"(analysis timeout - {file.filename})")
            return {
                "filename": file.filename,
                "error": "Analysis timeout - document too complex",
                "status": "failed"
            }
        except Exception as e:
            logger.error(f"Analysis failed for {file.filename}: {str(e)}")
            logger.error(traceback.format_exc())
            log_memory_usage(f"(analysis error - {file.filename})")
            return {
                "filename": file.filename,
                "error": f"Analysis failed: {str(e)}",
                "status": "failed"
            }
        
        # ✅ Ensure analysis_result is a dictionary
        if not isinstance(analysis_result, dict):
            logger.warning("OpenAI returned non-dict analysis result. Wrapping it.")
            analysis_result = {"analysis_output": str(analysis_result)}

        # ✅ Optional debug logging
        logger.info(f"Successfully processed {file.filename}")

        return {
            "filename": file.filename,
            "analysis": analysis_result,
            "status": "success",
            "extracted_text": extracted_text[:1000]  # Keep first 1000 chars for reference
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file {file.filename}: {e}")
        logger.error(traceback.format_exc())
        log_memory_usage(f"(processing error - {file.filename})")
        return {
            "filename": file.filename,
            "error": str(e),
            "status": "failed"
        }
    finally:
        # Clean up the temporary file
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

async def analyze_multiple_files_consolidated(files: List[UploadFile]) -> dict:
    """Analyze multiple files together and provide a single consolidated analysis with timeout handling."""
    timeout_handler = RequestTimeoutHandler(REQUEST_TIMEOUT)
    timeout_handler.start()
    
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > MAX_FILES_PER_REQUEST:  # Limit to prevent abuse
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES_PER_REQUEST} files allowed per request")
    
    validate_multiple_files_size(files)
    
    # Process all files to extract text and classify
    file_results = []
    all_texts = []
    file_info = []
    categories = []
    
    logger.info(f"Starting to process {len(files)} files")
    
    for i, file in enumerate(files):
        # Check timeout for each file
        timeout_handler.check_timeout()
        
        logger.info(f"Processing file {i+1}/{len(files)}: {file.filename}")
        
        # Extract text and classify document
        tmp_path = None
        try:
            validate_file(file)
            validate_file_size(file)
            
            # Save file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
                file_bytes = await file.read()
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # Extract text
            try:
                extracted_text = textract_service.extract_text_from_upload(tmp_path, file_bytes)
            except Exception as e:
                logger.error(f"Text extraction failed for {file.filename}: {str(e)}")
                logger.error(traceback.format_exc())
                log_memory_usage(f"(text extraction error - {file.filename})")
                continue
            
            if not extracted_text or not extracted_text.strip():
                logger.warning(f"No text extracted from {file.filename}")
                continue
            
            # Classify document
            try:
                classification = await asyncio.wait_for(
                    openai_service.classify_document(extracted_text),
                    timeout=timeout_handler.get_remaining_time()
                )
                category = classification.get("category", "GENERAL")
                categories.append(category)
                
                file_results.append({
                    "filename": file.filename,
                    "text_length": len(extracted_text),
                    "category": category,
                    "status": "success"
                })
                all_texts.append(extracted_text)
                file_info.append({
                    "filename": file.filename,
                    "text_length": len(extracted_text),
                    "category": category
                })
                
                logger.info(f"Successfully processed {file.filename} - classified as {category} - extracted {len(extracted_text)} characters")
                
            except asyncio.TimeoutError:
                logger.error(f"Classification timeout for {file.filename}")
                continue
            except Exception as e:
                logger.error(f"Classification failed for {file.filename}: {str(e)}")
                logger.error(traceback.format_exc())
                log_memory_usage(f"(classification error - {file.filename})")
                continue
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {e}")
            logger.error(traceback.format_exc())
            log_memory_usage(f"(processing error - {file.filename})")
            continue
        finally:
            # Clean up temporary file
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    logger.info(f"Completed file processing: {len(file_results)} successful, {len(files) - len(file_results)} failed")
    
    if not file_results:
        raise HTTPException(status_code=422, detail="No files could be processed successfully")
    
    # Check timeout before consolidated analysis
    timeout_handler.check_timeout()
    
    # Combine all extracted texts for consolidated analysis
    combined_text = "\n\n--- DOCUMENT SEPARATOR ---\n\n".join(all_texts)
    unique_categories = list(set(categories))
    
    # Since classification groups documents by category, we expect same-category analysis
    category = unique_categories[0] if unique_categories else "UNKNOWN"
    
    logger.info(f"Starting consolidated analysis with {len(combined_text)} total characters")
    logger.info(f"Category: {category}")
    logger.info(f"Document categories: {unique_categories}")
    
    # Perform consolidated analysis using OpenAI with timeout
    try:
        logger.info(f"Calling OpenAI API for consolidated analysis...")
        consolidated_analysis = await asyncio.wait_for(
            openai_service.analyze_multiple_documents_consolidated(
                combined_text, 
                file_info,
                categories
            ),
            timeout=timeout_handler.get_remaining_time()
        )
        logger.info(f"OpenAI API call completed successfully")
        
        return {
            "total_files": len(files),
            "successful_files": len(file_results),
            "failed_files": len(files) - len(file_results),
            "file_info": file_info,
            "document_categories": unique_categories,
            "category": category,
            "consolidated_analysis": consolidated_analysis,
            "status": "success",
            "processing_time": time.time() - timeout_handler.start_time
        }
        
    except asyncio.TimeoutError:
        logger.error("Consolidated analysis timeout")
        raise HTTPException(status_code=408, detail="Analysis timeout - too many complex documents")
    except Exception as e:
        logger.error(f"Error in consolidated analysis: {e}")
        logger.error(traceback.format_exc())
        log_memory_usage("(consolidated analysis error)")
        raise HTTPException(status_code=500, detail=f"Consolidated analysis failed: {str(e)}")

@app.get("/", status_code=200)
async def root():
    """Root endpoint for load balancer health checks"""
    return {"status": "ok", "message": "Document Analysis API", "timestamp": time.time()}

@app.get("/health", status_code=200)
async def health_check():
    """Health check endpoint for load balancer and monitoring"""
    return {"status": "ok", "timestamp": time.time()}

@app.post("/analyze")
async def analyze_single(file: UploadFile = File(...)):
    """Analyze a single document with timeout handling."""
    timeout_handler = RequestTimeoutHandler(REQUEST_TIMEOUT)
    timeout_handler.start()
    
    result = await process_single_file(file, timeout_handler)
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    
    result["processing_time"] = time.time() - timeout_handler.start_time
    return result

@app.post("/analyze-multiple")
async def analyze_multiple(files: List[UploadFile] = File(...)):
    """Analyze multiple documents individually with timeout handling."""
    timeout_handler = RequestTimeoutHandler(REQUEST_TIMEOUT)
    timeout_handler.start()
    
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > MAX_FILES_PER_REQUEST:  # Limit to prevent abuse
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES_PER_REQUEST} files allowed per request")
    
    validate_multiple_files_size(files)
    
    # Process all files with timeout handling
    results = []
    for file in files:
        # Check timeout for each file
        timeout_handler.check_timeout()
        
        result = await process_single_file(file, timeout_handler)
        results.append(result)
    
    # Count successes and failures
    successful = sum(1 for r in results if r.get("status") == "success")
    failed = len(results) - successful
    
    return {
        "total_files": len(results),
        "successful": successful,
        "failed": failed,
        "results": results,
        "processing_time": time.time() - timeout_handler.start_time
    }

@app.post("/analyze-consolidated")
async def analyze_consolidated(files: List[UploadFile] = File(...)):
    """Analyze multiple documents together with timeout handling."""
    return await analyze_multiple_files_consolidated(files)

@app.post("/classify-documents") 
async def classify_documents(files: List[UploadFile] = File(...)):
    """Step 1: Classify bulk documents into categories/channels."""
    timeout_handler = RequestTimeoutHandler(REQUEST_TIMEOUT)
    timeout_handler.start()
    
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES_PER_REQUEST} files allowed per request")
    
    validate_multiple_files_size(files)
    
    # Process all files to extract text and classify
    classification_results = []
    channel_summary = {}
    
    logger.info(f"Starting classification of {len(files)} files")
    
    for i, file in enumerate(files):
        # Check timeout for each file
        timeout_handler.check_timeout()
        
        logger.info(f"Classifying file {i+1}/{len(files)}: {file.filename}")
        
        # Extract text from file
        tmp_path = None
        try:
            validate_file(file)
            validate_file_size(file)
            
            # Save file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
                file_bytes = await file.read()
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            # Extract text
            try:
                extracted_text = textract_service.extract_text_from_upload(tmp_path, file_bytes)
            except Exception as e:
                logger.error(f"Text extraction failed for {file.filename}: {str(e)}")
                logger.error(traceback.format_exc())
                log_memory_usage(f"(text extraction error - {file.filename})")
                classification_results.append({
                    "filename": file.filename,
                    "category": "UNCLASSIFIABLE",
                    "confidence": 0.0,
                    "reasoning": f"Text extraction failed: {str(e)}",
                    "subcategory": "Extraction Error",
                    "status": "failed"
                })
                continue
            
            if not extracted_text or not extracted_text.strip():
                classification_results.append({
                    "filename": file.filename,
                    "category": "UNCLASSIFIABLE",
                    "confidence": 0.0,
                    "reasoning": "No text extracted from document",
                    "subcategory": "No Text",
                    "status": "failed"
                })
                continue
            
            # Classify document
            try:
                classification = await asyncio.wait_for(
                    openai_service.classify_document(extracted_text),
                    timeout=timeout_handler.get_remaining_time()
                )
                
                classification_results.append({
                    "filename": file.filename,
                    "category": classification.get("category", "GENERAL"),
                    "confidence": classification.get("confidence", 0.5),
                    "reasoning": classification.get("reasoning", "Classification completed"),
                    "subcategory": classification.get("subcategory", "Unknown"),
                    "status": "success"
                })
                
                # Update channel summary
                category = classification.get("category", "GENERAL")
                if category not in channel_summary:
                    channel_summary[category] = {
                        "count": 0,
                        "files": [],
                        "avg_confidence": 0.0,
                        "subcategories": {}
                    }
                
                channel_summary[category]["count"] += 1
                channel_summary[category]["files"].append(file.filename)
                channel_summary[category]["avg_confidence"] = (
                    (channel_summary[category]["avg_confidence"] * (channel_summary[category]["count"] - 1) + 
                     classification.get("confidence", 0.5)) / channel_summary[category]["count"]
                )
                
                subcategory = classification.get("subcategory", "Unknown")
                if subcategory not in channel_summary[category]["subcategories"]:
                    channel_summary[category]["subcategories"][subcategory] = 0
                channel_summary[category]["subcategories"][subcategory] += 1
                
                logger.info(f"Classified {file.filename} as {category} (confidence: {classification.get('confidence', 0.5)})")
                
            except asyncio.TimeoutError:
                logger.error(f"Classification timeout for {file.filename}")
                classification_results.append({
                    "filename": file.filename,
                    "category": "UNCLASSIFIABLE",
                    "confidence": 0.0,
                    "reasoning": "Classification timeout",
                    "subcategory": "Timeout",
                    "status": "timeout"
                })
            except Exception as e:
                logger.error(f"Classification failed for {file.filename}: {str(e)}")
                logger.error(traceback.format_exc())
                log_memory_usage(f"(classification error - {file.filename})")
                classification_results.append({
                    "filename": file.filename,
                    "category": "UNCLASSIFIABLE",
                    "confidence": 0.0,
                    "reasoning": f"Classification failed: {str(e)}",
                    "subcategory": "Classification Error",
                    "status": "failed"
                })
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {e}")
            logger.error(traceback.format_exc())
            log_memory_usage(f"(processing error - {file.filename})")
            classification_results.append({
                "filename": file.filename,
                "category": "UNCLASSIFIABLE",
                "confidence": 0.0,
                "reasoning": f"Processing error: {str(e)}",
                "subcategory": "Processing Error",
                "status": "error"
            })
        finally:
            # Clean up temporary file
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    # Count successes and failures
    successful = sum(1 for r in classification_results if r.get("status") == "success")
    failed = len(classification_results) - successful
    
    logger.info(f"Classification completed: {successful} successful, {failed} failed")
    
    return {
        "total_files": len(files),
        "successful_classifications": successful,
        "failed_classifications": failed,
        "classification_results": classification_results,
        "channel_summary": channel_summary,
        "available_channels": list(channel_summary.keys()),
        "status": "success",
        "processing_time": time.time() - timeout_handler.start_time
    }


# Catch-all handler for invalid paths - MUST BE LAST to not interfere with specific routes
# Returns 404 instead of crashing worker on invalid paths
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def catch_all(path: str, request: Request):
    """Catch-all route handler for invalid paths to prevent worker crashes from vulnerability scanners."""
    logger.warning(f"Invalid path requested: {request.method} {request.url.path}")
    logger.warning(f"Client IP: {request.client.host if request.client else 'unknown'}")
    
    # Return proper 404 JSON response instead of letting it crash
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "detail": f"The requested path '{path}' was not found on this server.",
            "available_endpoints": [
                "/",
                "/health",
                "/analyze",
                "/analyze-multiple",
                "/analyze-consolidated",
                "/classify-documents"
            ]
        }
    )

# Graceful shutdown handler
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)