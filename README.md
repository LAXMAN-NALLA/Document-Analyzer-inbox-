# Document Analysis API

A FastAPI-based document classification and analysis service that uses OpenAI GPT-4 to automatically categorize and analyze business documents.

## Features

- **Document Classification**: Automatically categorizes documents into 10 predefined categories (VAT, TAX, PAYMENTS, CERTIFICATES, REGISTRATION, LEGAL, FINANCIAL, INSURANCE, GENERAL, UNCLASSIFIABLE)
- **Bulk Processing**: Process up to 30 documents per request
- **Multiple File Formats**: Supports PDF, DOCX, XLSX, CSV, images (PNG, JPG, JPEG), TXT, RTF, PPTX, ODT
- **Text Extraction**: Hybrid extraction using pdfplumber, python-docx, pandas, and AWS Textract for OCR
- **AI-Powered Analysis**: Uses OpenAI GPT-4o for intelligent document classification and analysis
- **HTTPS/SSL Support**: Configured for secure connections
- **CORS Enabled**: Ready for frontend integration

## API Endpoints

### Health Check
- `GET /health` - Health check endpoint
- `GET /` - Root endpoint

### Document Classification
- `POST /classify-documents` - Classify multiple documents into categories
  - Accepts: Multiple files (max 30 files, 500MB per file)
  - Returns: Classification results with categories, confidence scores, and subcategories

### Document Analysis
- `POST /analyze` - Analyze a single document
- `POST /analyze-multiple` - Analyze multiple documents individually
- `POST /analyze-consolidated` - Analyze multiple documents together with consolidated results

## Document Categories

1. **VAT** - Value Added Tax documents, VAT returns, VAT correspondence
2. **TAX** - Income tax, corporate tax, tax assessments (non-VAT)
3. **PAYMENTS** - Invoices, payment requests, bills, receipts, payment confirmations
4. **CERTIFICATES** - ISO certificates, Certificate of Good Standing, product compliance
5. **REGISTRATION** - Chamber of Commerce, Trade Register, business licenses
6. **LEGAL** - Contracts, legal notices, court documents
7. **FINANCIAL** - Bank statements, financial reports, balance sheets
8. **INSURANCE** - Insurance policies, claims, premium notices
9. **GENERAL** - Business correspondence, service agreements
10. **UNCLASSIFIABLE** - Unreadable, corrupted, or non-business documents

## Technology Stack

- **Framework**: FastAPI
- **AI Model**: OpenAI GPT-4o
- **Text Extraction**: pdfplumber, python-docx, pandas, AWS Textract
- **Server**: Gunicorn with Uvicorn workers
- **Deployment**: AWS Elastic Beanstalk (Docker)
- **Reverse Proxy**: Nginx

## Configuration

### Environment Variables

Create a `.env` file or set environment variables in AWS Elastic Beanstalk:

```env
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o

# AWS Configuration (for Textract OCR)
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=ap-south-1

# File Size Limits
MAX_FILE_SIZE_MB=500
MAX_TOTAL_SIZE_MB=10000
MAX_FILES_PER_REQUEST=25

# Request Timeout
REQUEST_TIMEOUT_SECONDS=3600

# CORS Configuration (optional)
ALLOWED_ORIGINS=https://yourdomain.com
```

## Installation

### Local Development

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables in `.env`
4. Run the application:
   ```bash
   uvicorn main:app --reload
   ```

### Production Deployment

The application is configured for AWS Elastic Beanstalk with Docker:

1. Build and deploy using EB CLI or AWS Console
2. Configure environment variables in EB Console
3. Set up SSL certificate in Certificate Manager
4. Configure load balancer for HTTPS
5. Update DNS to point to load balancer

## File Structure

```
.
├── main.py                 # FastAPI application and endpoints
├── openai_service.py       # OpenAI API integration
├── prompts.py              # AI prompts for classification and analysis
├── textract_service.py     # Text extraction from various file formats
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker configuration
├── Procfile               # Process configuration for EB
├── .ebextensions/         # Elastic Beanstalk configuration
│   ├── 01_environment.config
│   └── 01_docker.config
└── .platform/             # Platform-specific configuration
    └── nginx/
        └── conf.d/
            ├── main.conf
            ├── timeouts.conf
            └── upload.conf
```

## API Usage Examples

### Classify Documents

```python
import requests

files = [
    ('files', open('invoice.pdf', 'rb')),
    ('files', open('vat_return.pdf', 'rb'))
]

response = requests.post(
    'https://your-api-domain.com/classify-documents',
    files=files
)

result = response.json()
print(f"Categories: {result['available_channels']}")
print(f"Results: {result['classification_results']}")
```

### Analyze Single Document

```python
files = [('file', open('document.pdf', 'rb'))]

response = requests.post(
    'https://your-api-domain.com/analyze',
    files=files
)

result = response.json()
print(result['analysis'])
```

## Response Format

### Classification Response

```json
{
  "total_files": 2,
  "successful_classifications": 2,
  "failed_classifications": 0,
  "classification_results": [
    {
      "filename": "invoice.pdf",
      "category": "PAYMENTS",
      "confidence": 0.95,
      "reasoning": "Document is a sales invoice requesting payment",
      "subcategory": "Sales Invoice",
      "status": "success"
    }
  ],
  "channel_summary": {
    "PAYMENTS": {
      "count": 1,
      "files": ["invoice.pdf"],
      "avg_confidence": 0.95,
      "subcategories": {
        "Sales Invoice": 1
      }
    }
  },
  "available_channels": ["PAYMENTS"],
  "status": "success",
  "processing_time": 12.5
}
```

## Limitations

- Maximum file size: 500MB per file (configurable)
- Maximum total size: 10GB for all files (configurable)
- Maximum files per request: 25 files (configurable)
- Request timeout: 3600 seconds (1 hour, configurable)

## Security

- HTTPS/SSL support via AWS Load Balancer
- CORS configuration for frontend integration
- File type validation
- File size limits
- Request timeout handling
- Input validation and sanitization

## License

[Add your license here]

## Support

For issues or questions, please contact the development team.

