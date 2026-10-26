"""Run one web server and one sequential scraper on the same persistent disk."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent


def main():
    from db.database import initialize_database
    from app.app import app  # Fail before starting children if login is missing.
    initialize_database()
    interval = int(os.environ.get('SCRAPE_INTERVAL_SECONDS', '3600'))
    if interval < 300:
        raise ValueError('SCRAPE_INTERVAL_SECONDS must be at least 300')
    port = int(os.environ.get('PORT', '10000'))
    stop = threading.Event()
    children = []

    def shutdown(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    web = subprocess.Popen([sys.executable, '-m', 'gunicorn', '--bind', f'0.0.0.0:{port}',
                            '--workers', '1', '--threads', '1', '--access-logfile', '-',
                            '--error-logfile', '-', 'wsgi:app'], cwd=ROOT)
    children.append(web)
    scrape = None
    next_run = time.monotonic()
    result = 0
    try:
        while not stop.wait(1):
            if web.poll() is not None:
                result = web.returncode or 1
                break
            if scrape is not None and scrape.poll() is not None:
                print(f'Scraper exited with status {scrape.returncode}', flush=True)
                children.remove(scrape)
                scrape = None
                next_run = time.monotonic() + interval
            if scrape is None and time.monotonic() >= next_run:
                scrape = subprocess.Popen([sys.executable, '-u', 'run_scraper.py'], cwd=ROOT)
                children.append(scrape)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return result


if __name__ == '__main__':
    sys.exit(main())
