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

def get_auth_headers():
    """Get authorization headers with AWS credentials"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AWS_ACCESS_KEY_ID}@{AWS_SECRET_ACCESS_KEY}"
    }

def list_models():
    """Call the models API to get available models"""
    headers = get_auth_headers()
    
    response = requests.get(
        f"{API_URL}/v1/models", 
        headers=headers
    )
    
    if response.status_code == 200:
        result = response.json()
        print("Available models:")
        for model in result["data"]:
            print(f"- {model['id']} (Provider: {model['owned_by']})")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)

def call_chat_api(messages, stream=False, model=None):
    """Call the proxy API with OpenAI-format payload"""
    headers = get_auth_headers()
    
    # Use the specified model or default to Claude 3.7 Sonnet
    if model is None:
        model = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
    
    payload = {
        "model": model,  # "bedrock/" prefix will be added automatically
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
    if "--list-models" in sys.argv:
        list_models()
        sys.exit(0)
    
    # Example messages
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Tell me a short story about a robot learning to cook."}
    ]
    
    # Use stream mode if specified as command line arg
    stream_mode = "--stream" in sys.argv
    
    # Get model from command line if specified (--model=modelId)
    model = None
    for arg in sys.argv:
        if arg.startswith("--model="):
            model = arg.split("=", 1)[1]
            break
    
    call_chat_api(messages, stream=stream_mode, model=model)
