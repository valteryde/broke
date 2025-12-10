import pytest
import subprocess
import time
import socket
import os
import signal
import requests

def wait_for_server(url, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            requests.get(url)
            return True
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    return False

@pytest.fixture(scope="session")
def run_server():
    # Start the server as a subprocess
    # We use preexec_fn=os.setsid to ensure we can kill the whole process group
    server = subprocess.Popen(
        ["python3", "server/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid 
    )

    base_url = "http://localhost:5000"
    
    if not wait_for_server(base_url):
        os.killpg(os.getpgid(server.pid), signal.SIGTERM)
        pytest.fail("Server failed to start")

    yield base_url

    # Cleanup: Kill the server process group
    os.killpg(os.getpgid(server.pid), signal.SIGTERM)
