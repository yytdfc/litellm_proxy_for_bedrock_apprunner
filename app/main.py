from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import litellm
import os
import json
import time
import re
from dotenv import load_dotenv
from typing import Dict, List, Any, Optional

load_dotenv()

app = FastAPI(
    title="LiteLLM Proxy for Bedrock",
    # Performance optimizations
    openapi_url=None,  # Disable OpenAPI docs in production for performance
    docs_url=None,     # Disable Swagger UI in production for performance
    redoc_url=None     # Disable ReDoc in production for performance
)

# Default AWS credentials from environment variables
default_aws_key_id = os.getenv("AWS_ACCESS_KEY_ID")
default_aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
default_aws_region = os.getenv("AWS_REGION", "us-west-2")

# Security scheme
security = HTTPBearer()

# Default model if none specified
DEFAULT_MODEL = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"

def get_aws_credentials(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Extract AWS credentials from Authorization header"""
    try:
        # Format should be "Bearer aws_access_key_id@aws_secret_access_key"
        token = credentials.credentials
        if '@' in token:
            aws_access_key_id, aws_secret_access_key = token.split('@', 1)
            return {
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key
            }
        else:
            # If no @ symbol, return default credentials
            return {
                "aws_access_key_id": default_aws_key_id,
                "aws_secret_access_key": default_aws_secret
            }
    except:
        # Return default credentials if parsing fails
        return {
            "aws_access_key_id": default_aws_key_id,
            "aws_secret_access_key": default_aws_secret
        }

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "healthy", "service": "litellm-proxy-for-bedrock"}

@app.get("/v1/models")
async def list_models():
    """List available models in OpenAI format"""
    # Just return a placeholder - actual models will be provided directly by client
    return {"object": "list", "data": []}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, credentials: dict = Depends(get_aws_credentials), response: Response = None):
    """Handle OpenAI-formatted chat completion requests"""
    try:
        body = await request.json()
        
        # Parse and prepare model name - add "bedrock/" prefix if missing
        if "model" in body:
            if not body["model"].startswith("bedrock/"):
                body["model"] = f"bedrock/{body['model']}"
        else:
            # Use default model if none provided
            body["model"] = f"bedrock/{DEFAULT_MODEL}"
        
        # Set AWS credentials for this request
        aws_config = {
            "aws_access_key_id": credentials["aws_access_key_id"],
            "aws_secret_access_key": credentials["aws_secret_access_key"],
            "aws_region_name": default_aws_region
        }

        # Handle streaming responses
        if body.get("stream", False):
            def generate_stream():
                try:
                    # Modify request for raw streaming with litellm
                    stream_options = body.copy()
                    
                    # Ensure we're getting raw stream chunks
                    if not "complete_response" in stream_options:
                        stream_options["complete_response"] = False
                    
                    # Forward request directly to LiteLLM with AWS credentials
                    response = litellm.completion(**stream_options, **aws_config)
                    
                    for chunk in response:
                        # Convert ModelResponse object to dict before JSON serialization
                        if hasattr(chunk, "model_dump"):
                            # For Pydantic v2 models
                            chunk_dict = chunk.model_dump()
                        elif hasattr(chunk, "dict"):
                            # For Pydantic v1 models
                            chunk_dict = chunk.dict()
                        else:
                            # Fallback - convert to dict directly
                            chunk_dict = {k: v for k, v in chunk.__dict__.items() if not k.startswith('_')}
                        
                        # Format as proper SSE
                        chunk_str = json.dumps(chunk_dict)
                        yield f"data: {chunk_str}\n\n"
                        
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    error_data = {"error": {"message": str(e), "type": type(e).__name__}}
                    yield f"data: {json.dumps(error_data)}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Content-Type": "text/event-stream",
                }
            )
        # Non-streaming response
        
        # Handle regular responses - forward request directly
        response = litellm.completion(**body, **aws_config)
        # Convert response to dict to ensure JSON serialization works
        if hasattr(response, "model_dump"):
            # For Pydantic v2 models
            return response.model_dump()
        elif hasattr(response, "dict"):
            # For Pydantic v1 models
            return response.dict()
        else:
            # Fallback - convert to dict directly
            return {k: v for k, v in response.__dict__.items() if not k.startswith('_')}
    
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": type(e).__name__}}
        )

if __name__ == "__main__":
    import uvicorn
    import multiprocessing

    # Calculate optimal workers based on CPU cores
    workers = multiprocessing.cpu_count() * 2 + 1
    
    # Run with optimized settings for performance
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        workers=workers,  # Multiple worker processes
        loop="uvloop",    # Faster event loop implementation
        http="httptools", # Faster HTTP protocol implementation
        limit_concurrency=1000,  # Increase concurrent connections limit
        backlog=2048      # Increase connection queue size
    )
