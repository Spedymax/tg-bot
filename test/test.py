import time
import pyautogui
while True:
    # Move the mouse left and right
    pyautogui.moveRel(-100, 0, duration=2)
    pyautogui.moveRel(100, 0, duration=2)

    # Pause for three minutes
    time.sleep(180)
