#!/usr/bin/env python3
"""
Start script for the casino mini-app
"""

import os
import sys
import logging
from app import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    """Main entry point for the mini-app"""
    try:
        logger.info("Starting Casino Mini-App...")
        
        # Print some useful information
        logger.info("Casino Mini-App is running on:")
        logger.info("- Local: http://localhost:5000")
        logger.info("- Network: http://0.0.0.0:5000")
        logger.info("")
        logger.info("Available endpoints:")
        logger.info("- GET  /           - Main casino page")
        logger.info("- GET  /casino     - Alternative casino page")
        logger.info("- GET  /api/player/<id> - Get player data")
        logger.info("- POST /api/spin   - Spin the wheel")
        logger.info("- POST /api/save_progress - Save player progress")
        logger.info("- GET  /health     - Health check")
        logger.info("")
        logger.info("Press Ctrl+C to stop the server")
        
        # Run the Flask app
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=True,
            use_reloader=False
        )
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
