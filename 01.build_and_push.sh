#!/bin/bash
set -e

# LiteLLM Proxy for Amazon Bedrock - Build and Push Script
# This script builds and pushes a Docker image to Amazon ECR

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
LITELLM_NAMESPACE=${LITELLM_NAMESPACE:-"ghcr.io/berriai/litellm"}
LITELLM_VERSION=${LITELLM_VERSION:-"litellm_stable_release_branch-v1.74.0-stable"}
ECR_NAMESPACE=${ECR_NAMESPACE:-"apprunner/litellm-proxy-for-bedrock"}
DOCKER_ARCH=${DOCKER_ARCH:-"linux/amd64"}

# Get the ACCOUNT and REGION defined in the current configuration
ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
REGION=${REGION:-$(aws configure get region)}

# If region is still empty, try to get it from EC2 metadata (for EC2 instances)
if [ -z "$REGION" ]; then
    TOKEN=`curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
    REGION=`curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region`
fi

# Calculate the full repository name
REPO_NAME="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_NAMESPACE}"

# Display configuration
echo "Building and pushing LiteLLM Proxy for Amazon Bedrock with the following configuration:"
echo "AWS Account: $ACCOUNT"
echo "AWS Region: $REGION"
echo "LiteLLM Namespace: $LITELLM_NAMESPACE"
echo "LiteLLM Version: $LITELLM_VERSION"
echo "ECR Namespace: $ECR_NAMESPACE"
echo "Docker Architecture: $DOCKER_ARCH"
echo "Repository: $REPO_NAME"
echo ""

# Confirm build and push if not in auto-confirm mode
if [ "$AUTO_CONFIRM" = false ]; then
  read -p "Continue with build and push? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Build and push cancelled."
      exit 1
  fi
fi

# If the repository doesn't exist in ECR, create it.
echo "Checking if ECR repository exists..."
aws ecr describe-repositories --region ${REGION} --repository-names "${ECR_NAMESPACE}" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Creating repository: ${ECR_NAMESPACE}"
    aws ecr create-repository --region ${REGION} --repository-name "${ECR_NAMESPACE}" > /dev/null
fi

# Log into Docker
echo "Logging into ECR..."
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com

# Build docker
echo "Building Docker image..."
echo "Command: docker build --platform $DOCKER_ARCH --build-arg LITELLM_VERSION=${LITELLM_VERSION} --build-arg LITELLM_NAMESPACE=${LITELLM_NAMESPACE} -t ${ECR_NAMESPACE}:${LITELLM_VERSION} ."

docker build --platform $DOCKER_ARCH \
  --build-arg LITELLM_VERSION=${LITELLM_VERSION} \
  --build-arg LITELLM_NAMESPACE=${LITELLM_NAMESPACE} \
  -t ${ECR_NAMESPACE}:${LITELLM_VERSION} .

echo "Docker image built successfully."

# Confirm push if not in auto-confirm mode
if [ "$AUTO_CONFIRM" = false ]; then
  read -p "Push the image to ECR? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Push cancelled. The image is available locally as ${ECR_NAMESPACE}:${LITELLM_VERSION}"
      exit 0
  fi
fi

# Push it
echo "Pushing images to ECR..."
docker tag ${ECR_NAMESPACE}:${LITELLM_VERSION} ${REPO_NAME}:${LITELLM_VERSION}
docker push ${REPO_NAME}:${LITELLM_VERSION}
docker tag ${ECR_NAMESPACE}:${LITELLM_VERSION} ${REPO_NAME}:latest
docker push ${REPO_NAME}:latest

echo "Build and push completed successfully!"
echo "Image URIs:"
echo "${REPO_NAME}:${LITELLM_VERSION}"
echo "${REPO_NAME}:latest"
echo ""
echo "To use this image in deployment, run:"
echo "export ECR_IMAGE_URI=${REPO_NAME}:latest"
echo "./02.deploy.sh"
