#!/usr/bin/python
from subprocess import Popen

filename_main = "main.py"
filename_love = "love.py"

while True:
    print("\nStarting " + filename_main + " and " + filename_love)

    # Start main.py
    p_main = Popen("/home/spedymax/venv/bin/python3 " + filename_main, shell=True)

    # Start love.py in parallel
    p_love = Popen("/home/spedymax/venv/bin/python3 " + filename_love, shell=True)

    # Wait for both processes to complete
    p_main.wait()
    p_love.wait()