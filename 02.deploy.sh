#!/bin/bash
set -e

# LiteLLM Proxy for Amazon Bedrock - Deployment Script
# This script deploys the LiteLLM Proxy to AWS App Runner using AWS CLI

# Parse command line arguments
AUTO_CONFIRM=false
for arg in "$@"; do
  case $arg in
    -y|--yes)
      AUTO_CONFIRM=true
      shift
      ;;
    *)
      # Unknown option
      ;;
  esac
done

# Default values (can be overridden by environment variables)
STACK_NAME=${STACK_NAME:-"litellm-proxy-bedrock"}
LITELLM_VERSION=${LITELLM_VERSION:-"latest"}
ECR_NAMESPACE=${ECR_NAMESPACE:-"apprunner/litellm-proxy-for-bedrock"}
# ============================================================
ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
REGION=${REGION:-$(aws configure get region)}
if [ -z "$REGION" ]; then
    TOKEN=`curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
    REGION=`curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region`
fi
REPO_NAME="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_NAMESPACE}"
ECR_IMAGE_URI=${ECR_IMAGE_URI:-${REPO_NAME}:latest}
# or
# ECR_IMAGE_URI=${ECR_IMAGE_URI:-"public.ecr.aws/y0a9p9k0/apprunner/litellm-proxy-for-bedrock:latest"}
# ============================================================
AWS_REGION=${AWS_REGION:-"us-west-2"}
APP_RUNNER_CPU=${APP_RUNNER_CPU:-"1 vCPU"}
APP_RUNNER_MEMORY=${APP_RUNNER_MEMORY:-"2 GB"}
APP_RUNNER_MAX_CONCURRENCY=${APP_RUNNER_MAX_CONCURRENCY:-100}
APP_RUNNER_MAX_SIZE=${APP_RUNNER_MAX_SIZE:-10}

# Display configuration
echo "Deploying LiteLLM Proxy for Amazon Bedrock with the following configuration:"
echo "Stack Name: $STACK_NAME"
echo "ECR Image URI: $ECR_IMAGE_URI"
echo "AWS Region: $AWS_REGION"
echo "App Runner CPU: $APP_RUNNER_CPU"
echo "App Runner Memory: $APP_RUNNER_MEMORY"
echo "App Runner Max Concurrency: $APP_RUNNER_MAX_CONCURRENCY"
echo "App Runner Max Size: $APP_RUNNER_MAX_SIZE"
echo ""

# Confirm deployment if not in auto-confirm mode
if [ "$AUTO_CONFIRM" = false ]; then
  read -p "Continue with deployment? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Deployment cancelled."
      exit 1
  fi
fi

# Set AWS region
aws configure set region $AWS_REGION

# Check if the stack already exists
STACK_EXISTS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME 2>/dev/null || echo "false")

if [[ $STACK_EXISTS != "false" ]]; then
    echo "Stack $STACK_NAME already exists. Updating..."
    UPDATE_OR_CREATE="update-stack"
    CHANGE_SET_TYPE="UPDATE"
else
    echo "Creating new stack $STACK_NAME..."
    UPDATE_OR_CREATE="create-stack"
    CHANGE_SET_TYPE="CREATE"
fi

# Create a change set to preview changes
CHANGE_SET_NAME="${STACK_NAME}-$(date +%y%m%d-%H%M%S)"

echo "Creating CloudFormation change set..."
aws cloudformation create-change-set \
    --stack-name $STACK_NAME \
    --change-set-name $CHANGE_SET_NAME \
    --template-body file://02.cloudformation.yaml \
    --capabilities CAPABILITY_IAM \
    --parameters \
        ParameterKey=ECRImageURI,ParameterValue=$ECR_IMAGE_URI \
        ParameterKey=AWSRegion,ParameterValue=$AWS_REGION \
        ParameterKey=AppRunnerCPU,ParameterValue="$APP_RUNNER_CPU" \
        ParameterKey=AppRunnerMemory,ParameterValue="$APP_RUNNER_MEMORY" \
        ParameterKey=AppRunnerMaxConcurrency,ParameterValue=$APP_RUNNER_MAX_CONCURRENCY \
        ParameterKey=AppRunnerMaxSize,ParameterValue=$APP_RUNNER_MAX_SIZE \
    --change-set-type $CHANGE_SET_TYPE

echo "Waiting for change set creation to complete..."
# Wait for change set creation but don't exit on error
aws cloudformation wait change-set-create-complete \
    --stack-name $STACK_NAME \
    --change-set-name $CHANGE_SET_NAME || true

# Check if the change set has changes or failed because there were no changes
CHANGE_SET_STATUS=$(aws cloudformation describe-change-set \
    --stack-name $STACK_NAME \
    --change-set-name $CHANGE_SET_NAME \
    --query 'Status' \
    --output text)

CHANGE_SET_STATUS_REASON=$(aws cloudformation describe-change-set \
    --stack-name $STACK_NAME \
    --change-set-name $CHANGE_SET_NAME \
    --query 'StatusReason' \
    --output text)

if [ "$CHANGE_SET_STATUS" == "FAILED" ] && [[ "$CHANGE_SET_STATUS_REASON" == *"didn't contain changes"* ]]; then
    echo "No changes detected in the CloudFormation stack. Your deployment is already up to date."
    SKIP_EXECUTION=true
else
    # Display the changes
    echo "Changes to be applied:"
    aws cloudformation describe-change-set \
        --stack-name $STACK_NAME \
        --change-set-name $CHANGE_SET_NAME \
        --query 'Changes[].{Action:ResourceChange.Action,LogicalResourceId:ResourceChange.LogicalResourceId,ResourceType:ResourceChange.ResourceType}' \
        --output table
    
    SKIP_EXECUTION=false
fi

# Confirm execution if not in auto-confirm mode and there are changes
if [ "$SKIP_EXECUTION" = false ] && [ "$AUTO_CONFIRM" = false ]; then
  read -p "Execute the changes? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Deployment cancelled."
      exit 1
  fi
fi

# Execute the change set if there are changes
if [ "$SKIP_EXECUTION" = false ]; then
  echo "Executing change set..."
  aws cloudformation execute-change-set \
      --stack-name $STACK_NAME \
      --change-set-name $CHANGE_SET_NAME

  echo "Waiting for stack deployment to complete..."
  if [[ $UPDATE_OR_CREATE == "create-stack" ]]; then
      aws cloudformation wait stack-create-complete --stack-name $STACK_NAME
  else
      aws cloudformation wait stack-update-complete --stack-name $STACK_NAME
  fi
else
  echo "Skipping change set execution as there are no changes."
fi

# Get outputs
echo "Deployment completed successfully!"
echo "Stack outputs:"
aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query 'Stacks[0].Outputs' \
    --output table

# Get API Key from Secrets Manager
SECRET_NAME=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query "Stacks[0].Outputs[?OutputKey=='APIKey'].OutputValue" \
    --output text)

SECRET_NAME=$(echo $SECRET_NAME | sed 's/.*name=\(.*\)/\1/')

echo "Retrieving API key from Secrets Manager..."
if command -v jq &> /dev/null; then
    # If jq is available, use it to parse the JSON
    API_KEY=$(aws secretsmanager get-secret-value --secret-id $SECRET_NAME --query 'SecretString' --output text | jq -r '.apiKey')
    echo "API Key: $API_KEY"
else
    # If jq is not available, provide instructions
    echo "To retrieve your API key, run:"
    echo "aws secretsmanager get-secret-value --secret-id $SECRET_NAME --query 'SecretString' --output text | jq -r '.apiKey'"
fi

# Get API Base URL
API_BASE_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --query "Stacks[0].Outputs[?OutputKey=='APIBaseURL'].OutputValue" \
    --output text)

echo "API Base URL: $API_BASE_URL"

# Instructions for testing
echo ""
echo "To test your deployment:"
echo "1. Use the API key printed above"
echo "2. Update client_examples/.env with your API_BASE and API_KEY"
echo "3. Run: cd client_examples && python openai_http_example.py"
