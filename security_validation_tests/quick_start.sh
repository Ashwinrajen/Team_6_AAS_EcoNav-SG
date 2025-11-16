#!/bin/bash
# Quick Start: OpenAI Moderation API Security Validation
# ======================================================

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   OpenAI Moderation API Security Validation - Quick Start     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY not set!"
    echo ""
    echo "Please set your OpenAI API key:"
    echo "  export OPENAI_API_KEY='sk-your-api-key-here'"
    echo ""
    echo "Tests will run in FALLBACK MODE without a valid API key."
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "📋 Test Categories:"
echo "   1. AI Security Testing (Primary)"
echo "      • Prompt injection detection"
echo "      • Harmful content blocking"
echo "      • Safe content validation"
echo ""
echo "   2. Responsible AI"
echo "      • Output validation"
echo "      • Off-topic detection"
echo "      • Edge case handling"
echo ""
echo "   3. Security Practices"
echo "      • Timeout handling"
echo "      • Fallback mechanisms"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Set environment variables
export GUARDRAILS_ENABLED='true'
export GUARDRAILS_TIMEOUT='5'
export AWS_REGION='ap-southeast-1'
export USE_S3='false'

echo "🔧 Environment configured:"
echo "   GUARDRAILS_ENABLED: ${GUARDRAILS_ENABLED}"
echo "   GUARDRAILS_TIMEOUT: ${GUARDRAILS_TIMEOUT}s"
echo ""

# Check for promptfoo
if command -v promptfoo &> /dev/null; then
    echo "✅ promptfoo found"
    echo ""
    echo "Choose test mode:"
    echo "  1) Standalone Python tests (quick, 6 tests)"
    echo "  2) Full promptfoo suite (comprehensive, 28+ tests)"
    echo ""
    read -p "Enter choice (1 or 2): " -n 1 -r
    echo ""
    
    if [[ $REPLY == "2" ]]; then
        echo "🧪 Running full promptfoo test suite..."
        python3 run_security_validation.py --promptfoo
    else
        echo "🔬 Running standalone Python tests..."
        python3 run_security_validation.py
    fi
else
    echo "ℹ️  promptfoo not found (install: npm install -g promptfoo)"
    echo "   Running standalone Python tests..."
    echo ""
    python3 run_security_validation.py
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ Testing complete!"
echo ""
echo "📄 View detailed results:"
echo "   • Check test_results/ directory"
echo "   • Run: promptfoo view (for UI)"
echo ""
