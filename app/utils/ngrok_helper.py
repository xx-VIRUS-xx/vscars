from pyngrok import ngrok
from app.config import NGROK_AUTH_TOKEN, NGROK_ENABLED
import os

class NgrokManager:
    """Manage ngrok tunnels for remote access"""
    
    _tunnel = None
    _public_url = None
    
    @classmethod
    def start_tunnel(cls, port: int = 8000) -> str:
        """
        Start ngrok tunnel
        
        Args:
            port: Local port to expose
            
        Returns:
            Public URL
        """
        if not NGROK_ENABLED:
            return None
        
        if NGROK_AUTH_TOKEN:
            ngrok.set_auth_token(NGROK_AUTH_TOKEN)
        
        try:
            # Kill existing tunnels
            ngrok.kill()
            
            # Start new tunnel
            cls._tunnel = ngrok.connect(port, "http")
            cls._public_url = cls._tunnel.public_url
            
            print(f"✅ Ngrok tunnel started: {cls._public_url}")
            return cls._public_url
            
        except Exception as e:
            print(f"❌ Failed to start ngrok: {e}")
            return None
    
    @classmethod
    def stop_tunnel(cls) -> None:
        """Stop ngrok tunnel"""
        try:
            ngrok.disconnect(cls._public_url)
            ngrok.kill()
            cls._tunnel = None
            cls._public_url = None
            print("✅ Ngrok tunnel stopped")
        except Exception as e:
            print(f"⚠️ Error stopping ngrok: {e}")
    
    @classmethod
    def get_public_url(cls) -> str:
        """Get current public URL"""
        return cls._public_url
    
    @classmethod
    def is_active(cls) -> bool:
        """Check if tunnel is active"""
        return cls._tunnel is not None
