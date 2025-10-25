#!/bin/bash
set -euo pipefail

# -----------------------------
# Pretty colors
# -----------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Checking prerequisites...${NC}"
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Docker is required but not installed.${NC}" >&2; exit 1; }
command -v sam >/dev/null 2>&1 || { echo -e "${RED}SAM CLI is required but not installed.${NC}" >&2; exit 1; }

echo -e "${GREEN}Starting SAM build process...${NC}"

# -----------------------------
# Clean previous builds
# -----------------------------
echo -e "${YELLOW}Cleaning previous builds...${NC}"
rm -rf .aws-sam

# Defensive cleanup of any partial site-packages from earlier failed runs
find layers -maxdepth 3 -type d -name "__pycache__" -prune -exec rm -rf {} + || true

# Ensure layer python dirs exist (renamed nemo to openai)
mkdir -p layers/crewai/python layers/openai/python layers/common/python

# -----------------------------
# Clean layers
# -----------------------------
rm -rf layers/crewai/python/* layers/openai/python/* layers/common/python/* || true

# -----------------------------
# Build layers (hardened pip in Docker)
# -----------------------------
echo -e "${YELLOW}Building layers...${NC}"

# ---- CrewAI layer (uses LC 0.2.x band, no crewai-tools) ----
docker run --rm --network host -v "$PWD":/var/task public.ecr.aws/sam/build-python3.11:latest \
  /bin/bash -lc '
    set -euo pipefail
    python -m pip install --upgrade pip &&
    pip cache purge || true &&
    PIP_NO_CACHE_DIR=1 pip install \
      --retries 8 --timeout 120 --prefer-binary -i https://pypi.org/simple \
      -r layers/crewai/requirements.txt -t layers/crewai/python/
  '

if [ ! -d "layers/crewai/python" ] || [ -z "$(ls -A layers/crewai/python)" ]; then
    echo -e "${RED}Failed to build CrewAI layer${NC}"
    exit 1
fi

# ---- OpenAI layer (renamed from nemo) ----
docker run --rm --network host -v "$PWD":/var/task public.ecr.aws/sam/build-python3.11:latest \
  /bin/bash -lc '
    set -euo pipefail
    python -m pip install --upgrade pip &&
    pip cache purge || true &&
    PIP_NO_CACHE_DIR=1 pip install \
      --retries 8 --timeout 120 --prefer-binary -i https://pypi.org/simple \
      -r layers/openai/requirements.txt -t layers/openai/python/
  '

if [ ! -d "layers/openai/python" ] || [ -z "$(ls -A layers/openai/python)" ]; then
    echo -e "${RED}Failed to build openai layer${NC}"
    exit 1
fi

# ---- Common layer ----
docker run --rm --network host -v "$PWD":/var/task public.ecr.aws/sam/build-python3.11:latest \
  /bin/bash -lc '
    set -euo pipefail
    python -m pip install --upgrade pip &&
    pip cache purge || true &&
    PIP_NO_CACHE_DIR=1 pip install \
      --retries 8 --timeout 120 --prefer-binary -i https://pypi.org/simple \
      -r layers/common/requirements.txt -t layers/common/python/
  '

if [ ! -d "layers/common/python" ] || [ -z "$(ls -A layers/common/python)" ]; then
    echo -e "${RED}Failed to build common layer${NC}"
    exit 1
fi

# -----------------------------
# Swap in lambda-specific requirements for each service
# -----------------------------
echo -e "${YELLOW}Preparing service requirements...${NC}"

cp api-gateway/requirements-lambda.txt api-gateway/requirements.txt.bak
cp api-gateway/requirements-lambda.txt api-gateway/requirements.txt

cp intent-requirements-service/requirements-lambda.txt intent-requirements-service/requirements.txt.bak
cp intent-requirements-service/requirements-lambda.txt intent-requirements-service/requirements.txt

cp shared-services/requirements-lambda.txt shared-services/requirements.txt.bak
cp shared-services/requirements-lambda.txt shared-services/requirements.txt

# -----------------------------
# Build SAM application
# -----------------------------
echo -e "${YELLOW}Building SAM application...${NC}"
sam build --use-container --parallel

# -----------------------------
# Restore original requirements
# -----------------------------
mv api-gateway/requirements.txt.bak api-gateway/requirements.txt
mv intent-requirements-service/requirements.txt.bak intent-requirements-service/requirements.txt
mv shared-services/requirements.txt.bak shared-services/requirements.txt

echo -e "${GREEN}Build complete!${NC}"