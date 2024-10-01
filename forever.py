#!/usr/bin/python
import os
from subprocess import Popen

filename = "main.py"

while True:
    print("\nStarting " + filename)
    p = Popen("/home/spedymax/venv/bin/python3 " + filename, shell=True)
    p.wait()
