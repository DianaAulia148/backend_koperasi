import requests
import json

BASE_URL = "http://127.0.0.1:5000/api/member/status"

test_ids = [1, 6, 12] # 1 and 6 are approved, 12 is not_started

for uid in test_ids:
    print(f"\nTesting User ID: {uid}")
    try:
        response = requests.get(f"{BASE_URL}/{uid}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")
