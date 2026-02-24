"""
Gunicorn configuration file for EV Backend
Handles worker crashes, timeouts, and graceful shutdowns

Azure App Service Deployment Notes:
- Port 8000 is correct (Azure App Service maps this automatically)
- Timeout 120s is safe for Razorpay API calls (max ~55s)
- Worker count auto-scales based on CPU cores
- worker_tmp_dir automatically falls back if /dev/shm unavailable
- All settings can be overridden via environment variables
"""
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
worker_connections = 1000
# Request timeout in seconds
# Must be greater than: RAZORPAY_CONNECT_TIMEOUT + RAZORPAY_READ_TIMEOUT + processing overhead
# Current: 10s (connect) + 20s (read) + 1 retry (1s sleep) + ~5s (processing) = ~36s worst case
# Set to 60s to provide safety margin
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 60))
keepalive = 5  # Keep-alive connections

# Limit worker restart frequency to prevent restart storms
worker_tmp_dir = None  # Use default temp directory
capture_output = True  # Capture stdout/stderr
enable_stdio_inheritance = False  # Don't inherit file descriptors

# Worker lifecycle
max_requests = 1000  # Restart worker after this many requests (prevents memory leaks)
max_requests_jitter = 50  # Random jitter to prevent all workers restarting at once
preload_app = False  # Set to True if you have memory issues, but may cause issues with some apps

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"  # Log to stderr
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "ev_backend"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Graceful timeout - time to wait for workers to finish before killing them
graceful_timeout = 30

# Worker timeout - time to wait for a worker to process a request
# Use shared memory for worker temp files (faster) if available (Linux only)
# Azure App Service may not have /dev/shm, so check if it exists
if os.path.exists("/dev/shm"):
    worker_tmp_dir = "/dev/shm"
else:
    # Fallback to default temp directory (works on Azure App Service)
    worker_tmp_dir = None

# SSL (if needed in future)
# keyfile = None
# certfile = None

def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting EV Backend Gunicorn server")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Reloading EV Backend Gunicorn server")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("EV Backend Gunicorn server is ready. Spawning workers")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    pass

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    pass

def worker_int(worker):
    """Called when a worker receives the INT or QUIT signal."""
    worker.log.info("Worker received INT or QUIT signal")

def pre_exec(server):
    """Called just before a new master process is forked."""
    server.log.info("Forking new master process")

def on_exit(server):
    """Called just before exiting Gunicorn."""
    server.log.info("Shutting down EV Backend Gunicorn server")

def worker_abort(worker):
    """Called when a worker times out or is killed."""
    import traceback
    worker.log.warning(f"Worker {worker.pid} aborted (timeout or killed)")
    worker.log.warning(f"Worker abort traceback:\n{traceback.format_exc()}")

def worker_exit(server, worker):
    """Called just after a worker has been exited, in the master process."""
    server.log.info(f"Worker {worker.pid} exited")

def nworkers_changed(server, new_value, old_value):
    """Called just after num_workers has been changed."""
    server.log.info(f"Worker count changed from {old_value} to {new_value}")

