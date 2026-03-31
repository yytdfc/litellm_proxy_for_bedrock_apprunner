# Group standard library imports
import hashlib
import json
import logging
import multiprocessing
import os
import random
import time
import uuid
from typing import List, Optional

# Third-party imports
import boto3
import litellm
import redis
from anthropic import AsyncAnthropicBedrock
from fastapi import FastAPI, Request, Depends, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader


litellm.drop_params = True # 👈 KEY CHANGE
litellm.modify_params=True

# Cross-region load balancing config
CROSS_REGION_POOLS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1",
    "ap-northeast-1", "ap-northeast-2", "ap-south-1",
    "ap-southeast-1", "ap-southeast-2", "sa-east-1"
]
CROSS_REGION_TTL = 3600  # 1 hour
REGION_BLACKLIST_TTL = 300  # 5 minutes

# Redis client for cross-region cache
_redis = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)


def _strip_cache_control(obj):
    """Recursively remove cache_control fields for hash computation"""
    if isinstance(obj, dict):
        return {k: _strip_cache_control(v) for k, v in obj.items() if k != "cache_control"}
    elif isinstance(obj, list):
        return [_strip_cache_control(i) for i in obj]
    return obj


def _compute_request_hash(body: dict) -> str:
    """Compute hash from tools + system + first 3 messages (without cache fields)"""
    parts = []
    if "tools" in body:
        parts.append(json.dumps(_strip_cache_control(body["tools"]), sort_keys=True))
    if "system" in body:
        parts.append(json.dumps(_strip_cache_control(body["system"]), sort_keys=True))
    if "messages" in body:
        parts.append(json.dumps(_strip_cache_control(body["messages"][:3]), sort_keys=True))
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _is_region_blacklisted(region: str) -> bool:
    return _redis.exists(f"blacklist:{region}") > 0


def _blacklist_region(region: str):
    _redis.setex(f"blacklist:{region}", REGION_BLACKLIST_TTL, "1")
    logger.warning(f"Region {region} blacklisted for {REGION_BLACKLIST_TTL}s")


def _get_cross_region(body: dict) -> str:
    """Get region for cross-region load balancing with Redis TTL cache"""
    h = f"cross:{_compute_request_hash(body)}"
    
    # Check cache, refresh TTL if hit and region is healthy
    if region := _redis.get(h):
        if not _is_region_blacklisted(region):
            _redis.expire(h, CROSS_REGION_TTL)
            return region
        # Cached region is blacklisted, clear and re-select
        _redis.delete(h)
    
    # Select region based on hash, skip blacklisted
    hash_int = int(h.split(":")[1], 16)
    for i in range(len(CROSS_REGION_POOLS)):
        candidate = CROSS_REGION_POOLS[(hash_int + i) % len(CROSS_REGION_POOLS)]
        if not _is_region_blacklisted(candidate):
            _redis.setex(h, CROSS_REGION_TTL, candidate)
            return candidate
    
    # All blacklisted, fallback to hash-based pick
    region = CROSS_REGION_POOLS[hash_int % len(CROSS_REGION_POOLS)]
    _redis.setex(h, CROSS_REGION_TTL, region)
    return region


# Model ID mapping: Claude API ID / alias -> AWS Bedrock ID
MODEL_ID_MAPPING = {
    # Claude Sonnet 4.5
    "claude-sonnet-4-5-20250929": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    # Claude Haiku 4.5
    "claude-haiku-4-5-20251001": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    # Claude Opus 4.5
    "claude-opus-4-5-20251101": "global.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-5": "global.anthropic.claude-opus-4-5-20251101-v1:0",
    # Claude Opus 4.6
    "claude-opus-4-6": "global.anthropic.claude-opus-4-6-v1",
    "claude-opus-4-6[1m]": "global.anthropic.claude-opus-4-6-v1",
    # Claude Sonnet 4.6
    "claude-sonnet-4-6": "global.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-6[1m]": "global.anthropic.claude-sonnet-4-6",
}

def convert_model_id(model_id: str) -> str:
    """Convert Claude API model ID to AWS Bedrock model ID if mapping exists"""
    return MODEL_ID_MAPPING.get(model_id, model_id)


# Configuration from environment variables
default_aws_region = os.getenv("AWS_REGION", "us-west-2")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "0"))
API_KEY = os.getenv("API_KEY", None)

# Set up logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
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

# Security schemes
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)
x_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

# Cache for AsyncAnthropicBedrock clients per region
_anthropic_clients: dict[str, AsyncAnthropicBedrock] = {}

def get_anthropic_client(aws_region: str) -> AsyncAnthropicBedrock:
    if aws_region not in _anthropic_clients:
        _anthropic_clients[aws_region] = AsyncAnthropicBedrock(
            aws_region=aws_region,
            timeout=3600.0,
            max_retries=0,
        )
    return _anthropic_clients[aws_region]


async def verify_api_key_dual(
    auth_header: str = Security(api_key_header),
    x_api_key: str = Security(x_api_key_header)
):
    """Verify API key from either Authorization header (Bearer token) or x-api-key header"""
    if not API_KEY:
        logger.warning("API_KEY environment variable not set")
        raise HTTPException(status_code=500, detail="API key not configured on server")
    
    # Try x-api-key first
    if x_api_key:
        if x_api_key == API_KEY:
            return True
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    # Then try Authorization header
    if auth_header:
        api_key = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
        if api_key == API_KEY:
            return True
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    raise HTTPException(status_code=401, detail="API key is required")


@app.get("/")
async def root():
    return {"status": "healthy"}


def add_cache_control_to_messages(messages: List[dict]) -> List[dict]:
    """Add ephemeral cache control to the last message only for prompt caching"""
    if not messages:
        return messages
    
    # Copy all messages first
    cached_messages = [message.copy() for message in messages]
    
    # Only add cache control to the last message
    last_message = cached_messages[-1]
    
    # Add cache control to content if it's a string
    if isinstance(last_message.get("content"), str):
        last_message["cache_control"] = {"type": "ephemeral"}
    
    # Add cache control to content if it's a list of content items
    elif isinstance(last_message.get("content"), list):
        cached_content = []
        for content_item in last_message["content"]:
            if isinstance(content_item, dict):
                cached_content_item = content_item.copy()
                cached_content_item["cache_control"] = {"type": "ephemeral"}
                cached_content.append(cached_content_item)
            else:
                cached_content.append(content_item)
        last_message["content"] = cached_content
    
    # Add cache control to tool_calls if present
    if "tool_calls" in last_message and isinstance(last_message["tool_calls"], list):
        cached_tool_calls = []
        for tool_call in last_message["tool_calls"]:
            if isinstance(tool_call, dict):
                cached_tool_call = tool_call.copy()
                cached_tool_call["cache_control"] = {"type": "ephemeral"}
                cached_tool_calls.append(cached_tool_call)
            else:
                cached_tool_calls.append(tool_call)
        last_message["tool_calls"] = cached_tool_calls
    
    return cached_messages


@app.get("/v1/models")
async def list_models(authenticated: bool = Depends(verify_api_key_dual)):
    """List available models in OpenAI format by querying AWS Bedrock"""
    return await list_models_with_region(None, authenticated)

@app.get("/{region}/v1/models")
async def list_models_with_region(region: Optional[str], authenticated: bool = Depends(verify_api_key_dual)):
    """List available models in OpenAI format by querying AWS Bedrock with optional region"""
    return await list_models_handler(region, authenticated)

@app.get("/{region}/epc/v1/models")
async def list_models_with_epc(region: Optional[str], authenticated: bool = Depends(verify_api_key_dual)):
    """List available models in OpenAI format by querying AWS Bedrock with EPC support"""
    return await list_models_handler(region, authenticated)

async def list_models_handler(region: Optional[str], authenticated: bool):
    """Handle model listing requests with optional region"""
    
    try:
        # Use provided region or fall back to default
        aws_region = region if region else default_aws_region
        
        bedrock_client = boto3.client(
            'bedrock',
            region_name=aws_region,
        )
        
        models = []

        # Format response in OpenAI compatible format
        response = bedrock_client.list_inference_profiles()
        
        # Format response in OpenAI compatible format
        for model in response.get("inferenceProfileSummaries", []):
            models.append({
                "id": model.get("inferenceProfileId"),
                "object": "model",
                "owned_by": model.get("inferenceProfileId").split(".")[1]
            })

        # Call AWS Bedrock API to list foundation models
        response = bedrock_client.list_foundation_models()

        # Format response in OpenAI compatible format
        for model in response.get("modelSummaries", []):
            if "TEXT" in model.get("outputModalities", ["TEXT"]):
                models.append({
                    "id": model.get("modelId"),
                    "object": "model",
                    "owned_by": model.get("providerName")
                })

        logger.info(f"Successfully listed models for region: {aws_region}")
        
        return {"object": "list", "data": models}
    except Exception as e:
        logger.error(f"Failed to list models for region {aws_region if 'aws_region' in locals() else 'unknown'}, error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": type(e).__name__}}
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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await chat_completions_with_region(None, request, authenticated)

@app.post("/cross/v1/chat/completions")
async def chat_completions_cross(request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    body = await request.json()
    model = convert_model_id(body.get("model", ""))
    if not model.startswith("global."):
        return await chat_completions_handler(default_aws_region, False, request, authenticated, body)
    region = _get_cross_region(body)
    logger.info(f"Cross-region routing to: {region}")
    try:
        return await chat_completions_handler(region, False, request, authenticated, body)
    except Exception as e:
        logger.error(f"Cross-region {region} failed: {e}, retrying with fallback")
        _blacklist_region(region)
        fallback = _get_cross_region(body)
        logger.info(f"Cross-region fallback to: {fallback}")
        return await chat_completions_handler(fallback, False, request, authenticated, body)

@app.post("/{region}/v1/chat/completions")
async def chat_completions_with_region(region: Optional[str], request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await chat_completions_handler(region, False, request, authenticated)

@app.post("/{region}/epc/v1/chat/completions")
async def chat_completions_with_epc(region: Optional[str], request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await chat_completions_handler(region, True, request, authenticated)

async def chat_completions_handler(region: Optional[str], enable_cache: bool, request: Request, authenticated: bool, body: dict = None):
    try:
        if body is None:
            body = await request.json()
        
        # Parse and prepare model name - convert Claude API ID to Bedrock ID, then add prefix
        if "model" in body:
            body["model"] = convert_model_id(body["model"])
            if not body["model"].startswith("bedrock/"):
                body["model"] = f"bedrock/converse/{body['model']}"
        else:
            # raise ValueError("No model specified in request")
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "No model specified in request", "type": "ValueError"}}
            )

        # Set AWS region from URL path or use default
        if region:
            body["aws_region_name"] = region
        elif "aws_region_name" not in body:
            body["aws_region_name"] = default_aws_region
        
        # Add ephemeral prompt cache if EPC endpoint is used
        if enable_cache and "messages" in body:
            body["messages"] = add_cache_control_to_messages(body["messages"])
            logger.info("Added ephemeral cache control to messages")
        
        # For Anthropic models, remove top_p if both temperature and top_p are present
        if "model" in body and "anthropic" in body["model"].lower():
            if "temperature" in body and "top_p" in body:
                logger.info(f"Removing top_p parameter for Anthropic model (keeping temperature)")
                body.pop("top_p")
            
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


@app.post("/v1/embeddings")
async def embeddings(request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await embeddings_handler(None, request, authenticated)

@app.post("/cross/v1/embeddings")
async def embeddings_cross(request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    body = await request.json()
    model = body.get("model", "")
    if not model.startswith("global."):
        return await embeddings_handler(default_aws_region, request, authenticated, body)
    region = _get_cross_region(body)
    logger.info(f"Cross-region embedding routing to: {region}")
    try:
        return await embeddings_handler(region, request, authenticated, body)
    except Exception as e:
        logger.error(f"Cross-region embedding {region} failed: {e}, retrying with fallback")
        _blacklist_region(region)
        fallback = _get_cross_region(body)
        logger.info(f"Cross-region embedding fallback to: {fallback}")
        return await embeddings_handler(fallback, request, authenticated, body)

@app.post("/{region}/v1/embeddings")
async def embeddings_with_region(region: Optional[str], request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await embeddings_handler(region, request, authenticated)

async def embeddings_handler(region: Optional[str], request: Request, authenticated: bool, body: dict = None):
    try:
        if body is None:
            body = await request.json()
        model = body.pop("model", None)
        if not model:
            return JSONResponse(status_code=400, content={"error": {"message": "No model specified", "type": "ValueError"}})
        if not model.startswith("bedrock/"):
            model = f"bedrock/{model}"
        body["aws_region_name"] = region or body.get("aws_region_name", default_aws_region)
        response = await litellm.aembedding(model=model, **body)
        if hasattr(response, "model_dump"):
            return response.model_dump()
        return response.dict()
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return JSONResponse(status_code=500, content={"error": {"message": str(e), "type": type(e).__name__}})


@app.post("/v1/messages")
async def messages(request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await messages_with_region(None, request, authenticated)

@app.post("/cross/v1/messages")
async def messages_cross(request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    body = await request.json()
    model = convert_model_id(body.get("model", ""))
    if not model.startswith("global."):
        return await messages_handler(default_aws_region, False, request, authenticated, body)
    region = _get_cross_region(body)
    logger.info(f"Cross-region routing to: {region}")
    try:
        return await messages_handler(region, False, request, authenticated, body)
    except Exception as e:
        logger.error(f"Cross-region {region} failed: {e}, retrying with fallback")
        _blacklist_region(region)
        fallback = _get_cross_region(body)
        logger.info(f"Cross-region fallback to: {fallback}")
        return await messages_handler(fallback, False, request, authenticated, body)

@app.post("/{region}/v1/messages")
async def messages_with_region(region: Optional[str], request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await messages_handler(region, False, request, authenticated)

@app.post("/{region}/epc/v1/messages")
async def messages_with_epc(region: Optional[str], request: Request, authenticated: bool = Depends(verify_api_key_dual)):
    return await messages_handler(region, True, request, authenticated)

async def messages_handler(region: Optional[str], enable_cache: bool, request: Request, authenticated: bool, body: dict = None):
    try:
        if body is None:
            body = await request.json()
        
        if "model" not in body:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "No model specified in request", "type": "ValueError"}}
            )

        # Convert Claude API ID to Bedrock ID
        body["model"] = convert_model_id(body["model"])
        model_id = body["model"]
        aws_region = region if region else body.get("aws_region_name", default_aws_region)
        
        # Add ephemeral prompt cache if EPC endpoint is used
        if enable_cache and "messages" in body:
            body["messages"] = add_cache_control_to_messages(body["messages"])
            logger.info("Added ephemeral cache control to messages")

        # For Claude models, use native Bedrock invoke API
        if "claude" in model_id.lower():
            return await _handle_claude_native(model_id, aws_region, body)
        
        # For non-Claude models, use LiteLLM
        if not model_id.startswith("bedrock/"):
            body["model"] = f"bedrock/{model_id}"
        body["aws_region_name"] = aws_region

        if body.get("stream", False):
            async def generate_stream():
                stream_options = body.copy()
                if "complete_response" not in stream_options:
                    stream_options["complete_response"] = False
                
                try:
                    request_id = str(uuid.uuid4())
                    start_time = time.time()
                    response = await litellm.anthropic.messages.acreate(**{"no-log": True}, **stream_options)
                    
                    async for chunk in response:
                        yield chunk
                    
                    process_time = time.time() - start_time
                    logger.info(f"[{request_id}] Successfully streamed messages response in {process_time:.3f}s")
                except Exception as e:
                    logger.error(f"Messages streaming failed error: {str(e)}")
                    error_data = {"error": {"message": str(e), "type": type(e).__name__ if e else "Unknown"}}
                    yield f"data: {json.dumps(error_data)}\n\n"
            
            return StreamingResponse(generate_stream(), media_type="text/event-stream")
        else:
            try:
                request_id = str(uuid.uuid4())
                start_time = time.time()
                response = await litellm.anthropic.messages.acreate(**{"no-log": True}, **body)
                process_time = time.time() - start_time
                logger.info(f"[{request_id}] Successfully completed messages request in {process_time:.3f}s")
                return response
            except Exception as e:
                logger.error(f"Messages request failed error: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": str(e), "type": type(e).__name__ if e else "Unknown"}}
                )
    
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": type(e).__name__}}
        )


def remove_cache_control_ttl(obj):
    """Recursively remove ttl from cache_control in nested structures"""
    if isinstance(obj, dict):
        if "cache_control" in obj and isinstance(obj["cache_control"], dict):
            obj["cache_control"].pop("ttl", None)
        for value in obj.values():
            remove_cache_control_ttl(value)
    elif isinstance(obj, list):
        for item in obj:
            remove_cache_control_ttl(item)


async def _handle_claude_native(model_id: str, aws_region: str, body: dict):
    """Handle Claude models using AsyncAnthropicBedrock"""
    request_id = str(uuid.uuid4())

    is_stream = body.pop("stream", False)
    
    remove_cache_control_ttl(body)
    
    # Strip fields not accepted by Bedrock InvokeModel
    for key in ["callOptions", "output_config", "headers"]:
        body.pop(key, None)
    for msg in body.get("messages", []):
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    block.pop("caller", None)
    
    # Convert output_format -> output_config.format (Bedrock rejects output_format)
    if "output_format" in body:
        of = body.pop("output_format")
        if "output_config" not in body:
            schema = of.get("json_schema", {}).get("schema", of.get("schema", {}))
            body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    
    # Auto-inject eager_input_streaming on 4.6 tools for faster tool permission prompts
    tools = body.get("tools", [])
    is_46 = "opus-4-6" in model_id or "opus-4.6" in model_id or "sonnet-4-6" in model_id or "sonnet-4.6" in model_id
    if is_46:
        for t in tools:
            if "input_schema" in t and "eager_input_streaming" not in t:
                t["eager_input_streaming"] = True
    
    # Text editor tool: Bedrock requires name='str_replace_based_edit_tool'
    for t in tools:
        if t.get("type", "").startswith("text_editor_") and t.get("name") == "text_editor":
            t["name"] = "str_replace_based_edit_tool"
    
    # Auto-detect beta headers from payload
    betas = set()
    if is_46:
        betas.add("context-1m-2025-08-07")
    tool_types = {t.get("type", "") for t in tools}
    if any(tt.startswith("tool_search") for tt in tool_types):
        betas.add("tool-search-tool-2025-10-19")
    if any("input_examples" in t for t in tools):
        betas.add("tool-examples-2025-10-29")
    if any(tt.startswith(("computer_", "bash_", "text_editor_")) for tt in tool_types):
        betas.add("computer-use-2025-01-24")
    
    # Use beta API when context_management is present
    use_beta = "context_management" in body
    if use_beta:
        betas.add("context-management-2025-06-27")
    
    extra_headers = {}
    if betas:
        extra_headers["anthropic-beta"] = ",".join(betas)
    
    client = get_anthropic_client(aws_region)
    api = client.beta.messages if use_beta else client.messages
    start_time = time.time()

    logger.info(f"[{request_id}] claude_native model={model_id} region={aws_region} stream={is_stream} beta={use_beta}")

    if is_stream:
        async def generate_stream():
            try:
                stream = await api.create(stream=True, extra_headers=extra_headers, **body)
                async for event in stream:
                    yield f"event: {event.type}\ndata: {json.dumps(event.model_dump() if hasattr(event, 'model_dump') else event.dict())}\n\n"
                
                process_time = time.time() - start_time
                logger.info(f"[{request_id}] Successfully streamed Claude native response in {process_time:.3f}s")
            except Exception as e:
                logger.error(f"Claude native streaming failed: {str(e)}")
                error_data = {"type": "error", "error": {"message": str(e), "type": type(e).__name__}}
                yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
        
        return StreamingResponse(generate_stream(), media_type="text/event-stream")
    else:
        try:
            response = await api.create(**body, extra_headers=extra_headers)
            process_time = time.time() - start_time
            logger.info(f"[{request_id}] Successfully completed Claude native request in {process_time:.3f}s")
            return response.model_dump() if hasattr(response, 'model_dump') else response.dict()
        except Exception as e:
            logger.error(f"Claude native request failed: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": {"message": str(e), "type": type(e).__name__}}
            )


def calculate_workers():
    """Calculate optimal number of workers based on environment or CPU count"""
    if MAX_WORKERS > 0:
        return MAX_WORKERS
    return multiprocessing.cpu_count()


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
