import requests
import json
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Update this to your deployed API URL
API_URL = "http://localhost:8000"

# AWS credentials (from environment or hardcoded for testing)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "your_access_key_id")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "your_secret_key")

def call_chat_api(messages, stream=False):
    """Call the proxy API with OpenAI-format payload"""
    # Authorization header format: "Bearer aws_access_key_id@aws_secret_access_key"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AWS_ACCESS_KEY_ID}@{AWS_SECRET_ACCESS_KEY}"
    }
    
    payload = {
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",  # "bedrock/" prefix will be added automatically
        "messages": messages,
        "temperature": 0.7,
        "stream": stream
    }
    
    if stream:
        response = requests.post(
            f"{API_URL}/v1/chat/completions", 
            headers=headers,
            json=payload,
            stream=True
        )
        
        for line in response.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if content:
                        print(content, end="", flush=True)
        print()
    else:
        response = requests.post(
            f"{API_URL}/v1/chat/completions", 
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            print(content)
        else:
            print(f"Error: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    # Example messages
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Tell me a short story about a robot learning to cook."}
    ]
    
    # Use stream mode if specified as command line arg
    stream_mode = "--stream" in sys.argv
    
    call_chat_api(messages, stream=stream_mode)
