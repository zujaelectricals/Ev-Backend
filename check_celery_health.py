#!/usr/bin/env python
"""
Celery Health Check Script
Run this script to verify Celery is working properly on your live server.

Usage:
    python check_celery_health.py
"""
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
    
    all_checks_passed = True
    
    # 1. Check Redis connection
    print("\n1. Checking Redis Connection...")
    try:
        redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        redis_client.ping()
        print("   ✓ Redis connection: OK")
        print(f"   ✓ Redis URL: {settings.CELERY_BROKER_URL}")
    except Exception as e:
        print(f"   ✗ Redis connection: FAILED - {e}")
        all_checks_passed = False
        return all_checks_passed
    
    # 2. Check Celery app
    print("\n2. Checking Celery App...")
    try:
        print(f"   ✓ Celery app: {app.main}")
        print(f"   ✓ Broker URL: {settings.CELERY_BROKER_URL}")
        print(f"   ✓ Result Backend: {settings.CELERY_RESULT_BACKEND}")
    except Exception as e:
        print(f"   ✗ Celery app: FAILED - {e}")
        all_checks_passed = False
        return all_checks_passed
    
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
            print("   → Start worker with: celery -A ev_backend worker --loglevel=info")
            all_checks_passed = False
    except Exception as e:
        print(f"   ✗ Worker check: FAILED - {e}")
        print("   → This might mean no workers are running")
        all_checks_passed = False
    
    # 4. Check registered tasks
    print("\n4. Checking Registered Tasks...")
    try:
        inspect = app.control.inspect()
        registered = inspect.registered()
        if registered:
            total_tasks = sum(len(tasks) for tasks in registered.values())
            print(f"   ✓ Registered tasks: {total_tasks}")
            # Show some task names
            if registered:
                worker_name = list(registered.keys())[0]
                sample_tasks = list(registered[worker_name])[:10]
                print(f"     Sample tasks:")
                for task in sample_tasks:
                    print(f"       - {task}")
        else:
            print("   ⚠ No registered tasks found!")
            print("   → This might mean workers are not running or not connected")
    except Exception as e:
        print(f"   ✗ Task registration check: FAILED - {e}")
    
    # 5. Check scheduled tasks
    print("\n5. Checking Scheduled Tasks...")
    try:
        inspect = app.control.inspect()
        scheduled = inspect.scheduled()
        if scheduled:
            total_scheduled = sum(len(tasks) for tasks in scheduled.values())
            print(f"   ✓ Scheduled tasks: {total_scheduled}")
        else:
            print("   ✓ No scheduled tasks (this is normal if no tasks are scheduled)")
    except Exception as e:
        print(f"   ⚠ Scheduled check: {e}")
    
    # 6. Check reserved tasks (in queue)
    print("\n6. Checking Queued Tasks...")
    try:
        inspect = app.control.inspect()
        reserved = inspect.reserved()
        if reserved:
            total_reserved = sum(len(tasks) for tasks in reserved.values())
            print(f"   ✓ Queued tasks: {total_reserved}")
        else:
            print("   ✓ No queued tasks")
    except Exception as e:
        print(f"   ⚠ Queue check: {e}")
    
    # 7. Test task execution
    print("\n7. Testing Task Execution...")
    try:
        from celery import shared_task
        
        @shared_task
        def health_check_task():
            return "OK"
        
        result = health_check_task.delay()
        task_result = result.get(timeout=10)
        print(f"   ✓ Test task executed successfully")
        print(f"   ✓ Task ID: {result.id}")
        print(f"   ✓ Task Result: {task_result}")
    except Exception as e:
        print(f"   ✗ Test task: FAILED - {e}")
        print("   → This indicates workers are not processing tasks")
        all_checks_passed = False
    
    # 8. Check worker stats
    print("\n8. Checking Worker Statistics...")
    try:
        inspect = app.control.inspect()
        stats = inspect.stats()
        if stats:
            for worker_name, worker_stats in stats.items():
                print(f"   ✓ Worker: {worker_name}")
                print(f"     - Pool: {worker_stats.get('pool', {}).get('implementation', 'N/A')}")
                print(f"     - Total tasks processed: {worker_stats.get('total', {}).get('tasks.succeeded', 0)}")
        else:
            print("   ⚠ No worker statistics available")
    except Exception as e:
        print(f"   ⚠ Stats check: {e}")
    
    print("\n" + "=" * 60)
    if all_checks_passed:
        print("✓ ALL CHECKS PASSED - Celery is working properly!")
    else:
        print("✗ SOME CHECKS FAILED - Please review the issues above")
    print("=" * 60)
    
    return all_checks_passed

if __name__ == "__main__":
    success = check_celery_health()
    sys.exit(0 if success else 1)

