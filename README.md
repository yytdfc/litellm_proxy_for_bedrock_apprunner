# LiteLLM Proxy for Amazon Bedrock

A FastAPI server that provides an OpenAI-compatible API interface for Amazon Bedrock using LiteLLM.

## Features

- OpenAI API compatibility
- Support for Amazon Bedrock models
- Streaming responses
- API key authentication
- Auto-scaling with AWS App Runner
- CloudFormation deployment

## Quick Start: One-Step Deployment

For the fastest deployment experience, use the all-in-one script:

```bash
# Run the all-in-one deployment script
./deploy-all-in-one.sh
```

This script will:
1. Set up environment variables
2. Build and push a Docker image to ECR
3. Deploy the application to AWS App Runner using CloudFormation

For automated deployments, use the `-y` flag to skip confirmations:
```bash
./deploy-all-in-one.sh --yes
```

To customize deployment settings, edit the `00.environment.sh` file before running the deployment script.

## Setup for Local Development

1. Clone this repository:
   ```
   git clone https://github.com/yytdfc/litellm_proxy_for_bedrock_apprunner.git
   cd litellm_proxy_for_bedrock_apprunner
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```
   cp .env.example .env
   ```
   Edit the `.env` file to add your AWS credentials and API key.

4. Run locally:
   ```
   uvicorn app.main:app --reload
   ```
   The API will be available at http://localhost:8000

5. Test the local deployment:
   ```
   cd client_examples
   cp .env_example .env
   # Edit .env with your local settings
   python openai_sdk_example.py
   ```

## Deployment Options

### Option 1: One-Step Deployment (Recommended)

```bash
./deploy-all-in-one.sh
# Or for automated deployments:
./deploy-all-in-one.sh --yes
```

### Option 2: Step-by-Step Deployment

For more control over the deployment process:

```bash
# 1. Set up environment variables
# Edit 00.environment.sh to customize deployment settings
source ./00.environment.sh

# 2. Build and push Docker image
./01.build_and_push.sh

# 3. Deploy with CloudFormation
./02.deploy.sh
```

Each script supports the `--yes` flag for automated deployments.

### Option 3: Manual Deployment via AWS Console

1. Build and push a Docker image or use the public one: `public.ecr.aws/y0a9p9k0/apprunner/litellm-proxy-for-bedrock:latest`
2. Deploy using the AWS CloudFormation console with the `02.cloudformation.yaml` template

## Testing Your Deployment

After deployment completes:

1. Note the API endpoint URL and API key from the script output
2. Configure the client:
   ```bash
   cd client_examples
   cp .env_example .env
   # Edit .env with your deployment values
   ```
3. Run the test client:
   ```bash
   python openai_sdk_example.py
   # or
   python openai_http_example.py
   ```

## API Usage

### Authentication

Include your API key in all requests:
```
Authorization: Bearer your_api_key
```

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
  "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello, who are you?"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

## Performance Tuning

Configure these parameters in the CloudFormation template:

- **AppRunnerMaxConcurrency**: Concurrent requests per instance
- **AppRunnerMaxSize**: Maximum number of instances for auto-scaling

Adjust these values based on your expected traffic and performance requirements.
