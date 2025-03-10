#!/bin/bash
LITELLM_VERSION=${LITELLM_VERSION:-"v1.63.2-stable"}
REPO_NAMESPACE=${REPO_NAMESPACE:-"apprunner/litellm-proxy-for-bedrock"}

# Get the ACCOUNT and REGION defined in the current configuration (default to us-west-2 if none defined)

ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}
REGION=${REGION:-$(aws configure get region)}

# If the repository doesn't exist in ECR, create it.
aws ecr describe-repositories --region ${REGION} --repository-names "${REPO_NAMESPACE}" > /dev/null 2>&1
if [ $? -ne 0 ]
then
echo "create repository:" "${REPO_NAMESPACE}"
aws ecr create-repository --region ${REGION} --repository-name "${REPO_NAMESPACE}" > /dev/null
fi

# Log into Docker
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com
REPO_NAME="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAMESPACE}:${LITELLM_VERSION}"

echo ${REPO_NAME}

# Build docker
docker build --build-arg LITELLM_VERSION=${LITELLM_VERSION} -t ${REPO_NAMESPACE}:${LITELLM_VERSION} .

# Push it
docker tag ${REPO_NAMESPACE}:${LITELLM_VERSION} ${REPO_NAME}
docker push ${REPO_NAME}
