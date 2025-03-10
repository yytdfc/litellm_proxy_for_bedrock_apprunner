from fastapi.testclient import TestClient
import pytest
import os
import json
from dotenv import load_dotenv
from app.main import app

load_dotenv()

client = TestClient(app)

# Mock AWS credentials for tests
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test_access_key")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test_secret_key")

# Test headers with authentication
auth_headers = {
    "Authorization": f"Bearer {AWS_ACCESS_KEY_ID}@{AWS_SECRET_ACCESS_KEY}"
}

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "litellm-proxy-for-bedrock"}

def test_models():
    # Models endpoint doesn't require auth
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert "data" in response.json()
    assert len(response.json()["data"]) > 0

def test_chat_completion_requires_auth():
    # Without auth header
    response = client.post("/v1/chat/completions", 
                           json={"model": "gpt-3.5-turbo",
                                "messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 401  # Unauthorized

def test_chat_completion_validation():
    # With auth header but invalid model
    response = client.post("/v1/chat/completions", 
                           headers=auth_headers,
                           json={"model": "invalid-model",
                                "messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 400

def test_auth_header_parsing():
    # Test with valid auth header format
    valid_headers = {
        "Authorization": "Bearer testkey@testsecret"
    }
    response = client.post("/v1/chat/completions", 
                          headers=valid_headers,
                          json={"model": "gpt-3.5-turbo", 
                               "messages": [{"role": "user", "content": "Hello"}]})
    # Should be 500 as the credentials are invalid for actual AWS
    # But we're just testing the auth parsing here
    assert response.status_code in [500, 200]