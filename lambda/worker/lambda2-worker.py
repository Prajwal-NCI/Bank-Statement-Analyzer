import json
import boto3
import PyPDF2
import re
from io import BytesIO
from datetime import datetime
from decimal import Decimal

# Import your TaxCalculator
from invoice_tax_pkg import TaxCalculator

# AWS Clients
s3_client = boto3.client('s3')
dynamo = boto3.resource('dynamodb')

DYNAMODB_TABLE = 'user_analyses'

def lambda_handler(event, context):
    """Process PDF analysis messages from SQS"""
    
    for record in event['Records']:
        try:
            # Parse SQS message
            message = json.loads(record['body'])
            
            bucket = message['bucket']
            key = message['key']
            country_code = message['country_code']
            user_email = message['user_email']
            file_name = message['file_name']
            
            print(f"📥 Processing: {file_name} for {user_email}")
            
            # Download PDF from S3
            response = s3_client.get_object(Bucket=bucket, Key=key)
            pdf_bytes = response['Body'].read()
            
            print(f"📄 Downloaded {len(pdf_bytes)} bytes from S3")
            
            # Analyze PDF
            analysis_result = analyze_pdf(pdf_bytes, country_code)
            
            print(f"✅ Analysis complete: {analysis_result.get('transaction_count', 0)} transactions")
            
            # Save to DynamoDB
            save_analysis_to_dynamo(user_email, file_name, analysis_result, country_code)
            
            print(f"✅ Saved to DynamoDB for {user_email}")
            
        except Exception as e:
            print(f"❌ Error processing message: {str(e)}")
            import traceback
            traceback.print_exc()
            raise  # Re-raise to keep message in queue for retry


# ============================================================================
# PDF ANALYSIS FUNCTIONS
# ============================================================================
def analyze_pdf(pdf_bytes, country_code):
    """Analyze PDF and return structured data"""
    try:
        # Extract text from PDF
        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        
        print(f"📝 Extracted {len(text)} characters from PDF")
        
        # Parse transactions
        transactions = parse_transactions(text)
        print(f"🔢 Found {len(transactions)} transactions")
        
        if not transactions:
            return {
                'transaction_count': 0,
                'country_code': country_code,
                'mode': 'standard',
                'monthly_summary': {},
                'category_summary': {}
            }
        
        # Calculate analysis with VAT
        calculator = TaxCalculator()
        analysis = calculate_analysis(transactions, calculator, country_code)
        
        return analysis
        
    except Exception as e:
        print(f"❌ PDF analysis error: {str(e)}")
        raise


def parse_transactions(text):
    """Parse transactions from bank statement text"""
    transactions = []
    lines = text.split('\n')
    
    for line in lines:
        # Match patterns like: "01 Nov Amazon -50.00"
        match = re.search(r'(\d{1,2}\s+\w{3})\s+(.+?)\s+([-]?\d+\.\d{2})', line)
        if match:
            date_str, description, amount_str = match.groups()
            amount = float(amount_str)
            
            if amount < 0:  # Only debit transactions
                transactions.append({
                    'date': date_str,
                    'description': description.strip(),
                    'amount': abs(amount),
                    'category': categorize(description)
                })
    
    return transactions


def categorize(description):
    """Categorize transaction based on description"""
    desc_lower = description.lower()
    
    if any(word in desc_lower for word in ['amazon', 'shop', 'store', 'retail']):
        return 'Shopping'
    elif any(word in desc_lower for word in ['restaurant', 'cafe', 'food', 'uber eats']):
        return 'Food & Dining'
    elif any(word in desc_lower for word in ['netflix', 'spotify', 'subscription']):
        return 'Entertainment'
    elif any(word in desc_lower for word in ['transport', 'uber', 'taxi', 'bus']):
        return 'Transport'
    elif any(word in desc_lower for word in ['electricity', 'gas', 'water', 'utility']):
        return 'Utilities'
    else:
        return 'Other'


def calculate_analysis(transactions, calculator, country_code):
    """Calculate spending analysis with VAT"""
    monthly_summary = {}
    category_summary = {}
    
    for tx in transactions:
        amount = tx['amount']
        category = tx['category']
        
        # Extract VAT from gross amount
        vat, net = calculator.extract_vat(amount, country_code)
        
        # Get month
        month = tx['date'].split()[1]  # e.g., "Nov"
        
        # Update monthly summary
        if month not in monthly_summary:
            monthly_summary[month] = {
                'net_total': 0,
                'vat_total': 0,
                'gross_total': 0,
                'by_category': {}
            }
        
        monthly_summary[month]['net_total'] += net
        monthly_summary[month]['vat_total'] += vat
        monthly_summary[month]['gross_total'] += amount
        
        if category not in monthly_summary[month]['by_category']:
            monthly_summary[month]['by_category'][category] = 0
        monthly_summary[month]['by_category'][category] += amount
        
        # Update category summary
        if category not in category_summary:
            category_summary[category] = {
                'net': 0,
                'vat': 0,
                'gross': 0,
                'count': 0,
                'by_month': {}
            }
        
        category_summary[category]['net'] += net
        category_summary[category]['vat'] += vat
        category_summary[category]['gross'] += amount
        category_summary[category]['count'] += 1
        
        if month not in category_summary[category]['by_month']:
            category_summary[category]['by_month'][month] = {
                'net': 0,
                'vat': 0,
                'gross': 0,
                'count': 0
            }
        
        category_summary[category]['by_month'][month]['net'] += net
        category_summary[category]['by_month'][month]['vat'] += vat
        category_summary[category]['by_month'][month]['gross'] += amount
        category_summary[category]['by_month'][month]['count'] += 1
    
    return {
        'transaction_count': len(transactions),
        'country_code': country_code,
        'mode': 'standard',
        'monthly_summary': monthly_summary,
        'category_summary': category_summary
    }


# ============================================================================
# SAVE TO DYNAMODB
# ============================================================================
def save_analysis_to_dynamo(user_email, file_name, analysis, country_code):
    """Save analysis results to DynamoDB"""
    table = dynamo.Table(DYNAMODB_TABLE)
    
    # Calculate totals
    monthly = analysis.get('monthly_summary', {})
    total_net = sum(float(m.get('net_total', 0)) for m in monthly.values())
    total_vat = sum(float(m.get('vat_total', 0)) for m in monthly.values())
    total_gross = sum(float(m.get('gross_total', 0)) for m in monthly.values())
    
    analysis_id = str(int(datetime.utcnow().timestamp() * 1000))
    saved_at = datetime.utcnow().isoformat()
    
    item = {
        'user_email': user_email,
        'analysis_id': analysis_id,
        'saved_at': saved_at,
        'file_name': file_name,
        'country_code': country_code,
        'total_gross': Decimal(str(round(total_gross, 2))),
        'total_net': Decimal(str(round(total_net, 2))),
        'total_vat': Decimal(str(round(total_vat, 2))),
        'transaction_count': analysis.get('transaction_count', 0),
        'monthly_summary': convert_to_decimal(monthly),
        'category_summary': convert_to_decimal(analysis.get('category_summary', {}))
    }
    
    table.put_item(Item=item)
    print(f"✅ Analysis saved: {analysis_id}")


def convert_to_decimal(obj):
    """Convert floats to Decimal for DynamoDB"""
    if isinstance(obj, dict):
        return {k: convert_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_decimal(item) for item in obj]
    elif isinstance(obj, float):
        return Decimal(str(round(obj, 2)))
    return obj
