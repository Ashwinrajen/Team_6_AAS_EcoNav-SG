#!/bin/bash
set -euo pipefail

# ---- Config -----------------------------------------------------
export SAM_CLI_TELEMETRY=0
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

STACK_NAME="${STACK_NAME:-travel-planner-stack}"
REGION="${AWS_REGION:-ap-southeast-2}"
OPENAI_KEY="${OPENAI_KEY:-}"
OWNER="${STACK_OWNER:-$(whoami)}"
AWS_PROFILE="${AWS_PROFILE:-default}"

# App state bucket (your app writes sessions here; SAM will still use its own managed bucket)
BUCKET_NAME="stp-state-${OWNER}-${REGION}-$(date +%Y%m%d)"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}🚀 Deploying Travel Planner Stack${NC}"
[ -n "$OPENAI_KEY" ] || { echo -e "${RED}❌ OPENAI_KEY not set${NC}"; exit 1; }

echo -e "${YELLOW}   S3 Bucket (app state): $BUCKET_NAME${NC}"

# ---- Clean previous build --------------------------------------
echo -e "${YELLOW}📦 Cleaning previous builds...${NC}"
rm -rf .aws-sam || true
docker image rm -f apigatewayfn:latest sharedservicesfn:latest intentservicefn:latest 2>/dev/null || true

# ---- Build ------------------------------------------------------
echo -e "${YELLOW}🧱 Building container images (SAM, in Docker)...${NC}"
sam build --use-container --parallel

# Guard: fail fast if any reserved env keys made it into the compiled template
if grep -E -n 'AWS_REGION|AWS_DEFAULT_REGION|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|LAMBDA_' \
  .aws-sam/build/template.yaml >/dev/null 2>&1; then
  echo -e "${RED}❌ Reserved Lambda/AWS env var found in compiled template (.aws-sam/build/template.yaml).${NC}"
  echo "   Remove any of these from Environment.Variables in your template: AWS_*, LAMBDA_*"
  exit 1
fi

# ---- Handle bad stack states -----------------------------------
status="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
  --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_FOUND")"

if [[ "$status" == "ROLLBACK_COMPLETE" ]]; then
  echo -e "${YELLOW}⚠️  Stack '$STACK_NAME' is ROLLBACK_COMPLETE. Deleting before re-deploy...${NC}"
  aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION" --profile "$AWS_PROFILE"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION" --profile "$AWS_PROFILE"
fi

# ---- Deploy -----------------------------------------------------
echo -e "${YELLOW}🚀 Deploying to AWS...${NC}"
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION" \
  --resolve-s3 \
  --resolve-image-repos \
  --parameter-overrides \
    OpenAIKey="$OPENAI_KEY" \
    ModelName=gpt-4o-mini \
    StateBucketName="$BUCKET_NAME" \
    StateBasePrefix=prod \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --profile "$AWS_PROFILE"

echo ""

# ---- Fetch API URL output (ensure template defines Output 'ApiUrl') ----
echo -e "${YELLOW}📍 Getting API URL...${NC}"
API_URL="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' --output text 2>/dev/null || echo "")"

if [ -n "$API_URL" ] && [ "$API_URL" != "None" ]; then
  echo -e "${GREEN}✅ Deployment complete!${NC}"
  echo -e "${GREEN}🌐 API URL: $API_URL${NC}"
  echo -e "${YELLOW}Test:${NC}  curl \"$API_URL/health\""
else
  echo -e "${YELLOW}⚠️  Deployed, but couldn't find 'ApiUrl' output.${NC}"
  echo "   Check your template Outputs or run: sam list endpoints"
fi
