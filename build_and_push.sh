#!/bin/bash
LITELLM_NAMESPACE=${LITELLM_NAMESPACE:-"ghcr.io/berriai/litellm"}
LITELLM_VERSION=${LITELLM_VERSION:-"litellm_stable_release_branch-v1.74.0-stable"}
ECR_NAMESPACE=${ECR_NAMESPACE:-"apprunner/litellm-proxy-for-bedrock"}
DOCKER_ARCH=${DOCKER_ARCH:-"linux/amd64"}

# Get the ACCOUNT and REGION defined in the current configuration (default to us-west-2 if none defined)

ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
REGION=${REGION:-$(aws configure get region)}
if [ -z "$REGION" ]; then
    TOKEN=`curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
    REGION=`curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region`
fi
echo $REGION

# If the repository doesn't exist in ECR, create it.
aws ecr describe-repositories --region ${REGION} --repository-names "${ECR_NAMESPACE}" > /dev/null 2>&1
if [ $? -ne 0 ]
then
echo "create repository:" "${ECR_NAMESPACE}"
aws ecr create-repository --region ${REGION} --repository-name "${ECR_NAMESPACE}" > /dev/null
fi

# Log into Docker
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com
REPO_NAME="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_NAMESPACE}"

echo ${REPO_NAME}

# Build docker
echo docker build --platform $DOCKER_ARCH --build-arg LITELLM_VERSION=${LITELLM_VERSION} LITELLM_NAMESPACE=${LITELLM_NAMESPACE} -t ${ECR_NAMESPACE}:${LITELLM_VERSION} .

docker build --platform $DOCKER_ARCH \
  --build-arg LITELLM_VERSION=${LITELLM_VERSION} \
  --build-arg LITELLM_NAMESPACE=${LITELLM_NAMESPACE} \
  -t ${ECR_NAMESPACE}\:${LITELLM_VERSION} .

# Push it
docker tag ${ECR_NAMESPACE}:${LITELLM_VERSION} ${REPO_NAME}:${LITELLM_VERSION}
docker push ${REPO_NAME}:${LITELLM_VERSION}
docker tag ${ECR_NAMESPACE}:${LITELLM_VERSION} ${REPO_NAME}:latest
docker push ${REPO_NAME}:latest

echo Build and push completed
echo Image URI: 

echo ${REPO_NAME}:${LITELLM_VERSION}
echo ${REPO_NAME}:latest
