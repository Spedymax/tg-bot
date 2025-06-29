import os
import random
import subprocess
from datetime import datetime, timedelta

# Function to commit with a specific date
def commit_with_date(commit_message, commit_date):
    commit_command = ['git', 'commit', '--allow-empty', '--date', commit_date, '-m', commit_message]
    subprocess.run(commit_command)

# Function to generate a random date and time within a day
def random_time_on_day(day):
    random_hour = random.randint(0, 23)
    random_minute = random.randint(0, 59)
    random_second = random.randint(0, 59)
    return datetime.combine(day, datetime.min.time()) + timedelta(
        hours=random_hour, minutes=random_minute, seconds=random_second)

# Function to create 1 to 3 commits per day within a date range
def generate_commits(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        num_commits = random.randint(1, 3)  # Choose how many commits to make for the day
        print(f"Making {num_commits} commit(s) on {current_date.strftime('%Y-%m-%d')}")

        for _ in range(num_commits):
            commit_time = random_time_on_day(current_date)
            commit_message = f"Commit on {commit_time.strftime('%Y-%m-%d %H:%M:%S')}"
            commit_with_date(commit_message, commit_time.strftime('%Y-%m-%dT%H:%M:%S'))

        # Move to the next day
        current_date += timedelta(days=1)

# Set start and end dates for the commit range
start_date = datetime.now() - timedelta(days=30)  # Commits starting from 30 days ago
end_date = datetime.now() - timedelta(days=1)     # Until yesterday

# Generate commits
generate_commits(start_date.date(), end_date.date())
