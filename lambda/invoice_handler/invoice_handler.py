import json
import re
import os
from datetime import datetime
import boto3
from io import BytesIO
import base64
from decimal import Decimal

# Custom VAT calculation package
from invoice_tax_pkg import TaxCalculator

# PDF parsing support
try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("WARNING: PyPDF2 not installed. PDF parsing will fail.")

# AWS service clients and resources
s3_client = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
sqs_client = boto3.client('sqs')

# Environment variables for resource names
S3_BUCKET = os.environ.get('S3_BUCKET_NAME', 'invoice-management-bucket-prajwal-nci')
USER_ANALYSES_TABLE = os.environ.get('DYNAMODB_TABLE_NAME', 'user_analyses')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/556192680160/BankStatementAnalysisQueue')

def lambda_handler(event, context):
    """
    Main Lambda entrypoint: API Gateway calls this function.
    Routes requests to appropriate handlers based on resource path and HTTP method.
    """
    try:
        path = event.get('resource', '')
        method = event.get('httpMethod', '')

        print(f"Request: {method} {path}")
        print(f"Using S3 Bucket: {S3_BUCKET}")
        print(f"Using DynamoDB Table: {USER_ANALYSES_TABLE}")
        print(f"Using SQS Queue: {SQS_QUEUE_URL}")

        # Route requests to appropriate handlers
        if path == '/bank/analyze' and method == 'POST':
            return handle_bank_analyze(event)
        elif path == '/upload' and method == 'POST':
            return handle_upload(event)
        elif path == '/delete' and method == 'POST':
            return handle_delete_file(event)
        elif path == '/bank/save-analysis' and method == 'POST':
            return handle_save_analysis(event)
        elif path == '/bank/my-analyses' and method == 'POST':
            return handle_get_user_analyses(event)
        elif path == '/bank/delete-analysis' and method == 'POST':
            return handle_delete_analysis(event)
        elif path == '/health' and method == 'GET':
            # Health check endpoint - verifies all services are ready
            return success_response({
                'status': 'healthy',
                'service': 'bank-analyzer-api',
                'pdf_support': PDF_SUPPORT,
                's3_bucket': S3_BUCKET,
                'dynamodb_table': USER_ANALYSES_TABLE,
                'sqs_queue': SQS_QUEUE_URL,
                'timestamp': datetime.utcnow().isoformat()
            })
        else:
            # Unknown endpoint
            return error_response(f'Unknown endpoint: {method} {path}', 404)

    except Exception as e:
        print(f'Lambda handler error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Internal server error: {str(e)}', 500)

# =============== FILE UPLOAD AND DELETE ===============

def handle_upload(event):
    """
    Handles file upload to S3.
    - Receives base64-encoded file from frontend
    - Decodes and uploads to S3 bucket
    - Returns S3 location
    """
    try:
        body = json.loads(event.get('body') or '{}')
        filename = body.get('filename', '').strip()
        content_base64 = body.get('content', '').strip()
        content_type = body.get('contentType', 'application/pdf')

        if not filename or not content_base64:
            return error_response('filename and content are required', 400)

        try:
            # Decode base64 content
            file_content = base64.b64decode(content_base64)
        except Exception as e:
            return error_response(f'Invalid base64 content: {str(e)}', 400)

        # Upload to S3
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType=content_type
        )

        print(f'File uploaded: s3://{S3_BUCKET}/{filename}')

        return success_response({
            'message': 'File uploaded successfully',
            'bucket': S3_BUCKET,
            'key': filename,
            's3_url': f's3://{S3_BUCKET}/{filename}'
        }, 201)

    except Exception as e:
        print(f'Upload error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Upload failed: {str(e)}', 500)

def handle_delete_file(event):
    """
    Handles deletion of a file from S3.
    """
    try:
        body = json.loads(event.get('body') or '{}')
        bucket = body.get('bucket', '').strip()
        key = body.get('key', '').strip()

        if not bucket or not key:
            return error_response('bucket and key are required', 400)

        s3_client.delete_object(Bucket=bucket, Key=key)

        print(f'File deleted: s3://{bucket}/{key}')

        return success_response({
            'message': 'File deleted successfully',
            'bucket': bucket,
            'key': key
        })

    except Exception as e:
        print(f'Delete error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Delete failed: {str(e)}', 500)

# bank statement analysis section

def handle_bank_analyze(event):
    try:
        body = json.loads(event.get('body') or '{}')
        bucket = body.get('bucket', '').strip()
        key = body.get('key', '').strip()
        country_code = body.get('country_code', 'IE').upper()
        user_email = body.get('user_email', '').strip()

        # Validate required fields
        if not bucket or not key:
            return error_response('bucket and key are required', 400)
        if not user_email:
            return error_response('user_email is required', 400)

        print(f'Queuing analysis: s3://{bucket}/{key} for {user_email}')

        # sends msg to sqs
        # This triggers lambda2-worker.py
        message = {
            'bucket': bucket,
            'key': key,
            'country_code': country_code,
            'user_email': user_email,
            'file_name': key
        }

        try:
            response = sqs_client.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            message_id = response.get('MessageId', 'unknown')
            print(f'Message sent to SQS: {message_id}')
        except Exception as sqs_error:
            print(f'SQS Error: {str(sqs_error)}')
            import traceback
            traceback.print_exc()
            return error_response(f'Failed to queue analysis: {str(sqs_error)}', 500)

        # Return 202 Accepted - processing has started
        return success_response({
            'message': 'Analysis queued successfully',
            'status': 'processing',
            'file': key,
            'user_email': user_email,
            'message_id': message_id,
            'note': 'Your file is being analyzed in the background. Please check "My Analyses" in 30-60 seconds for results.'
        }, 202)

    except Exception as e:
        print(f'Bank analysis error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Analysis failed: {str(e)}', 500)

# =============== DYNAMODB: SAVE, FETCH, DELETE ===============

def handle_save_analysis(event):

    try:
        body = json.loads(event.get('body') or '{}')
        user_email = body.get('user_email', '').strip()
        analysis_data = body.get('analysis_data', {})
        file_name = body.get('file_name', 'statement.pdf')[:100]

        if not user_email or not analysis_data:
            return error_response('user_email and analysis_data required', 400)

        table = dynamo.Table(USER_ANALYSES_TABLE)

        # Extract summary data
        monthly = analysis_data.get('monthly_summary', {})
        total_net = sum(float(m.get('net_total', 0)) for m in monthly.values())
        total_vat = sum(float(m.get('vat_total', 0)) for m in monthly.values())
        total_gross = sum(float(m.get('gross_total', 0)) for m in monthly.values())
        num_tx = analysis_data.get('transaction_count', 0)
        months_sorted = ','.join(sorted(monthly.keys()))
        
        # Create fingerprint for duplicate detection
        fingerprint = f"{file_name}_{round(total_gross, 2)}_{num_tx}_{months_sorted}"

        # Checks for duplicates
        try:
            existing = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(user_email),
                FilterExpression='fingerprint = :fp',
                ExpressionAttributeValues={':fp': fingerprint}
            )
            if existing.get('Items'):
                existing_item = existing['Items'][0]
                try:
                    saved_dt = datetime.fromisoformat(str(existing_item['saved_at']))
                    saved_formatted = saved_dt.strftime('%d %b %Y, %H:%M')
                except Exception:
                    saved_formatted = str(existing_item['saved_at'])
                
                print(f'Duplicate found for {user_email}')
                return success_response({
                    'message': 'This analysis was already saved previously',
                    'analysis_id': str(existing_item['analysis_id']),
                    'saved_at': str(existing_item['saved_at']),
                    'saved_at_formatted': saved_formatted,
                    'is_duplicate': True
                })
        except Exception as check_error:
            print(f'Duplicate check warning: {str(check_error)}')

        # Save new analysis record
        analysis_id = str(int(datetime.utcnow().timestamp() * 1000))
        saved_at = datetime.utcnow().isoformat()
        
        item = {
            'user_email': user_email,
            'analysis_id': analysis_id,
            'saved_at': saved_at,
            'file_name': file_name,
            'fingerprint': fingerprint,
            'country_code': analysis_data.get('country_code', 'IE'),
            'total_gross': Decimal(str(round(total_gross, 2))),
            'total_net': Decimal(str(round(total_net, 2))),
            'total_vat': Decimal(str(round(total_vat, 2))),
            'transaction_count': num_tx,
            'monthly_summary': convert_floats_to_decimal(monthly),
            'category_summary': convert_floats_to_decimal(analysis_data.get('category_summary', {}))
        }
        
        table.put_item(Item=item)
        
        try:
            saved_dt = datetime.fromisoformat(saved_at)
            saved_formatted = saved_dt.strftime('%d %b %Y, %H:%M')
        except Exception:
            saved_formatted = saved_at
        
        print(f'Analysis saved for {user_email}: {analysis_id}')
        
        return success_response({
            'message': 'Analysis saved successfully',
            'analysis_id': analysis_id,
            'saved_at': saved_at,
            'saved_at_formatted': saved_formatted,
            'is_duplicate': False
        }, 201)
        
    except Exception as e:
        print(f'Save analysis error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Save failed: {str(e)}', 500)

def handle_get_user_analyses(event):
    """
    Retrieves all analyses for a user from DynamoDB.
    
    Called when user clicks "My Analyses" button.
    Returns analyses sorted by newest first.
    """
    try:
        body = json.loads(event.get('body') or '{}')
        user_email = body.get('user_email', '').strip()

        if not user_email:
            return error_response('user_email required', 400)

        table = dynamo.Table(USER_ANALYSES_TABLE)

        # Query all analyses for this user
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(user_email),
            ScanIndexForward=False
        )

        items = response.get('Items', [])
        
        # Convert Decimal to float for JSON serialization
        for item in items:
            for key in ['total_gross', 'total_net', 'total_vat']:
                if key in item:
                    item[key] = float(item[key])
            
            # Format timestamp
            try:
                saved_dt = datetime.fromisoformat(str(item['saved_at']))
                item['saved_at_formatted'] = saved_dt.strftime('%d %b %Y, %H:%M')
            except Exception:
                item['saved_at_formatted'] = str(item['saved_at'])

            if 'monthly_summary' in item:
                item['monthly_summary'] = convert_decimal_to_float(item['monthly_summary'])
            if 'category_summary' in item:
                item['category_summary'] = convert_decimal_to_float(item['category_summary'])

        print(f'Retrieved {len(items)} analyses for {user_email}')
        
        return success_response({
            'analyses': items,
            'count': len(items)
        })

    except Exception as e:
        print(f'Get analyses error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Fetch failed: {str(e)}', 500)

def handle_delete_analysis(event):
    """
    Deletes a specific analysis from DynamoDB.
    """
    try:
        body = json.loads(event.get('body') or '{}')
        user_email = body.get('user_email', '').strip()
        analysis_id = body.get('analysis_id', '').strip()

        if not user_email or not analysis_id:
            return error_response('user_email and analysis_id required', 400)

        table = dynamo.Table(USER_ANALYSES_TABLE)

        table.delete_item(
            Key={
                'user_email': user_email,
                'analysis_id': analysis_id
            }
        )

        print(f'Deleted analysis {analysis_id} for {user_email}')
        
        return success_response({
            'message': 'Analysis deleted successfully',
            'analysis_id': analysis_id
        })
        
    except Exception as e:
        print(f'Delete analysis error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Delete failed: {str(e)}', 500)

# pdf processing section

def extract_text_from_pdf(pdf_bytes):
    """
    Extracts all text content from a PDF file using PyPDF2.
    Handles multi-page PDFs.
    """
    try:
        pdf_file = BytesIO(pdf_bytes)
        reader = PyPDF2.PdfReader(pdf_file)
        text = ''
        
        for page_num, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
            except Exception as e:
                print(f'Warning: Could not extract text from page {page_num}: {str(e)}')
                continue
        
        if not text.strip():
            raise Exception('No text content found in PDF')
        
        print(f'Extracted {len(text)} characters from PDF')
        return text

    except Exception as e:
        raise Exception(f'PDF extraction failed: {str(e)}')

def parse_transactions(content):
    """
    Parse bank statement transactions from PDF text.
    
    CRITICAL FIXES:
    - Only captures DEBIT transactions (Money out)
    - Ignores credits (Money in) like top-ups
    - Handles both CSV and free-text formats
    - Supports multiple date/amount formats
    
    Example transaction:
    "3 Nov Centra €8.51" → {'date': '2025-11-03', 'description': 'Centra', 'gross_amount': 8.51}
    """
    transactions = []
    lines = content.splitlines()
    
    print(f"Parsing {len(lines)} lines from statement...")
    
    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
        
        # Skip header rows
        if any(k in line.lower() for k in ['date', 'description', 'money out', 'money in', 'balance', 'account', 'opening', 'closing', 'statement']) \
           and not any(ch.isdigit() for ch in line):
            continue
        
        # Skip any line that is a credit or top-up
        if any(word in line.lower() for word in ['top-up', 'money in', 'credit', 'deposit', 'from:', 'apple pay', 'transfer in']):
            continue
        

        if ',' in line:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 3:
                date_str = parts[0]
                desc = parts[1]
                try:
                    amount = float(parts[2].replace('€', '').replace(',', '.'))
                except (ValueError, IndexError):
                    amount = None
                
                if amount is None:
                    continue
                
                # Parse date
                dt = None
                for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        break
                    except Exception:
                        continue
                
                if not dt:
                    try:
                        dt = datetime.fromisoformat(date_str)
                    except Exception:
                        continue
                
                month_key = dt.strftime('%Y-%m')
                transactions.append({
                    'date': dt.date().isoformat(),
                    'month': month_key,
                    'description': desc if desc else 'Transaction',
                    'gross_amount': round(abs(amount), 2),
                })
                continue
        
        date_patterns = [
            (r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+202[0-9])', '%d %b %Y'),
            (r'(\d{1,2}/\d{1,2}/202[0-9])', '%d/%m/%Y'),
            (r'(202[0-9]-\d{2}-\d{2})', '%Y-%m-%d'),
        ]
        
        amount_patterns = [
            r'-?€\s*(\d+[.,]\d{2})',
            r'-?\s*(\d+[.,]\d{2})\s*€',
            r'-?\s*(\d+[.,]\d{2})',
        ]
        
        dt = None
        date_str = None
        
        # Extract date
        for pattern, fmt in date_patterns:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                date_str = m.group(1)
                try:
                    dt = datetime.strptime(date_str, fmt)
                    break
                except Exception:
                    continue
        
        if not dt:
            continue
        
        # Extracts amount
        amount = None
        for pattern in amount_patterns:
            m = re.search(pattern, line)
            if m:
                try:
                    amt_str = m.group(1).replace(',', '.')
                    amount = float(amt_str)
                    break
                except Exception:
                    continue
        
        if amount is None:
            continue
        
        # Extracts description
        desc_line = line
        for pattern, _fmt in date_patterns:
            desc_line = re.sub(pattern, '', desc_line, flags=re.IGNORECASE)
        for pattern in amount_patterns:
            desc_line = re.sub(pattern, '', desc_line)
        
        desc = re.sub(r'\s+', ' ', desc_line).strip()
        if not desc or len(desc) < 2:
            desc = 'Transaction'
        
        month_key = dt.strftime('%Y-%m')
        transactions.append({
            'date': dt.date().isoformat(),
            'month': month_key,
            'description': desc[:100],
            'gross_amount': round(abs(amount), 2),
        })

    print(f"Found {len(transactions)} transactions")
    return transactions

def categorize_expense(description):
    """
    Categorizes each transaction into logical section.
    Uses keyword matching for automatic categorization.
    """
    if not description:
        return 'Other'
    
    text = description.lower()
    categories = {
        'Food & Groceries': [
            'tesco', 'lidl', 'supervalu', 'dunnes', 'eurasia', 'supermarket',
            'spar', 'centra', 'aldi', 'marks & spencer', 'm&s food'
        ],
        'Transport': [
            'transport for ireland', 'tfi', 'leap', 'bus', 'luas', 'dart',
            'nta', 'dublin bus', 'irish rail', 'taxi', 'uber', 'lyft', 'bolt'
        ],
        'Shopping': [
            'penneys', 'primark', 'mr price', 'euro giant', 'euro store',
            'zara', 'h&m', 'next', 'new look', 'tk maxx', 'dunnes stores'
        ],
        'Subscriptions': [
            'netflix', 'spotify', 'apple.com', 'apple music', 'subscription',
            'amazon prime', 'disney+', 'youtube premium', '48months'
        ],
        'Snacks & Dining': [
            'five guys', 'burger king', 'mcdonalds', "mcdonald's", 'kfc',
            'supermacs', 'subway', 'starbucks', 'costa', 'insomnia',
            'cafe', 'bakehouse', 'restaurant', 'pizza', 'nandos'
        ],
        'Bills & Utilities': [
            'rent', 'electric', 'electricity', 'gas', 'eir', 'vodafone',
            'three', 'sky', 'virgin media', 'utility', 'sse airtricity'
        ],
        'Health & Pharmacy': [
            'pharmacy', 'chemist', 'boots', 'mccabes', 'lloyds pharmacy',
            'hospital', 'doctor', 'dentist', 'medical'
        ]
    }
    
    for category, keywords in categories.items():
        if any(keyword in text for keyword in keywords):
            return category
    
    return 'Other'


def convert_floats_to_decimal(obj):
    """ converts all floats to Decimals for DynamoDB."""
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def convert_decimal_to_float(obj):
    """converts Decimals back to floats for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimal_to_float(item) for item in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

def success_response(data, status_code=200):
    """
    Includes CORS headers for cross-origin requests.
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
            'Content-Type': 'application/json',
        },
        'body': json.dumps(data, default=str),
    }

def error_response(message, status_code=500):
    """
    Helper to build a standard HTTP/JSON error response.
    """
    return success_response({'error': message}, status_code)
