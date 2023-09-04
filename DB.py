import os
import psycopg2
from datetime import datetime


# Get the database URL from environment variables
database_url = os.environ.get('postgres://swwnmrmvibkaln:9f127f6402cc566666445efbca44e4bbc8c4f48cf0ab3a1a8d27261bd874fac3@ec2-54-73-22-169.eu-west-1.compute.amazonaws.com:5432/d10jl00d7m0v3k')

# Establish a database connection
conn=psycopg2.connect(
  database="d10jl00d7m0v3k",
  user="swwnmrmvibkaln",
  host="ec2-54-73-22-169.eu-west-1.compute.amazonaws.com",
  password="9f127f6402cc566666445efbca44e4bbc8c4f48cf0ab3a1a8d27261bd874fac3",
  sslmode='require'
)

# Create a cursor for executing SQL queries
cursor = conn.cursor()

# Read data from "last_used.txt" and insert into the database
with open("coins.txt", "r") as f:
    for line in f:
        user_id, coins = line.strip().split()
        cursor.execute("INSERT INTO user_data (user_id, coins) VALUES (%s, %s)", (user_id, coins))

# Commit the changes and close the connection
conn.commit()
cursor.close()
conn.close()