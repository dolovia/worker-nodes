#!/usr/bin/env python3
"""
Long-running worker that polls for tasks and self-restarts before GitHub kills it.
Sends logs to Telegram for monitoring.
"""

import os
import time
import json
import subprocess
import sys
import requests
from datetime import datetime
from collections import deque

# Configuration
WORKER_ID = os.environ.get("WORKER_ID", "worker_001")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", "340"))
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Telegram config
TELEGRAM_BOT_TOKEN = "1032666313:AAGaaiIoN5P7qGmVral3rSAAyptq1aeLzRU"
TELEGRAM_CHAT_ID = "848696652"

START_TIME = time.time()
MAX_RUNTIME_SECONDS = MAX_RUNTIME_MINUTES * 60

# Message queue for Telegram (batch sends to avoid spam)
MESSAGE_QUEUE = deque(maxlen=50)
LAST_TELEGRAM_SEND = 0
TELEGRAM_BATCH_INTERVAL = 30  # Send batched logs every 30 seconds


class TelegramLogger:
    """Send logs to Telegram."""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.enabled = True
    
    def send_message(self, text, parse_mode="HTML"):
        """Send a message to Telegram."""
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"[Telegram Error] {e}", file=sys.stderr)
            return False
    
    def send_batch(self, messages):
        """Send multiple messages as one batch."""
        if not messages or not self.enabled:
            return False
        
        try:
            text = "\n".join(messages)
            # Limit to 4096 chars (Telegram limit)
            if len(text) > 4000:
                text = text[-4000:]
            
            return self.send_message(text)
        except Exception as e:
            print(f"[Telegram Error] {e}", file=sys.stderr)
            return False


# Initialize Telegram logger
tg = TelegramLogger(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)


def log(message, telegram=True):
    """Print timestamped logs and optionally send to Telegram."""
    timestamp = datetime.now().isoformat()
    formatted = f"[{timestamp}] [{WORKER_ID}] {message}"
    
    print(formatted)
    
    if telegram and tg.enabled:
        MESSAGE_QUEUE.append(formatted)


def send_batched_logs():
    """Send accumulated logs to Telegram."""
    global LAST_TELEGRAM_SEND
    
    now = time.time()
    if now - LAST_TELEGRAM_SEND > TELEGRAM_BATCH_INTERVAL:
        if MESSAGE_QUEUE:
            messages = list(MESSAGE_QUEUE)
            if tg.send_batch(messages):
                MESSAGE_QUEUE.clear()
            LAST_TELEGRAM_SEND = now


def should_restart_soon():
    """Check if we're approaching the 6-hour timeout."""
    elapsed = time.time() - START_TIME
    remaining = MAX_RUNTIME_SECONDS - elapsed
    
    if remaining < 600:
        log(f"⏰ Approaching timeout in {remaining/60:.1f} minutes — triggering restart")
        return True
    return False


def trigger_self_restart():
    """Dispatch a new workflow run via GitHub CLI."""
    try:
        log("🔄 Triggering self-restart via GitHub API...")
        
        cmd = [
            "gh", "workflow", "run", "worker.yml",
            "--ref", "main",
            "-f", f"worker_id={WORKER_ID}"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            log(f"✅ Restart triggered: {result.stdout.strip()}")
            return True
        else:
            log(f"❌ Restart failed: {result.stderr}")
            return False
            
    except Exception as e:
        log(f"❌ Error triggering restart: {e}")
        return False


def fetch_task():
    """
    Fetch task from coordinator.
    Replace this with your real API endpoint.
    """
    # TODO: Replace with real coordinator API
    # response = requests.get("https://your-coordinator.com/tasks/next")
    # return response.json()
    
    # Demo: return a task
    return {
        "id": f"task_{int(time.time())}",
        "type": "demo_work",
        "data": {}
    }


def execute_task(task):
    """Execute the task."""
    log(f"📋 Executing: {task['id']}")
    
    try:
        time.sleep(2)  # Simulate work
        
        result = {
            "task_id": task["id"],
            "status": "completed",
            "output": "Success"
        }
        
        log(f"✓ Completed: {task['id']}")
        return result
        
    except Exception as e:
        log(f"✗ Failed: {e}")
        return {
            "task_id": task["id"],
            "status": "failed",
            "error": str(e)
        }


def report_result(result):
    """Report result to coordinator."""
    log(f"📤 Result: {result['task_id']} → {result['status']}")
    
    # TODO: POST to coordinator API
    # requests.post("https://your-coordinator.com/tasks/complete", json=result)


def main():
    """Main worker loop."""
    log(f"🚀 Worker {WORKER_ID} starting | Max runtime: {MAX_RUNTIME_MINUTES}min")
    log(f"📍 Telegram logging: {'✓ Enabled' if tg.enabled else '✗ Disabled'}")
    
    # Send startup message to Telegram
    if tg.enabled:
        tg.send_message(
            f"🚀 <b>Worker {WORKER_ID}</b> started\n"
            f"⏱️ Max runtime: {MAX_RUNTIME_MINUTES}min\n"
            f"📍 Poll interval: {POLL_INTERVAL}s"
        )
    
    task_count = 0
    
    while True:
        # Check timeout
        if should_restart_soon():
            trigger_self_restart()
            
            # Final message to Telegram
            if tg.enabled:
                tg.send_message(
                    f"👋 <b>Worker {WORKER_ID}</b> restarting\n"
                    f"✓ Tasks completed: {task_count}"
                )
            
            log("👋 Exiting to allow restart")
            break
        
        # Process work
        try:
            task = fetch_task()
            result = execute_task(task)
            report_result(result)
            task_count += 1
        except Exception as e:
            log(f"⚠️  Error: {e}")
        
        # Send batched logs periodically
        send_batched_logs()
        
        # Status log every 10 minutes
        elapsed = (time.time() - START_TIME) / 60
        if int(elapsed) % 10 == 0 and int(elapsed) > 0:
            remaining = (MAX_RUNTIME_SECONDS - (time.time() - START_TIME)) / 60
            log(f"📊 {task_count} tasks | {elapsed:.0f}min elapsed | {remaining:.0f}min remaining")
        
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("⛔ Interrupted")
        if tg.enabled:
            tg.send_message(f"⛔ <b>Worker {WORKER_ID}</b> interrupted")
        sys.exit(0)
    except Exception as e:
        log(f"💥 Fatal: {e}")
        if tg.enabled:
            tg.send_message(f"💥 <b>Worker {WORKER_ID}</b> crashed: {e}")
        sys.exit(1)
