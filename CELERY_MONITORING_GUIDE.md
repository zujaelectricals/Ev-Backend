# Celery Monitoring Guide for Live Server

This guide provides multiple methods to check if Celery is working properly on your live server.

## Quick Status Check Methods

### 1. Check if Celery Worker Process is Running

**On Linux/Unix Server:**
```bash
# Check if Celery worker process is running
ps aux | grep celery

# Or more specific
ps aux | grep "celery.*worker"

# Check process count
pgrep -f "celery.*worker" | wc -l
```

**Expected Output:**
You should see processes like:
```
user    12345  0.5  2.1  python celery -A ev_backend worker --loglevel=info
```

### 2. Use Celery CLI to Inspect Status

**Connect to your server and run:**
```bash
# Navigate to your project directory
cd /path/to/your/project

# Activate virtual environment (if using one)
source venv/bin/activate  # or your venv path

# Check active workers
celery -A ev_backend inspect active

# Check registered tasks
celery -A ev_backend inspect registered

# Check scheduled tasks
celery -A ev_backend inspect scheduled

# Check reserved tasks (in queue)
celery -A ev_backend inspect reserved

# Get worker stats
celery -A ev_backend inspect stats

# Check if workers are online
celery -A ev_backend inspect ping
```

**Expected Output for `ping`:**
```
-> celery@hostname: OK
```

### 3. Check Redis Connection and Queues

**Connect to Redis CLI:**
```bash
# If Redis is on same server
redis-cli

# Or if Redis is remote
redis-cli -h YOUR_REDIS_HOST -p 6379

# Once connected, check Celery queues
KEYS celery*

# Check specific queue length
LLEN celery  # or your queue name

# Monitor Redis activity in real-time
MONITOR
```

### 4. Test with a Simple Task

**Create a test task file** (`test_celery.py`):
```python
from ev_backend.celery import app
from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task
def test_celery_task(message="Celery is working!"):
    """Simple test task to verify Celery is working"""
    logger.info(f"Test task executed: {message}")
    print(f"Test task executed: {message}")
    return f"Success: {message}"
```

**Run the test:**
```bash
# In Django shell or Python
python manage.py shell

# Then run:
from test_celery import test_celery_task
result = test_celery_task.delay("Hello from live server!")
print(f"Task ID: {result.id}")
print(f"Task State: {result.state}")
print(f"Task Result: {result.get(timeout=10)}")
```

### 5. Check Celery Logs

**Find Celery log files:**
```bash
# Check system logs (if using systemd)
journalctl -u celery -f

# Or check log files directly
tail -f /var/log/celery/worker.log
tail -f /path/to/your/project/logs/celery.log

# If using Docker
docker logs ev_backend_celery -f
docker logs ev_backend_celery_beat -f
```

### 6. Monitor Task Execution in Real-Time

**Use Celery Events:**
```bash
# In one terminal, start event monitoring
celery -A ev_backend events

# In another terminal, trigger a task and watch it execute
```

### 7. Check Django Admin (if django-celery-results is configured)

If you have `django_celery_results` installed:
1. Go to Django Admin: `http://your-server/admin/`
2. Navigate to "Django Celery Results" → "Task results"
3. Check recent task executions and their status

### 8. Test with Your Actual Tasks

**Test the payment_completed task:**
```bash
python manage.py shell
```

```python
from core.booking.tasks import payment_completed
from core.booking.models import Booking

# Get a test booking
booking = Booking.objects.first()

# Trigger the task
result = payment_completed.delay(booking.id, 1000.0)
print(f"Task ID: {result.id}")
print(f"Task State: {result.state}")

# Wait for result (with timeout)
try:
    result.get(timeout=30)
    print("Task completed successfully!")
except Exception as e:
    print(f"Task failed: {e}")
```

## Health Check Script

Create a comprehensive health check script (`check_celery_health.py`):

```python
#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from ev_backend.celery import app
from celery import current_app
import redis
from django.conf import settings

def check_celery_health():
    """Comprehensive Celery health check"""
    print("=" * 60)
    print("CELERY HEALTH CHECK")
    print("=" * 60)
    
    # 1. Check Redis connection
    print("\n1. Checking Redis Connection...")
    try:
        redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        redis_client.ping()
        print("   ✓ Redis connection: OK")
    except Exception as e:
        print(f"   ✗ Redis connection: FAILED - {e}")
        return False
    
    # 2. Check Celery app
    print("\n2. Checking Celery App...")
    try:
        print(f"   ✓ Celery app: {app.main}")
        print(f"   ✓ Broker URL: {settings.CELERY_BROKER_URL}")
        print(f"   ✓ Result Backend: {settings.CELERY_RESULT_BACKEND}")
    except Exception as e:
        print(f"   ✗ Celery app: FAILED - {e}")
        return False
    
    # 3. Check active workers
    print("\n3. Checking Active Workers...")
    try:
        inspect = app.control.inspect()
        active_workers = inspect.active()
        if active_workers:
            print(f"   ✓ Active workers: {len(active_workers)}")
            for worker_name, tasks in active_workers.items():
                print(f"     - {worker_name}: {len(tasks)} active tasks")
        else:
            print("   ⚠ No active workers found!")
            return False
    except Exception as e:
        print(f"   ✗ Worker check: FAILED - {e}")
        return False
    
    # 4. Check registered tasks
    print("\n4. Checking Registered Tasks...")
    try:
        registered = inspect.registered()
        if registered:
            total_tasks = sum(len(tasks) for tasks in registered.values())
            print(f"   ✓ Registered tasks: {total_tasks}")
            # Show some task names
            if registered:
                worker_name = list(registered.keys())[0]
                sample_tasks = list(registered[worker_name])[:5]
                print(f"     Sample tasks: {', '.join(sample_tasks)}")
        else:
            print("   ⚠ No registered tasks found!")
    except Exception as e:
        print(f"   ✗ Task registration check: FAILED - {e}")
    
    # 5. Test task execution
    print("\n5. Testing Task Execution...")
    try:
        from celery import shared_task
        
        @shared_task
        def health_check_task():
            return "OK"
        
        result = health_check_task.delay()
        task_result = result.get(timeout=10)
        print(f"   ✓ Test task executed: {task_result}")
        print(f"   ✓ Task ID: {result.id}")
    except Exception as e:
        print(f"   ✗ Test task: FAILED - {e}")
        return False
    
    print("\n" + "=" * 60)
    print("✓ ALL CHECKS PASSED - Celery is working properly!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = check_celery_health()
    sys.exit(0 if success else 1)
```

**Run the health check:**
```bash
python check_celery_health.py
```

## Common Issues and Solutions

### Issue: No workers found
**Solution:**
```bash
# Start Celery worker
celery -A ev_backend worker --loglevel=info

# Or with systemd
sudo systemctl start celery
sudo systemctl status celery
```

### Issue: Tasks not executing
**Check:**
1. Worker is running: `ps aux | grep celery`
2. Redis is accessible: `redis-cli ping`
3. Tasks are registered: `celery -A ev_backend inspect registered`

### Issue: Connection errors
**Check:**
1. Redis URL in settings matches your Redis server
2. Firewall allows connection to Redis port (6379)
3. Redis server is running: `redis-cli ping`

## Automated Monitoring

### Set up a cron job to check Celery health:
```bash
# Add to crontab (crontab -e)
*/5 * * * * cd /path/to/project && python check_celery_health.py >> /var/log/celery_health.log 2>&1
```

## Using Flower (Optional - Web-based Monitoring)

If you want a web-based monitoring tool:

1. **Install Flower:**
```bash
pip install flower
```

2. **Start Flower:**
```bash
celery -A ev_backend flower --port=5555
```

3. **Access Flower:**
Open browser: `http://your-server:5555`

4. **Add to docker-compose.yml (if using Docker):**
```yaml
flower:
  build: .
  command: celery -A ev_backend flower --port=5555
  ports:
    - "5555:5555"
  env_file:
    - .env
  depends_on:
    - redis
    - celery
```

## Quick One-Liner Check

For a quick status check, run this on your server:
```bash
celery -A ev_backend inspect ping && echo "✓ Celery is working" || echo "✗ Celery is not responding"
```

