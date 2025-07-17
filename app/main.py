# Group standard library imports
import json
import logging
import multiprocessing
import os
import time
import uuid
from typing import Dict, List, Any, Optional

# Third-party imports
import boto3
import litellm
from fastapi import FastAPI, Request, Response, Depends, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader


litellm.drop_params = True # 👈 KEY CHANGE
litellm.modify_params=True


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("litellm-proxy")

app = FastAPI(
    title="LiteLLM Proxy for Bedrock",
    # Performance optimizations
    openapi_url=None,  # Disable OpenAPI docs in production for performance
    docs_url=None,     # Disable Swagger UI in production for performance
    redoc_url=None     # Disable ReDoc in production for performance
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Configuration from environment variables
default_aws_region = os.getenv("AWS_REGION", "us-west-2")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "0"))  # 0 means auto-calculate
API_KEY = os.getenv("API_KEY", None)  # API key for authentication

# Security scheme
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify the API key from the Authorization header"""
    if not API_KEY:
        logger.warning("API_KEY environment variable not set")
        raise HTTPException(status_code=500, detail="API key not configured on server")
    
    if not api_key:
        raise HTTPException(status_code=401, detail="API key is required")
    
    # Remove 'Bearer ' prefix if present
    if api_key.startswith("Bearer "):
        api_key = api_key[7:]
    
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return True


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "healthy"}


def get_bedrock_client():
    """Create a reusable boto3 client with connection pooling"""
    return boto3.client(
        'bedrock',
        region_name=default_aws_region,
    )


@app.get("/v1/models")
async def list_models(authenticated: bool = Depends(verify_api_key)):
    """List available models in OpenAI format by querying AWS Bedrock"""
    
    try:
        bedrock_client = get_bedrock_client()
        
        # Call AWS Bedrock API to list foundation models
        response = bedrock_client.list_foundation_models()
        
        # Format response in OpenAI compatible format
        response = bedrock_client.list_inference_profiles()
        
        models = []
        # Format response in OpenAI compatible format
        for model in response.get("inferenceProfileSummaries", []):
            models.append({
                "id": model.get("inferenceProfileId"),
                "object": "model",
                "owned_by": model.get("inferenceProfileId").split(".")[1]
            })
        
        logger.info(f"Successfully listed models")
        
        return {"object": "list", "data": models}
    except Exception as e:
        logger.error(f"Failed to list models, error: {str(e)}")

    

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    logger.info(f"Request {request_id} started: {request.method} {request.url.path}")
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(f"Request {request_id} completed in {process_time:.3f}s")
    response.headers["X-Request-ID"] = request_id
    
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception handler caught: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": {"message": str(exc), "type": type(exc).__name__}}
    )


def process_tool_calls(messages):
    """Extract tool handling to a separate function"""
    tool_id = None
    for i, msg in enumerate(messages):
        if msg["role"] == "assistant" and "tool_calls" in msg:
            if not msg["tool_calls"][0].get("id"):
                msg["tool_calls"][0]["id"] = uuid.uuid4().hex
            tool_id = msg["tool_calls"][0]["id"]
        elif msg["role"] == "tool" and tool_id:
            msg["tool_call_id"] = tool_id
    return messages


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authenticated: bool = Depends(verify_api_key), response: Response = None):
    """Handle OpenAI-formatted chat completion requests"""
    try:
        body = await request.json()
        
        # Process tool calls in messages
        if "messages" in body:
            body["messages"] = process_tool_calls(body["messages"])
        
        # Parse and prepare model name - add "bedrock/" prefix if missing
        if "model" in body:
            if not body["model"].startswith("bedrock/"):
                body["model"] = f"bedrock/converse/{body['model']}"
        else:
            # raise ValueError("No model specified in request")
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "No model specified in request", "type": "ValueError"}}
            )

        if "aws_region_name" not in body:
            body["aws_region_name"] = default_aws_region
            
        # Handle streaming responses
        if body.get("stream", False):
            async def generate_stream():
                
                # Modify request for raw streaming with litellm
                stream_options = body.copy()
                
                # Ensure we're getting raw stream chunks
                if "complete_response" not in stream_options:
                    stream_options["complete_response"] = False
                
                try:
                    request_id = str(uuid.uuid4())
                    
                    # Use async context manager for better resource management
                    tool_id = ""
                    start_time = time.time()
                    
                    # Forward request directly to LiteLLM with AWS config
                    response = await litellm.acompletion(**stream_options)
                    
                    async for chunk in response:
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
                        
                        # Handle tool calls consistently
                        try:
                            if chunk_dict.get("choices", [{}])[0].get("delta", {}).get("tool_calls"):
                                if not tool_id:
                                    tool_id = chunk_dict["choices"][0]["delta"]["tool_calls"][0].get("id", uuid.uuid4().hex)
                                chunk_dict["choices"][0]["delta"]["tool_calls"][0]["id"] = tool_id
                        except (KeyError, IndexError):
                            pass
                            
                        # Format as proper SSE
                        chunk_str = json.dumps(chunk_dict)
                        yield f"data: {chunk_str}\n\n"
                    
                    # Log successful completion
                    process_time = time.time() - start_time
                    logger.info(f"[{request_id}] Successfully streamed response in {process_time:.3f}s")
                    
                    yield "data: [DONE]\n\n"
                    return  # Successfully streamed response
                except Exception as e:
                    logger.error(f"Streaming failed error: {str(e)}")
                
                    error_data = {"error": {"message": str(e), 
                                            "type": type(e).__name__ if e else "Unknown"}}
                    yield f"data: {json.dumps(error_data)}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
            )
        
        else:
            try:
                request_id = str(uuid.uuid4())
                
                
                start_time = time.time()
                
                # Handle regular responses - forward request directly
                response = await litellm.acompletion(**body)
                
                # Log successful completion with timing
                process_time = time.time() - start_time
                logger.info(f"[{request_id}] Successfully completed chat request in {process_time:.3f}s")
                
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
                logger.error(f"Failed chat completion error: {str(e)}")
            
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": str(e), 
                                    "type": type(e).__name__ if e else "Unknown"}}
                )
    
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": type(e).__name__}}
        )


def calculate_workers():
    """Calculate optimal number of workers based on environment or CPU count"""
    if MAX_WORKERS > 0:
        return MAX_WORKERS
    
    cpu_count = multiprocessing.cpu_count()
    # For I/O-bound tasks (like API calls): cpu_count * 2 + 1
    return cpu_count * 2 + 1


if __name__ == "__main__":
    import uvicorn
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="LiteLLM Proxy for Bedrock")
    parser.add_argument("--port", type=int, default=8080, help="Port to run the server on (default: 8080)")
    args = parser.parse_args()

    # Calculate optimal workers
    workers = calculate_workers()
    print(f"Starting server with {workers} workers on port {args.port}")
    
    # Run with optimized settings for performance
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=int(os.environ.get("PORT", args.port)),
        workers=workers,  # Multiple worker processes
        loop="uvloop",    # Faster event loop implementation
        http="httptools", # Faster HTTP protocol implementation
        limit_concurrency=1024,  # Increase concurrent connections limit
        backlog=2048      # Increase connection queue size
    )
