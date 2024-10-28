import pyautogui
import time

pyautogui.FAILSAFE = False
while True:
    # Move the mouse to the right
    pyautogui.move(100, 0, duration=1)  # Adjust the distance (100) and duration (1) as needed

    # Move the mouse to the left
    pyautogui.move(-100, 0, duration=1)  # Adjust the distance (-100) and duration (1) as needed

    # Wait for 3 minutes (180 seconds)
    time.sleep(60)
