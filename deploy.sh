#!/bin/bash
set -euo pipefail

# ================================================================================
# IMPROVED DEPLOY SCRIPT WITH COMPREHENSIVE ERROR HANDLING
# ================================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  SUSTAINABLE TRAVEL PLANNER - AWS DEPLOYMENT SCRIPT      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ---- Configuration -----------------------------------------------------
export SAM_CLI_TELEMETRY=0
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

STACK_NAME="${STACK_NAME:-travel-planner-stack}"
REGION="${AWS_REGION:-ap-southeast-1}"
OPENAI_KEY="${OPENAI_KEY:-}"
OWNER="${STACK_OWNER:-$(whoami)}"
AWS_PROFILE="${AWS_PROFILE:-default}"

# Generate unique bucket name with timestamp
BUCKET_NAME="stp-req-${OWNER}-prod"  # Static bucket name

echo -e "${GREEN}Configuration:${NC}"
echo -e "  Stack Name:    ${YELLOW}$STACK_NAME${NC}"
echo -e "  Region:        ${YELLOW}$REGION${NC}"
echo -e "  S3 Bucket:     ${YELLOW}$BUCKET_NAME${NC}"
echo -e "  AWS Profile:   ${YELLOW}$AWS_PROFILE${NC}"
echo ""

# ---- Validate Prerequisites --------------------------------------------
echo -e "${BLUE}[1/7] Validating prerequisites...${NC}"

if [ -z "$OPENAI_KEY" ]; then
    echo -e "${RED}❌ ERROR: OPENAI_KEY environment variable is not set${NC}"
    echo ""
    echo "Please set your OpenAI API key:"
    echo "  export OPENAI_KEY='your-key-here'"
    exit 1
fi

if ! command -v sam &> /dev/null; then
    echo -e "${RED}❌ ERROR: AWS SAM CLI not found${NC}"
    echo "Install from: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ ERROR: Docker not found${NC}"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ ERROR: AWS CLI not found${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All prerequisites found${NC}"
echo ""

# ---- Clean Previous Build ----------------------------------------------
echo -e "${BLUE}[2/7] Cleaning previous builds...${NC}"

if [ -d ".aws-sam" ]; then
    echo "Removing .aws-sam directory..."
    rm -rf .aws-sam
fi

# Remove Docker images to force fresh builds
echo "Removing old Docker images..."
docker image rm -f \
    apigatewayfn:latest \
    sharedservicesfn:latest \
    intentservicefn:latest \
    2>/dev/null || true

echo -e "${GREEN}✅ Cleanup complete${NC}"
echo ""

# ---- Handle Existing Stack ---------------------------------------------
echo -e "${BLUE}[3/7] Checking for existing stack...${NC}"

status="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")"

if [[ "$status" == "ROLLBACK_COMPLETE" ]]; then
    echo -e "${YELLOW}⚠️  Stack is in ROLLBACK_COMPLETE state${NC}"
    echo "Deleting stack before re-deploy..."
    
    aws cloudformation delete-stack \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE"
    
    echo "Waiting for stack deletion..."
    aws cloudformation wait stack-delete-complete \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE"
    
    echo -e "${GREEN}✅ Old stack deleted${NC}"
    
elif [[ "$status" != "NOT_FOUND" ]]; then
    echo -e "${YELLOW}⚠️  Existing stack found with status: $status${NC}"
    echo "Stack will be updated (not deleted)"
fi

echo ""

# ---- Build Container Images --------------------------------------------
echo -e "${BLUE}[4/7] Building container images...${NC}"
echo -e "${YELLOW}This may take 5-10 minutes on first build...${NC}"
echo ""

# Run SAM build with progress indication
if sam build --use-container --parallel; then
    echo ""
    echo -e "${GREEN}✅ Container images built successfully${NC}"
else
    echo ""
    echo -e "${RED}❌ Build failed${NC}"
    echo ""
    echo "Common issues:"
    echo "  1. Check Dockerfile syntax"
    echo "  2. Ensure requirements files exist"
    echo "  3. Check Docker daemon is running"
    echo "  4. Review build logs above for details"
    exit 1
fi

echo ""

# ---- Validate Build Output ---------------------------------------------
echo -e "${BLUE}[5/7] Validating build output...${NC}"

if [ ! -f ".aws-sam/build/template.yaml" ]; then
    echo -e "${RED}❌ Built template not found${NC}"
    exit 1
fi

# Check for reserved environment variable names
if grep -E -n 'AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|LAMBDA_RUNTIME' \
    .aws-sam/build/template.yaml >/dev/null 2>&1; then
    echo -e "${RED}❌ ERROR: Reserved Lambda environment variable found in template${NC}"
    echo "Remove these from Environment.Variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN, LAMBDA_*"
    exit 1
fi

echo -e "${GREEN}✅ Build validation passed${NC}"
echo ""

# ---- Deploy to AWS -----------------------------------------------------
echo -e "${BLUE}[6/7] Deploying to AWS...${NC}"
echo -e "${YELLOW}This will take 10-15 minutes...${NC}"
echo ""

if sam deploy \
    --template-file .aws-sam/build/template.yaml \
    --stack-name "$STACK_NAME" \
    --capabilities CAPABILITY_IAM \
    --region "$REGION" \
    --resolve-s3 \
    --resolve-image-repos \
    --parameter-overrides \
        OpenAIKey="$OPENAI_KEY" \
        ModelName=gpt-4o \
        StateBucketName="$BUCKET_NAME" \
        StateBasePrefix=prod \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --profile "$AWS_PROFILE"; then
    
    echo ""
    echo -e "${GREEN}✅ Deployment successful${NC}"
else
    echo ""
    echo -e "${RED}❌ Deployment failed${NC}"
    echo ""
    echo "To view CloudFormation events:"
    echo "  aws cloudformation describe-stack-events --stack-name $STACK_NAME --region $REGION --profile $AWS_PROFILE"
    exit 1
fi

echo ""

# ---- Get API URL -------------------------------------------------------
echo -e "${BLUE}[7/7] Retrieving API URL...${NC}"

API_URL="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text 2>/dev/null || echo "")"

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                  DEPLOYMENT COMPLETE                      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ -n "$API_URL" ] && [ "$API_URL" != "None" ]; then
    echo -e "${GREEN}🌐 API Gateway URL:${NC}"
    echo -e "   ${YELLOW}$API_URL${NC}"
    echo ""
    echo -e "${GREEN}📦 S3 Bucket:${NC}"
    echo -e "   ${YELLOW}$BUCKET_NAME${NC}"
    echo ""
    echo -e "${BLUE}🧪 Test Commands:${NC}"
    echo ""
    echo -e "${YELLOW}# Health Check${NC}"
    echo "curl -s \"$API_URL/health\" | jq"
    echo ""
    echo -e "${YELLOW}# Simple Greeting${NC}"
    echo "curl -X POST \"$API_URL/travel/plan\" \\"
    echo "  -H \"Content-Type: application/json\" \\"
    echo "  -d '{\"user_input\":\"Hello!\",\"session_id\":null}' | jq"
    echo ""
    echo -e "${YELLOW}# Complete Travel Plan${NC}"
    echo "curl -X POST \"$API_URL/travel/plan\" \\"
    echo "  -H \"Content-Type: application/json\" \\"
    echo "  -d '{\"user_input\":\"I want to visit Singapore from Dec 20-25, 2025 with a budget of 2000 SGD, relaxed pace\",\"session_id\":null}' | jq"
    echo ""
    echo -e "${BLUE}📊 Monitor Logs:${NC}"
    echo "sam logs --stack-name $STACK_NAME --region $REGION --tail"
    echo ""
    echo -e "${BLUE}🔍 View Stack Resources:${NC}"
    echo "aws cloudformation describe-stack-resources --stack-name $STACK_NAME --region $REGION"
    echo ""
else
    echo -e "${YELLOW}⚠️  Could not retrieve API URL${NC}"
    echo ""
    echo "To find your API URL manually:"
    echo "  aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query 'Stacks[0].Outputs'"
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Deployment script completed successfully                 ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"