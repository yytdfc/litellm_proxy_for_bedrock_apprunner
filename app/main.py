from fastapi import FastAPI, Request, Response, HTTPException, Depends
import uuid
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import litellm
import os
import json
import time
import re
import random
import logging
import base64
import zlib
from dotenv import load_dotenv
from typing import Dict, List, Any, Optional


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

# Default AWS credentials from environment variables
default_aws_key_id = os.getenv("AWS_ACCESS_KEY_ID", None)
default_aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", None)
default_aws_region = os.getenv("AWS_REGION", "us-west-2")

# Security scheme
security = HTTPBearer()

# Default model if none specified
DEFAULT_MODEL = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"

def parse_credential_pair(cred_pair: str) -> dict:
    """Parse a single credential pair in format aws_access_key_id@aws_secret_access_key
    The credential pair is expected to be zipped, base64 encoded"""
    try:
        
        if '@' in cred_pair:
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

@app.get("/v1/models")
async def list_models(credentials: List[dict] = Depends(get_aws_credentials)):
    """List available models in OpenAI format by querying AWS Bedrock"""
    import boto3
    import time
    
    # Shuffle credentials to try them in random order
    random.shuffle(credentials)
    last_exception = None
    
    # Try each credential pair until one succeeds
    for cred in credentials:
        try:
            # Log the AWS access key ID being used
            logger.info(f"Listing models using AWS access key: {cred['aws_access_key_id']}")
            
            # Create Bedrock client with current credentials
            bedrock_client = boto3.client(
                'bedrock',
                aws_access_key_id=cred["aws_access_key_id"],
                aws_secret_access_key=cred["aws_secret_access_key"],
                region_name=default_aws_region
            )
            
            # Call AWS Bedrock API to list foundation models
            response = bedrock_client.list_foundation_models()
            
            # Format response in OpenAI compatible format
            models = []
            # for model in response.get("modelSummaries", []):
            #     if "TEXT" not in model.get("outputModalities"):
            #         continue
            #     models.append({
            #         "id": model.get("modelId"),
            #         "object": "model",
            #         "owned_by": model.get("providerName", "unknown")
            #     })

            response = bedrock_client.list_inference_profiles()
            
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

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, credentials_list: List[dict] = Depends(get_aws_credentials), response: Response = None):
    """Handle OpenAI-formatted chat completion requests"""
    try:
        body = await request.json()
        try:
            for i in range(len(body["messages"])):
                if body["messages"][i]["role"] == "assistant":
                    if "tool_calls" in body["messages"][i]:
                        if body["messages"][i]["tool_calls"][0]["id"]:
                            tool_id = body["messages"][i]["tool_calls"][0]["id"]
                        else:
                            body["messages"][i]["tool_calls"][0]["id"] = uuid.uuid4().hex
                            tool_id = body["messages"][i]["tool_calls"][0]["id"]
                elif body["messages"][i]["role"] == "tool":
                    body["messages"][i]["tool_call_id"] = tool_id
        except Exception as e:
            pass

        # Parse and prepare model name - add "bedrock/" prefix if missing
        if "model" in body:
            if not body["model"].startswith("bedrock/"):
                body["model"] = f"bedrock/converse/{body['model']}"
        else:
            # Use default model if none provided
            body["model"] = f"bedrock/converse/{DEFAULT_MODEL}"
        
        print(credentials_list)
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
                if not "complete_response" in stream_options:
                    stream_options["complete_response"] = False
                
                # Try each credential pair until one succeeds
                for credentials in credentials_list:
                    try:
                        logger.info(f"Making chat completion using AWS access key: {credentials['aws_access_key_id']} for model: {body['model']}")
                        # Set AWS credentials for this request
                        aws_config = {
                            "aws_access_key_id": credentials["aws_access_key_id"],
                            "aws_secret_access_key": credentials["aws_secret_access_key"],
                            "aws_region_name": default_aws_region
                        }
                        
                        # Forward request directly to LiteLLM with AWS credentials
                        response = await litellm.acompletion(**stream_options, **aws_config)
                        tool_id = ""
                        
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
                            
                            try:
                                if chunk_dict["choices"][0]["delta"]["tool_calls"]:
                                    if len(tool_id) == 0:
                                        tool_id = chunk_dict["choices"][0]["delta"]["tool_calls"][0]["id"]
                                    else:
                                        chunk_dict["choices"][0]["delta"]["tool_calls"][0]["id"] = tool_id
                            except Exception as e:
                                pass
                            # Format as proper SSE
                            chunk_str = json.dumps(chunk_dict)
                            # print(chunk_str)
                            yield f"data: {chunk_str}\n\n"
                        
                        yield "data: [DONE]\n\n"
                        return  # Successfully streamed response
                    except Exception as e:
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
                logger.info(f"Making chat completion using AWS access key: {credentials['aws_access_key_id']} for model: {body['model']}")
                
                # Set AWS credentials for this request
                aws_config = {
                    "aws_access_key_id": credentials["aws_access_key_id"],
                    "aws_secret_access_key": credentials["aws_secret_access_key"],
                    "aws_region_name": default_aws_region
                }
                
                # Handle regular responses - forward request directly
                response = await litellm.acompletion(**body, **aws_config)
                
                # Log successful completion
                logger.info(f"Successfully completed chat request with AWS access key: {credentials['aws_access_key_id']}")
                
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
                logger.error(f"Failed chat completion with AWS access key: {credentials['aws_access_key_id']}, error: {str(e)}")
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

if __name__ == "__main__":
    import uvicorn
    import multiprocessing

    # Calculate optimal workers based on CPU cores
    workers = multiprocessing.cpu_count() * 2 + 1
    print(workers)
    
    # Run with optimized settings for performance
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=int(os.environ.get("PORT", "8080")),
        workers=workers,  # Multiple worker processes
        # loop="asyncio",    # Faster event loop for this task
        loop="uvloop",    # Faster event loop implementation
        http="httptools", # Faster HTTP protocol implementation
        limit_concurrency=1024,  # Increase concurrent connections limit
        backlog=2048      # Increase connection queue size
    )
