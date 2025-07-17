#!/usr/bin/env python3
"""
Example of using httpx to interact with the LiteLLM Proxy for Bedrock

Prerequisites:
- pip install httpx python-dotenv
"""

import os
import json
import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get configuration from environment variables
API_BASE = os.getenv("API_BASE")
API_KEY = os.getenv("API_KEY", "")

# Headers for API requests
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

def load_payload():
    """Load payload from JSON file"""
    try:
        with open('openai_payload.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading payload.json: {e}")
        return None

def chat_completion_example():
    """Example of a chat completion request"""
    print("Chat Completion Example:")
    
    # Load payload from JSON file
    payload = load_payload()
    
    try:
        # Make the API request
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{API_BASE}/chat/completions",
                headers=headers,
                json=payload
            )
            
            # Check if the request was successful
            response.raise_for_status()
            data = response.json()
            
            # Print the response
            print(f"Response: {data['choices'][0]['message']['content']}")
            
            # Check for tool calls
            if 'tool_calls' in data['choices'][0]['message'] and data['choices'][0]['message']['tool_calls']:
                print("\nTool Calls:")
                for tool_call in data['choices'][0]['message']['tool_calls']:
                    print(f"Function: {tool_call['function']['name']}")
                    print(f"Arguments: {tool_call['function']['arguments']}")
            
            print(f"Model: {data['model']}")
            print(f"Usage: {data['usage']}")
            
    except Exception as e:
        print(f"Error: {e}")

def streaming_chat_completion_example():
    """Example of a streaming chat completion request"""
    print("\nStreaming Chat Completion Example:")
    
    # Load payload from JSON file
    payload = load_payload()
    payload["stream"] = True
    
    try:
        # Make the API request with streaming
        with httpx.Client(timeout=60.0) as client:
            with client.stream(
                "POST",
                f"{API_BASE}/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                # Check if the request was successful
                response.raise_for_status()
                
                print("Response: ", end="", flush=True)
                current_tool_call = {"name": "", "arguments": ""}
                buffer = ""
                
                # Manually parse the SSE stream
                for line in response.iter_lines():
                    # Skip empty lines
                    if not line:
                        continue
                    
                    # Skip comments
                    if line.startswith(':'):
                        continue
                    
                    # Handle data lines
                    if line.startswith('data: '):
                        data = line[6:]  # Remove 'data: ' prefix
                        
                        # Check for end of stream
                        if data == "[DONE]":
                            break
                        
                        try:
                            # Parse the JSON chunk
                            chunk = json.loads(data)
                            
                            # Handle content
                            if chunk['choices'][0]['delta'].get('content'):
                                print(chunk['choices'][0]['delta']['content'], end="", flush=True)
                            
                            # Handle tool calls
                            if 'tool_calls' in chunk['choices'][0]['delta'] and chunk['choices'][0]['delta']['tool_calls']:
                                for tool_call in chunk['choices'][0]['delta']['tool_calls']:
                                    if 'function' in tool_call:
                                        if tool_call['function'].get('name'):
                                            if not current_tool_call["name"]:
                                                print("\n\nTool Calls:\nFunction: ", end="", flush=True)
                                            print(tool_call['function']['name'], end="", flush=True)
                                            current_tool_call["name"] += tool_call['function']['name']
                                        
                                        if tool_call['function'].get('arguments'):
                                            if not current_tool_call["arguments"]:
                                                print("\nArguments: ", end="", flush=True)
                                            print(tool_call['function']['arguments'], end="", flush=True)
                                            current_tool_call["arguments"] += tool_call['function']['arguments']
                            
                            # Handle usage info
                            if 'usage' in chunk:
                                print(f"\n\nUsage: {chunk['usage']}")
                        
                        except json.JSONDecodeError:
                            print(f"Error parsing JSON: {data}")
                
                print()
                
    except Exception as e:
        print(f"Error: {e}")

def list_models_example():
    """Example of listing available models"""
    print("\nList Models Example:")
    
    try:
        # Make the API request
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{API_BASE}/models",
                headers=headers
            )
            
            # Check if the request was successful
            response.raise_for_status()
            data = response.json()
            
            # Print the models
            print("Available models:")
            for model in data['data'][:5]:
                print(f"- {model['id']} (Provider: {model['owned_by']})")
            print(f"...")
            print(f"Total models: {len(data['data'])}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_models_example()
    print("="*50)
    chat_completion_example()
    print("="*50)
    streaming_chat_completion_example()
