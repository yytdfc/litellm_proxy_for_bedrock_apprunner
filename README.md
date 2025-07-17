# LiteLLM Proxy for Amazon Bedrock

A FastAPI server that provides an OpenAI-compatible API interface for Amazon Bedrock using LiteLLM.

## Features

- OpenAI API compatibility
- Support for Amazon Bedrock models
- Streaming responses
- API key authentication
- Auto-scaling with AWS App Runner
- CloudFormation deployment

## Deployment to AWS

### 1. Build and Push Docker Image

#### Option A: Build and push your own image (Recommended)

Building your own Docker image gives you more control over the environment and allows you to make custom modifications:

```bash
# Set environment variables (optional)
export LITELLM_VERSION=litellm_stable_release_branch-v1.74.0-stable
export ECR_NAMESPACE=apprunner/litellm-proxy-for-bedrock

# Build and push to your private ECR
./build_and_push.sh
```

The script will:
1. Create an ECR repository if it doesn't exist
2. Build the Docker image
3. Push the image to your ECR repository
4. Output the full image URI for use in CloudFormation

#### Option B: Use the public ECR image

Alternatively, you can use the pre-built public ECR image:
```
public.ecr.aws/y0a9p9k0/apprunner/litellm-proxy-for-bedrock:latest
```

### 2. Deploy with CloudFormation

1. Navigate to AWS CloudFormation in the AWS Console
2. Click "Create stack" > "With new resources (standard)"
3. Upload the `cloudformation.yaml` file
4. Fill in the parameters:
   - **ECRImageURI**: Use your own ECR image URI (recommended) or the public ECR image
   - **AWSRegion**: Region for Bedrock (default: us-west-2)
   - **AppRunnerCPU**: CPU units (1-4 vCPU)
   - **AppRunnerMemory**: Memory (2-8 GB)
   - **AppRunnerMaxConcurrency**: Max concurrent requests per instance
   - **AppRunnerMaxSize**: Maximum number of instances for auto-scaling
5. Click "Next" through the wizard and "Create stack"
6. Wait for the stack creation to complete (~5-10 minutes)

### 3. Get Deployment Information

After deployment completes:

1. Go to the CloudFormation stack's "Outputs" tab
2. Note the following values:
   - **APIBaseURL**: The endpoint URL for your API
   - **APIKey**: Link to retrieve your API key from Secrets Manager

### 4. Test the Deployment

1. Set up the client environment:
   ```bash
   cd client_examples
   cp .env_example .env
   ```

2. Edit the `.env` file with your deployment values:
   ```
   API_BASE=https://your-app-runner-url.awsapprunner.com/v1
   API_KEY=your-api-key-from-secrets-manager
   ```

3. Install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

4. Run the test client:
   ```bash
   python3 openai_sdk_example.py
   ```

This will:
- List available Bedrock models
- Send a chat completion request
- Test streaming capabilities

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
  "model": "anthropic.claude-3-sonnet-20240229-v1:0",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello, who are you?"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

## Environment Variables

- `API_KEY`: API key for authentication
- `AWS_REGION`: AWS region for Bedrock (default: us-west-2)

## Performance Tuning

The CloudFormation template allows you to configure:

- **AppRunnerMaxConcurrency**: Controls how many concurrent requests each instance can handle
- **AppRunnerMaxSize**: Controls the maximum number of instances for auto-scaling

Adjust these values based on your expected traffic and performance requirements.
