import requests
import json

def call_api(endpoint, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # In a real scenario, these would be loaded from config.json
    # For this script, we assume the user provides them or they are hardcoded for demonstration
    ENDPOINT = "https://api.example.com/v1/data"
    API_KEY = "your_api_key_here"
    
    print(f"Calling endpoint: {ENDPOINT}")
    result = call_api(ENDPOINT, API_KEY)
    print("Response:", json.dumps(result, indent=4))
