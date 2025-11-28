from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import os

# Create Flask app (MUST be named 'application' for Elastic Beanstalk)
application = Flask(__name__, static_folder='static', static_url_path='')
CORS(application)


@application.route('/')
def root():
    return send_from_directory('static', 'login.html')


@application.route('/<path:path>')
def serve_static(path: str):
    return send_from_directory('static', path)


@application.route('/api/config', methods=['GET'])
def get_config():
    config = {
        "cognito": {
            "userPoolId": os.environ.get("COGNITO_USER_POOL_ID", ""),
            "clientId": os.environ.get("COGNITO_CLIENT_ID", ""),
            "region": os.environ.get("COGNITO_REGION", "us-east-1"),
        },
        "api": {
            "baseUrl": os.environ.get("API_GATEWAY_URL", "")
        }
    }
    return jsonify(config), 200


@application.route('/health', methods=['GET'])
def health_check():
    """
    Simple health check endpoint for testing.
    """
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    # Run locally for testing
    application.run(debug=True, host="0.0.0.0", port=5000)
