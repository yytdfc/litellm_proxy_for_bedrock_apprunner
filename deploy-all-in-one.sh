#!/bin/bash
set -e

# LiteLLM Proxy for Amazon Bedrock - All-in-One Deployment Script
# This script runs all three steps: environment setup, build & push, and deployment

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

# Function to confirm action
confirm_action() {
  if [ "$AUTO_CONFIRM" = false ]; then
    read -p "$1 (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Operation cancelled."
      exit 1
    fi
  fi
}

echo "=========================================================="
echo "LiteLLM Proxy for Amazon Bedrock - All-in-One Deployment"
echo "=========================================================="
echo ""
echo "This script will perform the following steps:"
echo "1. Set up environment variables"
echo "2. Build and push Docker image to ECR"
echo "3. Deploy the application to AWS App Runner using CloudFormation"
echo ""

confirm_action "Continue with the deployment process?"

# Step 1: Set up environment variables
echo ""
echo "=========================================================="
echo "Step 1: Setting up environment variables"
echo "=========================================================="
source ./00.environment.sh

# Step 2: Build and push Docker image
echo ""
echo "=========================================================="
echo "Step 2: Building and pushing Docker image"
echo "=========================================================="
confirm_action "Continue with building and pushing the Docker image?"

# Run the build and push script with auto-confirm if specified
if [ "$AUTO_CONFIRM" = true ]; then
  ./01.build_and_push.sh --yes
else
  ./01.build_and_push.sh
fi

# Step 3: Deploy to AWS App Runner
echo ""
echo "=========================================================="
echo "Step 3: Deploying to AWS App Runner"
echo "=========================================================="
confirm_action "Continue with deploying to AWS App Runner?"

# Run the deploy script with auto-confirm if specified
if [ "$AUTO_CONFIRM" = true ]; then
  ./02.deploy.sh --yes
else
  ./02.deploy.sh
fi

echo ""
echo "=========================================================="
echo "Deployment Complete!"
echo "=========================================================="
