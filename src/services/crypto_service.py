import logging
from openpyxl import load_workbook
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CryptoService:
    """Service for handling encrypted configuration files."""
    
    def __init__(self, crypto_module):
        """Initialize with a crypto module that provides decrypt_file function."""
        self.crypto_module = crypto_module
    
    def decrypt_and_load_config(self, encrypted_file: str, decrypted_file: str) -> Dict[str, Optional[str]]:
        """Decrypt file and load configuration from Excel."""
        try:
            # Decrypt the file
            self.crypto_module.decrypt_file(encrypted_file, decrypted_file)
            
            # Load workbook
            workbook = load_workbook(filename=decrypted_file)
            sheet = workbook.active
            
            # Read API keys from cells
            config = {
                'openai_api_key': sheet['A1'].value,
                'google_api_key': sheet['A2'].value
            }
            
            logger.info("Configuration loaded successfully from decrypted file")
            return config
            
        except Exception as e:
            logger.error(f"Error loading encrypted config: {str(e)}")
            return {
                'openai_api_key': None,
                'google_api_key': None
            }
    
    def get_openai_client(self, api_key: str):
        """Get OpenAI client with provided API key."""
        try:
            from openai import OpenAI
            return OpenAI(api_key=api_key)
        except ImportError:
            logger.error("OpenAI library not installed")
            return None
    
    def get_google_client(self, api_key: str):
        """Get Google Generative AI client with provided API key."""
        try:
            from google import genai
            return genai.Client(api_key=api_key)
        except ImportError:
            logger.error("Google Generative AI library not installed")
            return None
