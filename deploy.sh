#!/bin/bash
set -euo pipefail

STACK_NAME="travel-planner-stack"
REGION="ap-southeast-2"
OPENAI_KEY="${OPENAI_KEY:-REPLACE_ME}"

# Let SAM manage the artifacts bucket automatically
sam deploy \
  --template-file template.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION" \
  --resolve-s3 \
  --parameter-overrides \
    OpenAIKey="$OPENAI_KEY" \
    ModelName=gpt-4o-mini \
    OWNER="${STACK_OWNER:-default}" \
    StateBucketName="stp-state-${OWNER}-${REGION}-$(date +%Y%m%d%H%M%S)" \
    StateBasePrefix=prod \
    AwsS3Endpoint="" \
  --no-confirm-changeset
