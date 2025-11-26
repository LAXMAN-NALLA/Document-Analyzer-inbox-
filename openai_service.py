# openai_service.py
import os
import json
import logging
from openai import AsyncOpenAI
from prompts import ANALYSIS_PROMPTS, DOCUMENT_CLASSIFICATION_PROMPT, SINGLE_DOCUMENT_PROMPTS

# Load OpenAI credentials
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_RETRIES = 3

async def classify_document(text: str) -> dict:
    """Classify a document into predefined categories."""
    logging.info("Classifying document...")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Attempt {attempt}: Sending classification request to OpenAI...")
            response = await client.chat.completions.create(
                model=OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": DOCUMENT_CLASSIFICATION_PROMPT},
                    {"role": "user", "content": text}
                ],
                temperature=0.2  # Balanced temperature for consistent category classification but varied subcategory generation
            )
            content = response.choices[0].message.content.strip()
            logging.debug(f"OpenAI classification response: {content}")
            result = json.loads(content)

            if isinstance(result, dict) and "category" in result:
                return result
            else:
                logging.warning("Unexpected classification format.")
                return {"category": "GENERAL", "confidence": 0.5, "reasoning": "Classification failed", "subcategory": "Unknown"}

        except Exception as e:
            logging.warning(f"Classification attempt {attempt} failed: {e}")
    
    logging.error("All classification attempts failed.")
    return {"category": "GENERAL", "confidence": 0.0, "reasoning": "Classification failed", "subcategory": "Unknown"}


async def analyze_document(text: str, category: str = None, subcategory: str = None) -> dict:
    """Analyze a single document using the appropriate prompt based on context."""
    logging.info("Analyzing single document...")
    
    # Choose the appropriate prompt based on whether category is provided
    if category:
        # Use channel/consolidated analysis prompt for pre-classified documents
        system_prompt = ANALYSIS_PROMPTS
        analysis_prompt = f"""
You are analyzing a document that has been classified as {category}.

Please provide a detailed analysis focusing on {category}-specific aspects and requirements.

Document text to analyze:
{text}

IMPORTANT: Focus on {category}-specific details, requirements, deadlines, and compliance issues. Extract relevant key details for {category} documents.
"""
    else:
        # Use single document analysis prompt for unclassified documents
        system_prompt = SINGLE_DOCUMENT_PROMPTS
        analysis_prompt = text
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Attempt {attempt}: Sending analysis request to OpenAI...")
            response = await client.chat.completions.create(
                model=OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": analysis_prompt}
                ],
                temperature=0.2
            )
            content = response.choices[0].message.content.strip()
            logging.debug(f"OpenAI response: {content}")
            result = json.loads(content)

            if isinstance(result, dict):
                return result
            else:
                logging.warning("Unexpected analysis format.")
                return {"result": str(result)}

        except Exception as e:
            logging.warning(f"Attempt {attempt} failed: {e}")
    logging.error("All analysis attempts failed.")
    return {"error": "Failed to analyze document."}

async def analyze_multiple_documents_consolidated(combined_text: str, file_info: list, categories: list = None) -> dict:
    """Analyze multiple documents together and provide a single consolidated analysis."""
    logging.info(f"Performing consolidated analysis of {len(file_info)} documents")
    
    # Log the analysis start
    logging.info(f"Starting consolidated analysis for {len(file_info)} documents")
    logging.info(f"Total combined text length: {len(combined_text)} characters")

    # Smart text sampling for better analysis
    if len(combined_text) > 50000:
        # For very large text, use smart sampling to get representative content
        # Take first 25,000 chars (beginning of documents) and last 25,000 chars (end of documents)
        first_part = combined_text[:25000]
        last_part = combined_text[-25000:]
        text_sample = first_part + "\n\n[... MIDDLE CONTENT TRUNCATED ...]\n\n" + last_part
        logging.info(f"Using smart sampling: {len(text_sample)} characters (first 25k + last 25k of {len(combined_text)} total)")
    else:
        # For smaller text, use all content
        text_sample = combined_text
        logging.info(f"Using all {len(text_sample)} characters for analysis")
    
    # Use the enhanced ANALYSIS_PROMPTS for consolidated analysis with category information
    category_info = ""
    analysis_focus = ""
    
    if categories:
        unique_categories = list(set(categories))
        # Since classification groups documents by category, we expect same-category analysis
        single_category = unique_categories[0]
        category_info = f"""
The documents have been classified as {single_category} documents.

Focus your analysis specifically on {single_category}-related aspects, requirements, deadlines, and compliance issues.
"""
        analysis_focus = f"""
IMPORTANT: Focus on {single_category}-specific details, requirements, deadlines, and compliance issues. Provide specific, actionable recommendations with exact amounts, dates, and regulatory requirements.

Extract {single_category}-specific key details from the combined text:
- If {single_category} is PAYMENTS: Extract invoice_number, due_date, total_amount, currency, sender_name, receiver_name, iban, payment_reference
- If {single_category} is VAT: Extract vat_id_number, tax_authority, reporting_period, submission_deadline, tax_due_amount, form_name
- If {single_category} is LEGAL: Extract contract_parties, effective_date, expiration_date, renewal_terms
- If {single_category} is REGISTRATION: Extract company_name, registration_number, issuing_authority, date_of_issue
- If {single_category} is FINANCIAL: Extract account_balance, transaction_summary, financial_period, bank_name
- If {single_category} is INSURANCE: Extract policy_number, coverage_type, premium_amount, renewal_date, insurer_name
- If {single_category} is CERTIFICATES: Extract certificate_type, issuing_authority, validity_period, certificate_number
- If {single_category} is TAX: Extract tax_type, tax_period, tax_amount, filing_deadline, tax_authority
- If {single_category} is GENERAL: Extract sender_name, subject, contact_person, relevant_dates
"""
    
    consolidated_prompt = f"""
You are analyzing {len(file_info)} documents that have been classified as the same category.
{category_info}
Focus your analysis on providing comprehensive insights for this specific document category.

Document Information:
{json.dumps(file_info, indent=2)}

Please provide a comprehensive analysis focusing on:
1. **Comprehensive Summary**: Detailed summary of all documents combined with specific details, amounts, dates, and entities
2. **Key Findings**: Specific findings from the document collection
3. **Detailed Recommendations**: Specific recommendations with exact details and next steps
4. **Priority Actions**: Most urgent actions that need immediate attention with specific details

Analyze the following combined text from all documents:
{text_sample}

{analysis_focus}
"""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"Attempt {attempt}: Sending consolidated analysis request to OpenAI...")
            logging.info(f"Prompt length: {len(consolidated_prompt)} characters")
            logging.info(f"Text sample length: {len(text_sample)} characters")
            
            response = await client.chat.completions.create(
                model=OPENAI_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": ANALYSIS_PROMPTS},
                    {"role": "user", "content": consolidated_prompt}
                ],
                temperature=0.3,
                max_tokens=3000
            )
            content = response.choices[0].message.content.strip()
            logging.debug(f"OpenAI consolidated analysis response: {content}")
            result = json.loads(content)

            if isinstance(result, dict):
                return result
            else:
                logging.warning("Unexpected consolidated analysis format.")
                return {"comprehensive_summary": "Analysis completed but format was unexpected", "detailed_recommendations": ["Please check document format"]}

        except Exception as e:
            logging.error(f"Attempt {attempt} failed with error: {str(e)}")
            logging.error(f"Error type: {type(e).__name__}")
            if hasattr(e, '__traceback__'):
                import traceback
                logging.error(f"Full traceback: {traceback.format_exc()}")
    
    logging.error("All consolidated analysis attempts failed.")
    return {"comprehensive_summary": "Failed to analyze documents", "detailed_recommendations": ["Please try again or check document format"]}
