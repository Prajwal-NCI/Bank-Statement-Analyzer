import json
import re
import os
from datetime import datetime
import boto3
from io import BytesIO
import base64
from decimal import Decimal

from invoice_tax_pkg import TaxCalculator

try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("WARNING: PyPDF2 not installed. PDF parsing will fail.")

s3_client = boto3.client('s3')
dynamo = boto3.resource('dynamodb')

# READ FROM ENVIRONMENT VARIABLES
S3_BUCKET = os.environ.get('S3_BUCKET_NAME', 'invoice-management-bucket-prajwal-nci')
USER_ANALYSES_TABLE = os.environ.get('DYNAMODB_TABLE_NAME', 'user_analyses')


def lambda_handler(event, context):
    try:
        path = event.get('resource', '')
        method = event.get('httpMethod', '')

        print(f"Request: {method} {path}")
        print(f"Using S3 Bucket: {S3_BUCKET}")
        print(f"Using DynamoDB Table: {USER_ANALYSES_TABLE}")

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
            return success_response({
                'status': 'healthy',
                'service': 'bank-analyzer',
                'pdf_support': PDF_SUPPORT,
                's3_bucket': S3_BUCKET,
                'dynamodb_table': USER_ANALYSES_TABLE,
                'timestamp': datetime.utcnow().isoformat()
            })
        else:
            return error_response(f'Unknown endpoint: {method} {path}', 404)

    except Exception as e:
        print(f'Lambda handler error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Internal server error: {str(e)}', 500)


# -------------------- FILE UPLOAD / DELETE --------------------


def handle_upload(event):
    try:
        body = json.loads(event.get('body') or '{}')
        filename = body.get('filename', '').strip()
        content_base64 = body.get('content', '').strip()
        content_type = body.get('contentType', 'application/pdf')

        if not filename or not content_base64:
            return error_response('filename and content are required', 400)

        try:
            file_content = base64.b64decode(content_base64)
        except Exception as e:
            return error_response(f'Invalid base64 content: {str(e)}', 400)

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType=content_type
        )

        print(f'✅ File uploaded: s3://{S3_BUCKET}/{filename}')

        return success_response({
            'message': 'File uploaded successfully',
            'bucket': S3_BUCKET,
            'key': filename,
            's3_url': f's3://{S3_BUCKET}/{filename}'
        })

    except Exception as e:
        print(f'Upload error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Upload failed: {str(e)}', 500)


def handle_delete_file(event):
    try:
        body = json.loads(event.get('body') or '{}')
        bucket = body.get('bucket', '').strip()
        key = body.get('key', '').strip()

        if not bucket or not key:
            return error_response('bucket and key are required', 400)

        s3_client.delete_object(Bucket=bucket, Key=key)

        print(f'✅ File deleted: s3://{bucket}/{key}')

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


# -------------------- BANK ANALYZE --------------------


def handle_bank_analyze(event):
    try:
        body = json.loads(event.get('body') or '{}')
        bucket = body.get('bucket', '').strip()
        key = body.get('key', '').strip()
        country_code = body.get('country_code', 'IE').upper()
        user_email = body.get('user_email', '').strip()

        if not bucket or not key:
            return error_response('bucket and key are required', 400)

        print(f'Analyzing: s3://{bucket}/{key} for country {country_code}')

        if key.lower().endswith('.pdf'):
            if not PDF_SUPPORT:
                return error_response('PDF support not available. Install PyPDF2.', 500)
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=key)
                pdf_bytes = obj['Body'].read()
                content = extract_text_from_pdf(pdf_bytes)
            except Exception as e:
                print(f'PDF extraction error: {str(e)}')
                return error_response(f'PDF extraction failed: {str(e)}', 500)
        else:
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=key)
                content = obj['Body'].read().decode('utf-8', errors='ignore')
            except Exception as e:
                print(f'File read error: {str(e)}')
                return error_response(f'File read failed: {str(e)}', 500)

        transactions = parse_transactions(content)

        if not transactions:
            return error_response('No valid transactions found in statement', 400)

        print(f'Found {len(transactions)} transactions')

        calc = TaxCalculator()
        enriched = []

        for t in transactions:
            try:
                category = categorize_expense(t['description'])
                gross = t['gross_amount']

                vat, net = calc.extract_vat(gross, country_code)

                enriched.append({
                    'date': t['date'],
                    'month': t['month'],
                    'description': t['description'],
                    'category': category,
                    'net_amount': round(net, 2),
                    'vat_amount': round(vat, 2),
                    'total_amount': round(gross, 2),
                    'country_code': country_code,
                })
            except Exception as e:
                print(f'Transaction processing error: {str(e)}')
                continue

        if not enriched:
            return error_response('Could not process any transactions', 400)

        monthly = {}
        by_category = {}

        for e_tx in enriched:
            m = e_tx['month']
            c = e_tx['category']
            net = e_tx['net_amount']
            vat = e_tx['vat_amount']
            gross = e_tx['total_amount']

            if m not in monthly:
                monthly[m] = {
                    'net_total': 0.0,
                    'vat_total': 0.0,
                    'gross_total': 0.0,
                    'by_category': {}
                }

            monthly[m]['net_total'] += net
            monthly[m]['vat_total'] += vat
            monthly[m]['gross_total'] += gross

            if c not in monthly[m]['by_category']:
                monthly[m]['by_category'][c] = 0.0
            monthly[m]['by_category'][c] += gross

            if c not in by_category:
                by_category[c] = {
                    'net': 0.0,
                    'vat': 0.0,
                    'gross': 0.0,
                    'count': 0,
                    'by_month': {}
                }

            by_category[c]['net'] += net
            by_category[c]['vat'] += vat
            by_category[c]['gross'] += gross
            by_category[c]['count'] += 1

            if m not in by_category[c]['by_month']:
                by_category[c]['by_month'][m] = {
                    'net': 0.0,
                    'vat': 0.0,
                    'gross': 0.0,
                    'count': 0
                }

            by_category[c]['by_month'][m]['net'] += net
            by_category[c]['by_month'][m]['vat'] += vat
            by_category[c]['by_month'][m]['gross'] += gross
            by_category[c]['by_month'][m]['count'] += 1

        for m_data in monthly.values():
            m_data['net_total'] = round(m_data['net_total'], 2)
            m_data['vat_total'] = round(m_data['vat_total'], 2)
            m_data['gross_total'] = round(m_data['gross_total'], 2)

        for c_data in by_category.values():
            c_data['net'] = round(c_data['net'], 2)
            c_data['vat'] = round(c_data['vat'], 2)
            c_data['gross'] = round(c_data['gross'], 2)

        result = {
            'country_code': country_code,
            'transaction_count': len(enriched),
            'transactions': enriched,
            'monthly_summary': monthly,
            'category_summary': by_category,
        }

        print(f'✅ Analysis complete: {len(enriched)} transactions processed')

        return success_response(result)

    except Exception as e:
        print(f'Bank analysis error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Analysis failed: {str(e)}', 500)


# -------------------- SAVE / LIST / DELETE ANALYSES --------------------


def handle_save_analysis(event):
    try:
        body = json.loads(event.get('body') or '{}')
        user_email = body.get('user_email', '').strip()
        analysis_data = body.get('analysis_data', {})
        file_name = body.get('file_name', 'statement.pdf')[:100]

        if not user_email or not analysis_data:
            return error_response('user_email and analysis_data required', 400)

        table = dynamo.Table(USER_ANALYSES_TABLE)

        monthly = analysis_data.get('monthly_summary', {})
        total_net = sum(float(m.get('net_total', 0)) for m in monthly.values())
        total_vat = sum(float(m.get('vat_total', 0)) for m in monthly.values())
        total_gross = sum(float(m.get('gross_total', 0)) for m in monthly.values())
        num_tx = analysis_data.get('transaction_count', 0)

        months_sorted = ','.join(sorted(monthly.keys()))
        fingerprint = f"{file_name}_{round(total_gross, 2)}_{num_tx}_{months_sorted}"

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

                print(f'ℹ️ Duplicate found for {user_email}')

                return success_response({
                    'message': 'This analysis was already saved previously',
                    'analysis_id': str(existing_item['analysis_id']),
                    'saved_at': str(existing_item['saved_at']),
                    'saved_at_formatted': saved_formatted,
                    'is_duplicate': True
                })
        except Exception as check_error:
            print(f'Duplicate check warning: {str(check_error)}')

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

        print(f'✅ Analysis saved for {user_email}: {analysis_id}')

        return success_response({
            'message': 'Analysis saved successfully',
            'analysis_id': analysis_id,
            'saved_at': saved_at,
            'saved_at_formatted': saved_formatted,
            'is_duplicate': False
        })

    except Exception as e:
        print(f'Save analysis error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Save failed: {str(e)}', 500)


def handle_get_user_analyses(event):
    try:
        body = json.loads(event.get('body') or '{}')
        user_email = body.get('user_email', '').strip()

        if not user_email:
            return error_response('user_email required', 400)

        table = dynamo.Table(USER_ANALYSES_TABLE)

        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('user_email').eq(user_email),
            ScanIndexForward=False
        )

        items = response.get('Items', [])

        for item in items:
            for key in ['total_gross', 'total_net', 'total_vat']:
                if key in item:
                    item[key] = float(item[key])

            try:
                saved_dt = datetime.fromisoformat(str(item['saved_at']))
                item['saved_at_formatted'] = saved_dt.strftime('%d %b %Y, %H:%M')
            except Exception:
                item['saved_at_formatted'] = str(item['saved_at'])

            if 'monthly_summary' in item:
                item['monthly_summary'] = convert_decimal_to_float(item['monthly_summary'])
            if 'category_summary' in item:
                item['category_summary'] = convert_decimal_to_float(item['category_summary'])

        print(f'✅ Retrieved {len(items)} analyses for {user_email}')

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

        print(f'✅ Deleted analysis {analysis_id} for {user_email}')

        return success_response({
            'message': 'Analysis deleted successfully',
            'analysis_id': analysis_id
        })

    except Exception as e:
        print(f'Delete analysis error: {str(e)}')
        import traceback
        traceback.print_exc()
        return error_response(f'Delete failed: {str(e)}', 500)


# -------------------- PDF & PARSING --------------------


def extract_text_from_pdf(pdf_bytes):
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

        print(f'✅ Extracted {len(text)} characters from PDF')
        return text

    except Exception as e:
        raise Exception(f'PDF extraction failed: {str(e)}')


def parse_transactions(content):
    """
    Parses transactions from multiple Irish bank statement formats:
    1. CSV format: date, description, amount
    2. Revolut/N26 style: "01 Nov 2025 TESCO -€25.50"
    3. AIB/BOI style: "01/11/2025 TESCO DUBLIN €25.50"
    4. Generic ISO: "2025-11-01 TESCO €25.50"
    """
    transactions = []
    lines = content.splitlines()

    print(f"📄 Parsing {len(lines)} lines from statement...")

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue

        # Skip pure header lines
        if any(k in line.lower() for k in ['date', 'description', 'amount', 'balance', 'transaction']) \
                and not any(ch.isdigit() for ch in line):
            continue

        # ------------ FORMAT 1: CSV ------------
        if ',' in line:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 3:
                date_str = parts[0]
                desc = parts[1]

                try:
                    amount = float(parts[2])
                except (ValueError, IndexError):
                    amount = None

                if amount is None:
                    continue

                # Parse date
                dt = None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
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

        # ------------ FORMATS 2/3/4: free text ------------
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

        # Remove date and amount to get description
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

        print(f"  ✅ Line {line_num}: {dt.date()} | {desc[:30]} | €{abs(amount):.2f}")

    print(f"🔢 Found {len(transactions)} transactions")
    return transactions


def categorize_expense(description):
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


# -------------------- CONVERSIONS & RESPONSES --------------------


def convert_floats_to_decimal(obj):
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    return obj


def convert_decimal_to_float(obj):
    if isinstance(obj, dict):
        return {k: convert_decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimal_to_float(item) for item in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj


def success_response(data, status_code=200):
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
    return success_response({'error': message}, status_code)
