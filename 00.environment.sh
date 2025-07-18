#!/bin/bash
# LiteLLM Proxy for Amazon Bedrock - Environment Setup Script
# This script sets up environment variables for the build and deployment process

# Stack name for CloudFormation
export STACK_NAME="litellm-proxy-bedrock"

# LiteLLM configuration
export LITELLM_NAMESPACE="ghcr.io/berriai/litellm"
export LITELLM_VERSION="litellm_stable_release_branch-v1.74.0-stable"

# ECR configuration
export ECR_NAMESPACE="apprunner/litellm-proxy-for-bedrock"
export DOCKER_ARCH="linux/amd64"

# AWS configuration - detect account and region
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
export REGION=$(aws configure get region 2>/dev/null || echo "")

# If region is still empty, try to get it from EC2 metadata
if [ -z "$REGION" ]; then
    TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" || echo "")
    if [ -n "$TOKEN" ]; then
        REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region || echo "")
    fi
    
    # If still empty, default to us-west-2
    if [ -z "$REGION" ]; then
        REGION="us-west-2"
        echo "Could not detect region, defaulting to us-west-2"
    fi
fi

# Calculate the full repository name
export REPO_NAME="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_NAMESPACE}"
export ECR_IMAGE_URI="${REPO_NAME}:latest"

# App Runner configuration
export AWS_REGION="$REGION"  # Use the same region for Bedrock service
export APP_RUNNER_CPU="1 vCPU"
export APP_RUNNER_MEMORY="2 GB"
export APP_RUNNER_MAX_CONCURRENCY=100
export APP_RUNNER_MAX_SIZE=10

# Display configuration
echo "Environment configured with the following settings:"
echo "Stack Name: $STACK_NAME"
echo "AWS Account: $ACCOUNT"
echo "AWS Region: $REGION"
echo "LiteLLM Namespace: $LITELLM_NAMESPACE"
echo "LiteLLM Version: $LITELLM_VERSION"
echo "ECR Namespace: $ECR_NAMESPACE"
echo "Docker Architecture: $DOCKER_ARCH"
echo "Repository: $REPO_NAME"
echo "ECR Image URI: $ECR_IMAGE_URI"
echo "App Runner CPU: $APP_RUNNER_CPU"
echo "App Runner Memory: $APP_RUNNER_MEMORY"
echo "App Runner Max Concurrency: $APP_RUNNER_MAX_CONCURRENCY"
echo "App Runner Max Size: $APP_RUNNER_MAX_SIZE"
echo ""
echo "Environment variables have been set for the current shell session."
echo "To use these variables in another shell, source this script:"
echo "source ./00.environment.sh"
echo ""
echo "To customize these settings, edit this script directly."
