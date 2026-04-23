#!/usr/bin/env python3
"""
API Call Script
This script calls the API endpoint defined in config.json
"""

import json
import requests
import time
from typing import Optional

def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)

def make_api_request(
    config: dict,
    max_retries: int = 3,
    timeout: int = 30
) -> Optional[dict]:
    """
    Make an API request with retry logic.
    
    Args:
        config: Configuration dictionary containing API details
        max_retries: Maximum number of retry attempts
        timeout: Request timeout in seconds
    
    Returns:
        Response data or None if all retries fail
    """
    endpoint = config.get("api_endpoint")
    api_key = config.get("api_key")
    
    if not endpoint:
        raise ValueError("API endpoint not found in config")
    
    headers = {
        "Content-Type": "application/json"
    }
    
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1}/{max_retries}...")
            response = requests.get(
                endpoint,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print("All retries exhausted.")
                return None

def main():
    """Main function to execute API call."""
    print("Loading configuration...")
    config = load_config()
    
    print(f"API Endpoint: {config['api_endpoint']}")
    print(f"Timeout: {config['timeout']}s")
    print(f"Max Retries: {config['retries']}")
    print("-" * 50)
    
    print("Making API request...")
    result = make_api_request(config)
    
    if result:
        print("\nResponse received:")
        print(json.dumps(result, indent=2))
    else:
        print("\nNo response received after all retries.")

if __name__ == "__main__":
    main()
