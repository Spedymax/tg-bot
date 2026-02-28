"""
Gunicorn configuration for Casino Mini-App
"""
import multiprocessing

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Worker processes
workers = 4  # (CPU cores × 2) + 1, assuming 2 cores
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 2

# Environment variables
import os
os.environ['GUNICORN_WORKERS'] = str(workers)

# Worker lifecycle
max_requests = 1000
max_requests_jitter = 50
graceful_timeout = 30

# Logging
chdir = '/home/spedymax/tg-bot/miniapp'
accesslog = '/home/spedymax/logs/casino-miniapp-access.log'
errorlog = '/home/spedymax/logs/casino-miniapp-error.log'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'casino-miniapp'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = 'www-data'
group = 'www-data'
tmp_upload_dir = None

# SSL (if needed in future)
# keyfile = None
# certfile = None

def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Gunicorn master starting")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Gunicorn reloading")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Gunicorn is ready. Spawning workers")

def on_exit(server):
    """Called just before exiting Gunicorn."""
    server.log.info("Gunicorn shutting down")
