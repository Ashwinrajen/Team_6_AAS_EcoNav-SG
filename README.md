# 🌍 Intelligent Sustainable Travel Planning System - Intent and Requirements Gathering Agent

An AI-powered, serverless travel planning system that intelligently collects user requirements through conversational interfaces, validates inputs/outputs for security, and generates comprehensive travel plans. Built with microservices architecture on AWS Lambda using Docker containers.

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Technology Stack](#-technology-stack)
- [Prerequisites](#-prerequisites)
- [AWS Deployment](#-aws-deployment)
- [Testing](#-testing)
- [Security](#-security)
- [Monitoring & Debugging](#-monitoring--debugging)
- [Cleanup](#-cleanup)

---

## 🎯 Overview

The **Intelligent Sustainable Travel Planning System** is a production-ready, enterprise-grade conversational AI platform that:

1. **Classifies User Intent** - Distinguishes between greetings, travel planning, and off-topic conversations
2. **Collects Requirements Intelligently** - Gathers travel details through natural conversation using CrewAI agents
3. **Validates Security** - Uses OpenAI Moderation API to ensure safe inputs/outputs
4. **Manages Sessions** - Maintains conversation state across interactions using S3 storage
5. **Generates Travel Plans** - Creates comprehensive, structured travel itineraries (extensible to downstream retrieval and planning agents)

### Use Cases

- **Travel Agencies**: Automate initial customer consultation and requirements gathering
- **Tourism Boards**: Provide personalized destination recommendations
- **Corporate Travel**: Streamline business trip planning processes
- **Personal Travel**: Help individuals plan sustainable vacations

---

## 🏗️ Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Gateway                              │
│                    (HTTP API - FastAPI)                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
    ┌────────────┴─────────────┬──────────────────────┐
    │                          │                      │
    ▼                          ▼                      ▼
┌─────────────────┐   ┌──────────────────┐   ┌────────────────┐
│  Intent Service │   │ Shared Services  │   │  S3 Storage    │
│  (CrewAI)       │   │  (OpenAI Mod)    │   │  (Sessions)    │
└─────────────────┘   └──────────────────┘   └────────────────┘
         │                     │                       │
         │                     │                       │
         └─────────────────────┴───────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  CloudWatch Logs    │
                    └─────────────────────┘
```

### Microservices

#### 1. **API Gateway Service** (`api-gateway/`)
- **Role**: Entry point for all requests
- **Features**:
  - Orchestrates workflow between services
  - Manages session lifecycle
  - Handles error propagation
  - Integrates with downstream planning agents

#### 2. **Intent & Requirements Service** (`intent-requirements-service/`)
- **Role**: Classifies intent and gathers travel requirements
- **Features**:
  - Binary intent classification (greeting/planning/other)
  - Intelligent requirements collection using CrewAI agents
  - Natural language understanding with GPT-4
  - Context-aware conversation management
  - Adaptive questioning strategy

#### 3. **Shared Services** (`shared-services/`)
- **Role**: Security validation and session management
- **Features**:
  - Input/output security validation
  - OpenAI Moderation API integration
  - Prompt injection detection
  - Session CRUD operations
  - S3-based persistence
- **Technology**: FastAPI + OpenAI Moderation API

### Data Flow

```
User Input → API Gateway → Security Validation (Input) 
          ↓
    Intent Classification
          ↓
    Requirements Gathering (CrewAI Agent)
          ↓
    Security Validation (Output)
          ↓
    Session Update (S3)
          ↓
    Response to User
```

---

## 🛠️ Technology Stack

### Backend
- **Python 3.11** - Core programming language
- **FastAPI** - High-performance web framework
- **CrewAI** - Multi-agent orchestration framework
- **LangChain** - LLM application framework
- **OpenAI GPT-4** - Large language model

### AI/ML
- **OpenAI API** - GPT-4 for intent and requirements
- **OpenAI Moderation API** - Content safety validation
- **LangChain OpenAI** - LLM integrations

### Infrastructure
- **AWS Lambda** - Serverless compute
- **Amazon S3** - Session and state storage
- **AWS SAM** - Infrastructure as Code
- **Amazon API Gateway (HTTP API)** - API management
- **Amazon CloudWatch** - Logging and monitoring

### Development Tools
- **Docker** - Containerization
- **Pytest** - Testing framework
- **Boto3** - AWS SDK for Python
- **Mangum** - AWS Lambda adapter for ASGI applications

---

## 📦 Prerequisites

### Required Software

1. **AWS SAM CLI** (v1.100 or higher)
   ```bash
   
   # Install on Linux
   pip install aws-sam-cli
   
   # Verify
   sam --version
   ```

2. **Docker** (v20.x or higher)
   ```bash
   
   # Install on Linux
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   
   # Verify
   docker --version
   docker ps  # Ensure Docker daemon is running
   ```

3. **Python 3.11+**
   ```bash
   python3 --version
   ```

4. **jq** (for JSON parsing in scripts)
   ```bash
   sudo apt-get install jq  # Linux
   ```

### AWS Account Setup

1. **Create AWS Account** (if you don't have one)
2. **Configure AWS Credentials**:
   ```bash
   aws configure
   # AWS Access Key ID: [Your Access Key]
   # AWS Secret Access Key: [Your Secret Key]
   # Default region name: ap-southeast-1
   # Default output format: json
   ```

3. **Verify AWS Configuration**:
   ```bash
   aws sts get-caller-identity
   ```

### API Keys

1. **OpenAI API Key** (required)
   - Sign up at [OpenAI Platform](https://platform.openai.com/)
   - Generate API key from [API Keys page](https://platform.openai.com/api-keys)
   - Ensure your account has access to GPT-4 models

---

## ☁️ AWS Deployment

### Quick Deployment

```bash
# Set environment variables
export OPENAI_KEY="sk-your-openai-api-key"
export AWS_PROFILE="default"  # Your AWS profile
export AWS_REGION="ap-southeast-1"
export STACK_NAME="intent-agent-stack-prod"

# Run deployment script
chmod +x deploy.sh
./deploy.sh
```

### What the Deployment Script Does

The `deploy.sh` script automates:

1. ✅ **Validates prerequisites** (AWS SAM, Docker, AWS CLI)
2. 🧹 **Cleans previous builds** (removes `.aws-sam` directory)
3. 🗑️ **Handles stuck stacks** (deletes ROLLBACK_COMPLETE stacks)
4. 🏗️ **Builds container images** (3 Lambda functions)
5. ✔️ **Validates build output** (checks for reserved environment variables)
6. 🚀 **Deploys to AWS** (creates CloudFormation stack)
7. 🔥 **Warms up functions** (sends health check requests)

**Deployment takes approximately 10-15 minutes**.

### Post-Deployment

After successful deployment, you'll see:

```
🌐 API Gateway URL:
   https://xxxxxxxxxx.execute-api.ap-southeast-1.amazonaws.com

📦 S3 Bucket:
   iss-travel-planner

🧪 Test Commands:
   curl https://xxxxxxxxxx.execute-api.ap-southeast-1.amazonaws.com/health | jq
```

---

## 🧪 Testing

### Run Unit Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-mock pytest-env httpx fastapi python-dotenv responses moto faker
pip install starlette==0.27.0 httpx==0.24.1

export OPENAI_API_KEY="test-key-12345"
export USE_S3="false"
export GUARDRAILS_ENABLED="false"
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run all tests
pytest tests/test_api_gateway.py -v
pytest tests/test_intent_classification.py -v
pytest tests/test_requirements_gathering.py -v
pytest tests/test_security.py -v
pytest tests/test_session_management.py -v
```

---

## 🔒 Security

### Security Features

1. **OpenAI Moderation API**
   - Blocks harmful, offensive, or inappropriate content
   - Validates both user inputs and AI outputs

2. **Prompt Injection Detection**
   - Detects and blocks malicious prompt manipulation
   - Pattern matching for common injection techniques
   - Fallback to local validation on API failure

3. **Input Sanitization**
   - Removes potentially harmful content
   - Validates data types and formats
   - Enforces length limits

4. **Output Filtering**
   - Prevents sensitive data leakage
   - Blocks inappropriate assistant responses
   - Trust scoring mechanism

---

## 📊 Monitoring & Debugging

### CloudWatch Logs

Each Lambda function has its own log group:

```bash
# API Gateway logs
/aws/lambda/stp-api-gateway-prod

# Intent Service logs
/aws/lambda/intent-requirements-prod

# Shared Services logs
/aws/lambda/shared-functions-prod
```

### Viewing Logs

**Using AWS Console:**
1. Go to CloudWatch → Log Groups
2. Select log group
3. Filter by request ID or search term

---

## 🗑️ Cleanup

### Delete AWS Resources

Use the interactive cleanup script:

```bash
chmod +x cleanup-aws-interactive.sh
./cleanup-aws-interactive.sh
```

**The script will:**
1. Scan for CloudFormation stacks
2. Find S3 buckets
3. List Lambda functions
4. Show API Gateways
5. Find ECR repositories
6. List CloudWatch Log Groups
7. **Prompt for confirmation before deletion**
---

<div align="center">

**Built with ❤️ by [Ashiwin Rajendran/Architecting AI Systems - NUS]**

</div>