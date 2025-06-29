#!/usr/bin/env python3
"""
Script to deploy fixes to the server for bot manager scripts and systemd services
Run this script on your Ubuntu server after uploading the fixed files
"""

import os
import shutil
import subprocess
import sys

def run_command(cmd, check=True):
    """Run shell command and print output"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if check and result.returncode != 0:
        print(f"Command failed with return code {result.returncode}")
        sys.exit(1)
    return result

def main():
    print("=== Deploying Bot Manager Fixes ===")
    
    # Stop all services first
    print("\n1. Stopping services...")
    services = ['webhook.service', 'memory_bot.service', 'love_bot.service', 'btc_bot.service', 'songcontest_bot.service']
    for service in services:
        run_command(f"sudo systemctl stop {service}", check=False)
    
    # Copy fixed manager scripts
    print("\n2. Copying fixed manager scripts...")
    
    # Copy fixed memories bot manager
    if os.path.exists("scripts/memories_bot_manager_fixed.py"):
        shutil.copy("scripts/memories_bot_manager_fixed.py", "/home/spedymax/scripts/memories_bot_manager.py")
        print("✓ Fixed memories_bot_manager.py")
    
    # Copy fixed songcontest bot manager
    if os.path.exists("scripts/songcontest_bot_manager_fixed.py"):
        shutil.copy("scripts/songcontest_bot_manager_fixed.py", "/home/spedymax/scripts/songcontest_bot_manager.py")
        print("✓ Fixed songcontest_bot_manager.py")
    
    # Copy songs.py if it doesn't exist
    if not os.path.exists("/home/spedymax/tg-bot/scripts/songs.py"):
        if os.path.exists("scripts/songs.py"):
            shutil.copy("scripts/songs.py", "/home/spedymax/tg-bot/scripts/songs.py")
            print("✓ Created songs.py")
    
    # Set proper permissions
    print("\n3. Setting permissions...")
    run_command("chmod +x /home/spedymax/scripts/*.py")
    run_command("chown spedymax:spedymax /home/spedymax/scripts/*.py")
    
    # Update systemd service files
    print("\n4. Updating systemd services...")
    
    # Fix BTC bot service description
    btc_service_content = """[Unit]
Description=BTC Bot Service
After=network.target

[Service]
Type=simple
User=spedymax
WorkingDirectory=/home/spedymax/tg-bot
ExecStart=/home/spedymax/venv/bin/python3 /home/spedymax/scripts/btc_bot_manager.py
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
"""
    
    with open("/etc/systemd/system/btc_bot.service", "w") as f:
        f.write(btc_service_content)
    print("✓ Fixed btc_bot.service description")
    
    # Create songcontest service if it doesn't exist
    if not os.path.exists("/etc/systemd/system/songcontest_bot.service"):
        songcontest_service_content = """[Unit]
Description=Song Contest Bot Service
After=network.target

[Service]
Type=simple
User=spedymax
WorkingDirectory=/home/spedymax/tg-bot
ExecStart=/home/spedymax/venv/bin/python3 /home/spedymax/scripts/songcontest_bot_manager.py
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
"""
        
        with open("/etc/systemd/system/songcontest_bot.service", "w") as f:
            f.write(songcontest_service_content)
        print("✓ Created songcontest_bot.service")
        
        # Enable the new service
        run_command("sudo systemctl enable songcontest_bot.service")
    
    # Reload systemd
    print("\n5. Reloading systemd...")
    run_command("sudo systemctl daemon-reload")
    
    # Start services
    print("\n6. Starting services...")
    all_services = services + ['songcontest_bot.service']
    for service in all_services:
        run_command(f"sudo systemctl start {service}")
        run_command(f"sudo systemctl enable {service}")
    
    # Check service status
    print("\n7. Checking service status...")
    for service in all_services:
        print(f"\n--- {service} ---")
        run_command(f"sudo systemctl status {service} --no-pager", check=False)
    
    print("\n=== Deployment Complete ===")
    print("All fixes have been applied. Check the service statuses above for any issues.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script must be run as root (use sudo)")
        sys.exit(1)
    main()
