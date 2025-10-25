#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}📦 Building container images with SAM...${NC}"

# Clean previous builds
echo -e "${YELLOW}Cleaning previous builds...${NC}"
rm -rf .aws-sam

# Build all container images
sam build --use-container --parallel

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Build complete!${NC}"
    echo ""
    echo "Container images built:"
    echo "  - SharedServicesFn (OpenAI Moderation)"
    echo "  - IntentServiceFn (CrewAI)"
    echo "  - ApiGatewayFn (Gateway)"
    echo ""
    echo "Next step: Run './deploy.sh' to deploy to AWS"
else
    echo -e "${RED}❌ Build failed${NC}"
    exit 1
fi