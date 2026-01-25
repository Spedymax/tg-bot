#!/usr/bin/env python3
"""
Script to run the casino mini-app from the root directory
"""

import os
import sys
import subprocess

def main():
    """Run the mini-app"""
    # Change to the miniapp directory
    miniapp_dir = os.path.join(os.path.dirname(__file__), 'miniapp')
    
    if not os.path.exists(miniapp_dir):
        print(f"Error: miniapp directory not found at {miniapp_dir}")
        sys.exit(1)
    
    # Run the mini-app
    try:
        print("Starting Casino Mini-App...")
        print(f"Changing to directory: {miniapp_dir}")
        
        # Change to miniapp directory and run the app
        os.chdir(miniapp_dir)
        subprocess.run([sys.executable, "start_miniapp.py"], check=True)
        
    except KeyboardInterrupt:
        print("\nMini-app stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"Error running mini-app: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
