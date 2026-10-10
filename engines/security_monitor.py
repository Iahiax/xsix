import os
import json
import time
import threading
import logging
from datetime import datetime

logging.basicConfig(filename='./storage/logs/system_audit.log', level=logging.INFO,
                    format='%(asctime)s | %(levelname)s | %(message)s')

class SecurityMonitor:
    def __init__(self):
        self.mutex = threading.Lock()
        self.rate_limit = {}
        self.max_requests_per_min = 60
        
    def acquire_execution_lock(self, timeout=1.5):
        self.mutex.acquire(timeout=timeout)
        return self.mutex.locked()
        
    def release_lock(self):
        self.mutex.release()
        
    def check_rate_limit(self, client_ip: str) -> bool:
        now = time.time()
        self.rate_limit[client_ip] = [t for t in self.rate_limit.get(client_ip, []) if now - t < 60]
        if len(self.rate_limit[client_ip]) >= self.max_requests_per_min:
            return False
        self.rate_limit[client_ip].append(now)
        return True
        
    def log_action(self, action: str, details: dict):
        logging.info(f"{action} | {json.dumps(details)}")
        
    def generate_crash_dump(self, error: Exception):
        dump = {
            "timestamp": datetime.now().isoformat(),
            "error": str(error),
            "traceback": error.__traceback__.tb_lineno if error.__traceback__ else None,
            "system_state": "critical_halt"
        }
        with open('./storage/logs/crash_dump.json', 'w') as f:
            json.dump(dump, f, indent=2)
        self.log_action("CRASH_DUMP_GENERATED", dump)


