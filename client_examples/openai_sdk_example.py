#!/usr/bin/env python3
"""
Example of using the OpenAI SDK to interact with the LiteLLM Proxy for Bedrock

Prerequisites:
- pip install openai python-dotenv
"""

import os
import sys
import json
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get configuration from environment variables
API_BASE = os.getenv("API_BASE")
API_KEY= os.getenv("API_KEY", "")

# If API_TOKEN is not set directly, construct it from AWS credentials
if not API_KEY:
    AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    if AWS_ACCESS_KEY and AWS_SECRET_KEY:
        API_TOKEN = f"{AWS_ACCESS_KEY}@{AWS_SECRET_KEY}"

# Initialize the OpenAI client with the custom API base
client = OpenAI(
    api_key=API_KEY,  # The AWS credentials are passed as the API key
    base_url=API_BASE,  # The base URL from CloudFormation output
)

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
        response = client.chat.completions.create(**payload)
        
        print(f"Response: {response.choices[0].message.content}")
        if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
            print("\nTool Calls:")
            for tool_call in response.choices[0].message.tool_calls:
                print(f"Function: {tool_call.function.name}")
                print(f"Arguments: {tool_call.function.arguments}")
        print(f"Model: {response.model}")
        print(f"Usage: {response.usage}")
        
    except Exception as e:
        print(f"Error: {e}")

def streaming_chat_completion_example():
    """Example of a streaming chat completion request"""
    print("\nStreaming Chat Completion Example:")
    
    # Load payload from JSON file
    payload = load_payload()
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}

    
    try:
        stream = client.chat.completions.create(**payload)
        
        print("Response: ", end="", flush=True)
        current_tool_call = {"name": "", "arguments": ""}
        
        for chunk in stream:
            if chunk.choices[0].delta.content:
                print(chunk.choices[0].delta.content, end="", flush=True)
            
            if hasattr(chunk.choices[0].delta, 'tool_calls') and chunk.choices[0].delta.tool_calls:
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if hasattr(tool_call.function, 'name') and tool_call.function.name:
                        if not current_tool_call["name"]:
                            print("\n\nTool Calls:\nFunction: ", end="", flush=True)
                        print(tool_call.function.name, end="", flush=True)
                        current_tool_call["name"] += tool_call.function.name
                    if hasattr(tool_call.function, 'arguments') and tool_call.function.arguments:
                        if not current_tool_call["arguments"]:
                            print("\nArguments: ", end="", flush=True)
                        print(tool_call.function.arguments, end="", flush=True)
                        current_tool_call["arguments"] += tool_call.function.arguments

            if hasattr(chunk, 'usage') and chunk.usage:
                print(f"\n\nUsage: {chunk.usage}")
        print()
        
    except Exception as e:
        print(f"Error: {e}")

def list_models_example():
    """Example of listing available models"""
    print("\nList Models Example:")
    
    try:
        models = client.models.list()
        print("Available models:")
        for model in models.data[:5]:
            print(f"- {model.id} (Provider: {model.owned_by})")
        print(f"...")
        print(f"Total models: {len(models.data)}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_models_example()
    print("="*50)
    chat_completion_example()
    print("="*50)
    streaming_chat_completion_example()
