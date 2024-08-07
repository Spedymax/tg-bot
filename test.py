import time
import pyautogui
import cv2
import numpy as np
from pynput import keyboard

# Flag to stop the script
stop_flag = False

# Coordinates and dimensions of the game screen region (x, y, width, height)
# These values need to be set according to your game window's location and size
GAME_REGION = (100, 100, 600, 1000)  # Example values, adjust accordingly

# Function to handle key press
def on_press(key):
    global stop_flag
    try:
        if key == keyboard.Key.alt_l and keyboard.KeyCode.from_char('k'):
            stop_flag = True
            return False  # Stop listener
    except AttributeError:
        pass

# Function to find green objects on the screen and click the first one (highest)
def locate_and_click_green():
    x, y, width, height = GAME_REGION
    screen = pyautogui.screenshot(region=(x, y, width, height))
    screen_np = np.array(screen)
    hsv = cv2.cvtColor(screen_np, cv2.COLOR_RGB2HSV)

    # Define the range for green color in HSV
    lower_green = np.array([40, 40, 40])
    upper_green = np.array([80, 255, 255])

    # Create a mask for green color
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        # Sort contours by their y-position (descending order)
        contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[1], reverse=True)
        x_offset, y_offset, w, h = cv2.boundingRect(contours[0])

        # Click at the center of the first detected green object (highest)
        pyautogui.click(x + x_offset + w // 2, y + y_offset + h // 2)

# Start the keyboard listener
listener = keyboard.Listener(on_press=on_press)
listener.start()

try:
    while not stop_flag:
        locate_and_click_green()
        time.sleep(np.random.uniform(0.00005, 0.005))
finally:
    listener.stop()
