# LiteLLM Proxy for Amazon Bedrock

A FastAPI server that provides an OpenAI-compatible API interface for Amazon Bedrock using LiteLLM.

## Features

- OpenAI API compatibility
- Support for Amazon Bedrock models
- Streaming responses
- Request-specific AWS credentials via Authorization header
- Easy deployment to AWS App Runner

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Configure AWS credentials:
   - Create a `.env` file based on `.env.example`
   - Add your AWS credentials (these will be used as fallback if not provided in the request)

## Running Locally

```
uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000

## API Usage

### Authentication

You can provide AWS credentials in the Authorization header:

```
Authorization: Bearer your_aws_access_key_id@your_aws_secret_access_key
```

If credentials are not provided in the header, the application will fall back to the environment variables.

### List Available Models
```
GET /v1/models
```

### Chat Completions
```
POST /v1/chat/completions
```

Example request:
```json
{
  "model": "gpt-3.5-turbo",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello, who are you?"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

## Using the Example Client

```
python client_example.py
```

For streaming:

```
python client_example.py --stream
```

## Deployment to AWS App Runner

1. Push this repository to a git repository
2. Create a new AWS App Runner service
3. Select "Source code repository"
4. Connect your repository
5. Select the branch to deploy
6. Configure build settings:
   - Runtime: Python
   - Build command: pip install -r requirements.txt
   - Start command: uvicorn app.main:app --host 0.0.0.0 --port 8080
7. Configure service settings:
   - Add environment variables for default AWS credentials
8. Create and deploy the service

## Environment Variables

- `AWS_ACCESS_KEY_ID`: Your default AWS access key
- `AWS_SECRET_ACCESS_KEY`: Your default AWS secret key
- `AWS_REGION`: AWS region (default: us-west-2)

## Adding More Models

Edit the `MODEL_MAPPING` dictionary in `app/main.py` to add more model mappings.