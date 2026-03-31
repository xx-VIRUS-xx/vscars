import qrcode
from io import BytesIO
import base64
import json
from datetime import datetime
import uuid

def generate_qr_code(data: dict) -> str:
    """
    Generate QR code and return as base64 encoded image
    
    Args:
        data: Dictionary containing authentication info
        
    Returns:
        Base64 encoded PNG image
    """
    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    
    # Add data to QR code
    qr.add_data(json.dumps(data))
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return img_str

def create_qr_auth_token(username: str, email: str, device_id: str) -> tuple:
    """
    Create QR code data for authentication
    
    Args:
        username: Username requesting access
        email: User email
        device_id: Device identifier
        
    Returns:
        Tuple of (qr_code_image_base64, qr_data)
    """
    request_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    qr_data = {
        "request_id": request_id,
        "username": username,
        "email": email,
        "device_id": device_id,
        "timestamp": timestamp,
        "type": "access_request"
    }
    
    qr_image = generate_qr_code(qr_data)
    
    return qr_image, request_id

def parse_qr_data(qr_string: str) -> dict:
    """Parse QR code data"""
    try:
        return json.loads(qr_string)
    except json.JSONDecodeError:
        return {}
