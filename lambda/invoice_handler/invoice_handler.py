import json
import re
import os
from datetime import datetime
import boto3
from io import BytesIO
import base64
from decimal import Decimal

try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    from invoice_tax_pkg import TaxCalculator
except ImportError:
    TaxCalculator = None

s3_client = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
sqs_client = boto3.client('sqs')

S3_BUCKET = os.environ.get('S3_BUCKET_NAME', 'invoice-management-bucket-prajwal-nci')
USER_ANALYSES_TABLE = os.environ.get('DYNAMODB_TABLE_NAME', 'user_analyses')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/556192680160/BankStatementAnalysisQueue')

def lambda_handler(event, context):
    try:
        http_method = event.get('httpMethod', '')
        path = event.get('path', '')
        
        if path == '/health' and http_method == 'GET':
            return success_response({
                'status': 'healthy',
                'service': 'bank-analyzer-api',
                'pdf_support': PDF_SUPPORT,
                's3_bucket': S3_BUCKET,
                'dynamodb_table': USER_ANALYSES_TABLE,
                'sqs_queue': SQS_QUEUE_URL,
                'timestamp': datetime.utcnow().isoformat()
            })
        elif path == '/upload' and http_method == 'POST':
            return handle_upload(event)
        elif path == '/delete' and http_method == 'POST':
            return handle_delete_file(event)
        elif path == '/bank/analyze' and http_method == 'POST':
            return handle_bank_analyze(event)
        elif path == '/bank/save-analysis' and http_method == 'POST':
            return handle_save_analysis(event)
        elif path == '/bank/my-analyses' and http_method == 'POST':
            return handle_get_user_analyses(event)
        elif path == '/bank/delete-analysis' and http_method == 'POST':
            return handle_delete_analysis(event)
        else:
            return error_response('Unknown endpoint', 404)
    except Exception as e:
        return error_response('Internal server error: {}'.format(str(e)), 500)

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
            return error_response('Invalid base64 content: {}'.format(str(e)), 400)

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType=content_type
        )

        return success_response({
            'message': 'File uploaded successfully',
            'bucket': S3_BUCKET,
            'key': filename,
            's3_url': 's3://{}/{}'.format(S3_BUCKET, filename)
        }, 201)

    except Exception as e:
        return error_response('Upload failed: {}'.format(str(e)), 500)

def handle_delete_file(event):
    try:
        body = json.loads(event.get('body') or '{}')
        bucket = body.get('bucket', '').strip()
        key = body.get('key', '').strip()

        if not bucket or not key:
            return error_response('bucket and key are required', 400)

        s3_client.delete_object(Bucket=bucket, Key=key)

        return success_response({
            'message': 'File deleted successfully',
            'bucket': bucket,
            'key': key
        })

    except Exception as e:
        return error_response('Delete failed: {}'.format(str(e)), 500)

def handle_bank_analyze(event):
    try:
        body = json.loads(event.get('body') or '{}')
        bucket = body.get('bucket', '').strip()
        key = body.get('key', '').strip()
        country_code = body.get('country_code', 'IE').upper()
        user_email = body.get('user_email', '').strip()

        if not bucket or not key:
            return error_response('bucket and key are required', 400)
        if not user_email:
            return error_response('user_email is required', 400)

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
        except Exception as sqs_error:
            return error_response('Failed to queue analysis: {}'.format(str(sqs_error)), 500)

        return success_response({
            'message': 'Analysis queued successfully',
            'status': 'processing',
            'file': key,
            'user_email': user_email,
            'message_id': message_id,
            'note': 'Check back in 30-60 seconds for results'
        }, 202)

    except Exception as e:
        return error_response('Analysis failed: {}'.format(str(e)), 500)

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
        
        fingerprint = '{}_{}_{}_{}'.format(file_name, round(total_gross, 2), num_tx, months_sorted)

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
                
                return success_response({
                    'message': 'This analysis was already saved previously',
                    'analysis_id': str(existing_item['analysis_id']),
                    'saved_at': str(existing_item['saved_at']),
                    'saved_at_formatted': saved_formatted,
                    'is_duplicate': True
                })
        except Exception:
            pass

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
        
        return success_response({
            'message': 'Analysis saved successfully',
            'analysis_id': analysis_id,
            'saved_at': saved_at,
            'saved_at_formatted': saved_formatted,
            'is_duplicate': False
        }, 201)
        
    except Exception as e:
        return error_response('Save failed: {}'.format(str(e)), 500)

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
        
        return success_response({
            'analyses': items,
            'count': len(items)
        })

    except Exception as e:
        return error_response('Fetch failed: {}'.format(str(e)), 500)

def handle_delete_analysis(event):
    try:
        body = json.loads(event.get('body') or '{}')
        user_email = body.get('user_email', '').strip()
        analysis_id = body.get('analysis_id', '').strip()

        if not user_email or not analysis_id:
            return error_response('user_email and analysis_id required', 400)

        table = dynamo.Table(USER_ANALYSES_TABLE)
        table.delete_item(Key={'user_email': user_email, 'analysis_id': analysis_id})
        
        return success_response({
            'message': 'Analysis deleted successfully',
            'analysis_id': analysis_id
        })
        
    except Exception as e:
        return error_response('Delete failed: {}'.format(str(e)), 500)

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
