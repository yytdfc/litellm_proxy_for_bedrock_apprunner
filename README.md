# LiteLLM Proxy for Amazon Bedrock

OpenAI-compatible API proxy for Amazon Bedrock, deployed on AWS App Runner via CloudFormation.

## Deploy

Deploy using the public Docker image, no build required:

```bash
aws cloudformation deploy \
  --template-file 02.cloudformation.yaml \
  --stack-name litellm-proxy-bedrock \
  --capabilities CAPABILITY_IAM
```

After deployment, get your API Base URL and API Key from CloudFormation Outputs.

API Key is stored in AWS Secrets Manager — click the link in Outputs to retrieve it.

## Configure Claude Code

`~/.claude/settings.json`:

```json
{
  "apiKeyHelper": "echo YOUR_API_KEY",
  "primaryProvider": {
    "baseURL": "https://xxxxxxxxxx.us-west-2.awsapprunner.com/v1",
    "model": "claude-sonnet-4-6"
  }
}
```

## Configure OpenClaw

`~/.openclaw/openclaw.json`:

```json
{
  "apiKey": "YOUR_API_KEY",
  "baseURL": "https://xxxxxxxxxx.us-west-2.awsapprunner.com/v1",
  "model": "claude-sonnet-4-6"
}
```

Replace `xxxxxxxxxx.us-west-2.awsapprunner.com` with your actual API Base URL from CloudFormation Outputs.

## Supported Model Aliases

| Alias | Bedrock Model ID |
|---|---|
| `claude-sonnet-4-5` | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `claude-haiku-4-5` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `claude-opus-4-5` | `global.anthropic.claude-opus-4-5-20251101-v1:0` |
| `claude-opus-4-6` | `global.anthropic.claude-opus-4-6-v1` |
| `claude-sonnet-4-6` | `global.anthropic.claude-sonnet-4-6` |

You can also use any Bedrock model ID directly (e.g. `us.anthropic.claude-3-7-sonnet-20250219-v1:0`).

## CloudFormation Parameters

| Parameter | Default | Description |
|---|---|---|
| `ECRImageURI` | `public.ecr.aws/.../latest` | Docker image URI |
| `AWSRegion` | `us-west-2` | Bedrock region |
| `AppRunnerCPU` | `1 vCPU` | CPU per instance |
| `AppRunnerMemory` | `2 GB` | Memory per instance |
| `AppRunnerMaxConcurrency` | `100` | Concurrent requests per instance |
| `AppRunnerMaxSize` | `10` | Max auto-scaling instances |

## API Usage

```bash
# List models
curl -H "Authorization: Bearer YOUR_API_KEY" \
  https://xxxxxxxxxx.us-west-2.awsapprunner.com/v1/models

# Chat completions
curl -X POST -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  https://xxxxxxxxxx.us-west-2.awsapprunner.com/v1/chat/completions \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"Hello"}]}'
```

## Build & Deploy from Source

```bash
./deploy-all-in-one.sh        # interactive
./deploy-all-in-one.sh --yes  # non-interactive
```

Or step by step:

```bash
source ./00.environment.sh    # set env vars
./01.build_and_push.sh        # build & push to ECR
./02.deploy.sh                # deploy CloudFormation
```

## Local Development

```bash
pip install -r app/requirements.txt
cp .env.example .env          # edit with your AWS credentials and API key
uvicorn app.main:app --reload
```
