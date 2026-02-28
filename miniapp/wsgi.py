#!/usr/bin/env python3
"""
WSGI entry point for Casino Mini-App with Gunicorn
"""
import os
import sys
import logging

# Set up paths
miniapp_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(miniapp_dir)
parent_dir = os.path.dirname(miniapp_dir)
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'src'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import the Flask app
from app import app as application

if __name__ == "__main__":
    application.run()
