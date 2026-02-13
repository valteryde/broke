#!/usr/bin/env python3
"""Simple CLI to restart the Broke Docker container."""

import requests
import sys

UPDATER_URL = "http://localhost:9999/restart"


def restart():
    """Trigger a container restart via the updater sidecar."""
    try:
        print("Requesting container restart...")
        response = requests.post(UPDATER_URL, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            print(f"Success! Container restarted: {result.get('container_id', 'unknown')}")
            return 0
        else:
            print(f"Failed: {response.status_code}")
            print(response.text)
            return 1
            
    except requests.exceptions.ConnectionError:
        print("Cannot connect to updater service. Is it running?")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(restart())
