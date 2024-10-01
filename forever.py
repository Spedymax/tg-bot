#!/usr/bin/python
import os
from subprocess import Popen

filename = "main.py"
script_dir = os.path.dirname(os.path.abspath(__file__))  # Get script directory

while True:
    print("\nStarting " + filename)
    os.chdir(script_dir)  # Change directory to script location (tg-bot)
    p = Popen("python " + filename, shell=True)
    p.wait()