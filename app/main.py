# Group standard library imports
import json
import logging
import multiprocessing
import os
import random
import time
import uuid
from typing import Dict, List, Any, Optional

# Third-party imports
import boto3
import litellm
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


litellm.drop_params = True # 👈 KEY CHANGE
litellm.modify_params=True


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("litellm-proxy")

load_dotenv()

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
default_aws_key_id = os.getenv("AWS_ACCESS_KEY_ID", None)
default_aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", None)
default_aws_region = os.getenv("AWS_REGION", "us-west-2")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "0"))  # 0 means auto-calculate

# Security scheme
security = HTTPBearer()

def parse_credential_pair(cred_pair: str) -> dict:
    """Parse a single credential pair in format aws_access_key_id@aws_secret_access_key"""
    if '@' not in cred_pair:
        return None
        
    try:
        aws_access_key_id, aws_secret_access_key = cred_pair.split('@', 1)
        return {
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key
        }
    except Exception as e:
        logger.error(f"Error parsing credential pair: {str(e)}")
        return None

def get_aws_credentials(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Extract AWS credentials from Authorization header"""
    try:
        # Format: "Bearer aws_key1@aws_secret1|aws_key2@aws_secret2|..."
        token = credentials.credentials
        
        # Check if multiple credentials are provided (separated by |)
        if '|' in token:
            credential_pairs = token.split('|')
            aws_credentials_list = []
            
            for cred_pair in credential_pairs:
                parsed_creds = parse_credential_pair(cred_pair)
                if parsed_creds:
                    aws_credentials_list.append(parsed_creds)
            
            if aws_credentials_list:
                # Return list of credential pairs
                return aws_credentials_list
        
        # Single credential pair case
        elif '@' in token:
            aws_access_key_id, aws_secret_access_key = token.split('@', 1)
            return [{
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key
            }]
        
        # No valid credentials in token, use default
        return [{
            "aws_access_key_id": default_aws_key_id,
            "aws_secret_access_key": default_aws_secret
        }]
    except:
        # Return default credentials if parsing fails
        return [{
            "aws_access_key_id": default_aws_key_id,
            "aws_secret_access_key": default_aws_secret
        }]

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "healthy"}

def get_bedrock_client(credentials):
    """Create a reusable boto3 client with connection pooling"""
    return boto3.client(
        'bedrock',
        aws_access_key_id=credentials["aws_access_key_id"],
        aws_secret_access_key=credentials["aws_secret_access_key"],
        region_name=default_aws_region,
    )

@app.get("/v1/models")
async def list_models(credentials: List[dict] = Depends(get_aws_credentials)):
    """List available models in OpenAI format by querying AWS Bedrock"""
    
    # Shuffle credentials to try them in random order
    random.shuffle(credentials)
    last_exception = None
    
    # Try each credential pair until one succeeds
    for cred in credentials:
        try:
            # Log the AWS access key ID being used
            logger.info(f"Listing models using AWS access key: {cred['aws_access_key_id']}")
            
            # Create Bedrock client with current credentials
            bedrock_client = get_bedrock_client(cred)
            
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
            
            logger.info(f"Successfully listed models with AWS access key: {cred['aws_access_key_id']}")
            
            return {"object": "list", "data": models}
        except Exception as e:
            logger.error(f"Failed to list models with AWS access key: {cred['aws_access_key_id']}, error: {str(e)}")
            last_exception = e
            continue  # Try next credential pair
    
    # If we've tried all credentials and all failed
    logger.error(f"All credential attempts failed when listing models. Last error: {str(last_exception)}")
    return JSONResponse(
        status_code=500,
        content={"error": {"message": f"All credential attempts failed. Last error: {str(last_exception)}", 
                          "type": type(last_exception).__name__ if last_exception else "Unknown"}}
    )

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
async def chat_completions(request: Request, credentials_list: List[dict] = Depends(get_aws_credentials), response: Response = None):
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
            
        
        # Shuffle credentials to try them in random order
        random.shuffle(credentials_list)
        last_exception = None

        # Handle streaming responses
        if body.get("stream", False):
            async def generate_stream():
                nonlocal last_exception
                
                # Modify request for raw streaming with litellm
                stream_options = body.copy()
                
                # Ensure we're getting raw stream chunks
                if "complete_response" not in stream_options:
                    stream_options["complete_response"] = False
                
                # Try each credential pair until one succeeds
                for credentials in credentials_list:
                    try:
                        request_id = str(uuid.uuid4())
                        logger.info(f"[{request_id}] Making streaming chat completion using AWS key: {credentials['aws_access_key_id'][:5]}... for model: {body['model']}")
                        
                        # Set AWS credentials for this request
                        aws_config = {
                            "aws_access_key_id": credentials["aws_access_key_id"],
                            "aws_secret_access_key": credentials["aws_secret_access_key"],
                            "aws_region_name": default_aws_region
                        }
                        
                        # Use async context manager for better resource management
                        tool_id = ""
                        start_time = time.time()
                        
                        # Forward request directly to LiteLLM with AWS credentials
                        response = await litellm.acompletion(**stream_options, **aws_config)
                        
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
                        logger.error(f"Streaming failed with AWS key: {credentials['aws_access_key_id'][:5]}..., error: {str(e)}")
                        last_exception = e
                        continue  # Try next credential
                
                # If all credentials failed
                error_data = {"error": {"message": f"All credential attempts failed. Last error: {str(last_exception)}", 
                                        "type": type(last_exception).__name__ if last_exception else "Unknown"}}
                yield f"data: {json.dumps(error_data)}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
            )
        
        # Non-streaming response - try each credential until one works
        for credentials in credentials_list:
            try:
                request_id = str(uuid.uuid4())
                logger.info(f"[{request_id}] Making chat completion using AWS key: {credentials['aws_access_key_id'][:5]}... for model: {body['model']}")
                
                # Set AWS credentials for this request
                aws_config = {
                    "aws_access_key_id": credentials["aws_access_key_id"],
                    "aws_secret_access_key": credentials["aws_secret_access_key"],
                    "aws_region_name": default_aws_region
                }
                
                start_time = time.time()
                
                # Handle regular responses - forward request directly
                response = await litellm.acompletion(**body, **aws_config)
                
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
                logger.error(f"Failed chat completion with AWS key: {credentials['aws_access_key_id'][:5]}..., error: {str(e)}")
                last_exception = e
                continue  # Try next credential
        
        # If all credentials failed
        return JSONResponse(
            status_code=500,
            content={"error": {"message": f"All credential attempts failed. Last error: {str(last_exception)}", 
                              "type": type(last_exception).__name__ if last_exception else "Unknown"}}
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
