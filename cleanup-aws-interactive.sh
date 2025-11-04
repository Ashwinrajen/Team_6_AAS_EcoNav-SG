#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

REGION="ap-southeast-1"

# Helper function to ask yes/no
ask_confirmation() {
    local prompt="$1"
    local response
    while true; do
        read -p "$prompt (y/n): " response
        case $response in
            [Yy]* ) return 0;;
            [Nn]* ) return 1;;
            * ) echo "Please answer y or n.";;
        esac
    done
}

# Helper function to print section headers
print_header() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  $1${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Helper function to print resource counts
print_resource_info() {
    local resource_type="$1"
    local count="$2"
    if [ "$count" -eq 0 ]; then
        echo -e "${YELLOW}  ℹ️  No $resource_type found${NC}"
    else
        echo -e "${GREEN}  📦 Found $count $resource_type${NC}"
    fi
}

# ============================================================================
# MAIN SCRIPT START
# ============================================================================

clear
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                                                               ║${NC}"
echo -e "${CYAN}║      AWS INTERACTIVE CLEANUP SCRIPT - TRAVEL PLANNER         ║${NC}"
echo -e "${CYAN}║                                                               ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}This script will help you safely delete AWS resources.${NC}"
echo -e "${YELLOW}You'll be asked to confirm each deletion step.${NC}"
echo ""
echo -e "${BLUE}Region: ${YELLOW}$REGION${NC}"
echo ""

if ! ask_confirmation "Do you want to continue with the cleanup scan?"; then
    echo "Cleanup cancelled."
    exit 0
fi

# ============================================================================
# STEP 1: SCAN AND LIST ALL RESOURCES
# ============================================================================

print_header "STEP 1: SCANNING FOR AWS RESOURCES"

echo -e "${CYAN}Scanning for CloudFormation stacks...${NC}"
STACKS=$(aws cloudformation list-stacks \
    --region "$REGION" \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE UPDATE_ROLLBACK_COMPLETE \
    --query 'StackSummaries[?contains(StackName, `travel-planner`)].{Name:StackName, Status:StackStatus, Created:CreationTime}' \
    --output json 2>/dev/null)
STACK_COUNT=$(echo "$STACKS" | jq -r '. | length')

echo -e "${CYAN}Scanning for S3 buckets...${NC}"
BUCKETS=$(aws s3api list-buckets \
    --region "$REGION" \
    --query 'Buckets[?contains(Name, `stp-req`)].{Name:Name, Created:CreationDate}' \
    --output json 2>/dev/null)
BUCKET_COUNT=$(echo "$BUCKETS" | jq -r '. | length')

echo -e "${CYAN}Scanning for Lambda functions...${NC}"
FUNCTIONS=$(aws lambda list-functions \
    --region "$REGION" \
    --query 'Functions[?contains(FunctionName, `travel-planner`) || contains(FunctionName, `stp-`) || contains(FunctionName, `shared-services`) || contains(FunctionName, `intent-requirements`)].{Name:FunctionName, Runtime:Runtime, Memory:MemorySize}' \
    --output json 2>/dev/null)
FUNCTION_COUNT=$(echo "$FUNCTIONS" | jq -r '. | length')

echo -e "${CYAN}Scanning for API Gateways...${NC}"
APIS=$(aws apigatewayv2 get-apis \
    --region "$REGION" \
    --query 'Items[?contains(Name, `travel`)].{Name:Name, ApiId:ApiId, Protocol:ProtocolType}' \
    --output json 2>/dev/null)
API_COUNT=$(echo "$APIS" | jq -r '. | length')

echo -e "${CYAN}Scanning for ECR repositories...${NC}"
ECR_REPOS=$(aws ecr describe-repositories \
    --region "$REGION" \
    --query 'repositories[?contains(repositoryName, `travelplannerstack`)].{Name:repositoryName, URI:repositoryUri, Created:createdAt}' \
    --output json 2>/dev/null)
ECR_COUNT=$(echo "$ECR_REPOS" | jq -r '. | length')

echo -e "${CYAN}Scanning for CloudWatch Log Groups...${NC}"
LOG_GROUPS=$(aws logs describe-log-groups \
    --region "$REGION" \
    --query 'logGroups[?contains(logGroupName, `travel-planner-stack`)].{Name:logGroupName, Size:storedBytes, Created:creationTime}' \
    --output json 2>/dev/null)
LOG_GROUP_COUNT=$(echo "$LOG_GROUPS" | jq -r '. | length')

# Display summary
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                    RESOURCE SUMMARY                            ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
print_resource_info "CloudFormation Stack(s)" "$STACK_COUNT"
print_resource_info "S3 Bucket(s)" "$BUCKET_COUNT"
print_resource_info "Lambda Function(s)" "$FUNCTION_COUNT"
print_resource_info "API Gateway(s)" "$API_COUNT"
print_resource_info "ECR Repositor(ies)" "$ECR_COUNT"
print_resource_info "CloudWatch Log Group(s)" "$LOG_GROUP_COUNT"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"

TOTAL_RESOURCES=$((STACK_COUNT + BUCKET_COUNT + FUNCTION_COUNT + API_COUNT + ECR_COUNT + LOG_GROUP_COUNT))

if [ "$TOTAL_RESOURCES" -eq 0 ]; then
    echo ""
    echo -e "${YELLOW}✨ No resources found to delete! Your AWS account is clean.${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}⚠️  Total resources found: ${RED}$TOTAL_RESOURCES${NC}"
echo ""

if ! ask_confirmation "Do you want to see detailed information about these resources?"; then
    echo -e "${YELLOW}Skipping detailed view...${NC}"
else
    # Show detailed information
    if [ "$STACK_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}CloudFormation Stacks:${NC}"
        echo "$STACKS" | jq -r '.[] | "  📦 \(.Name)\n     Status: \(.Status)\n     Created: \(.Created)"'
    fi

    if [ "$BUCKET_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}S3 Buckets:${NC}"
        echo "$BUCKETS" | jq -r '.[] | "  🪣 \(.Name)\n     Created: \(.Created)"'
        
        # Show bucket sizes
        for BUCKET in $(echo "$BUCKETS" | jq -r '.[].Name'); do
            OBJECT_COUNT=$(aws s3 ls s3://$BUCKET --recursive --region "$REGION" 2>/dev/null | wc -l || echo "0")
            BUCKET_SIZE=$(aws s3 ls s3://$BUCKET --recursive --region "$REGION" --summarize 2>/dev/null | grep "Total Size" | awk '{print $3}' || echo "0")
            echo -e "     Objects: $OBJECT_COUNT | Size: $BUCKET_SIZE bytes"
        done
    fi

    if [ "$FUNCTION_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}Lambda Functions:${NC}"
        echo "$FUNCTIONS" | jq -r '.[] | "  λ \(.Name)\n     Runtime: \(.Runtime) | Memory: \(.Memory)MB"'
    fi

    if [ "$API_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}API Gateways:${NC}"
        echo "$APIS" | jq -r '.[] | "  🌐 \(.Name)\n     API ID: \(.ApiId) | Protocol: \(.Protocol)"'
    fi

    if [ "$ECR_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}ECR Repositories:${NC}"
        echo "$ECR_REPOS" | jq -r '.[] | "  🐳 \(.Name)\n     URI: \(.URI)"'
        
        # Show image count and sizes
        for REPO in $(echo "$ECR_REPOS" | jq -r '.[].Name'); do
            IMAGE_COUNT=$(aws ecr list-images --repository-name "$REPO" --region "$REGION" --query 'imageIds' --output json 2>/dev/null | jq '. | length' || echo "0")
            echo -e "     Images: $IMAGE_COUNT"
        done
    fi

    if [ "$LOG_GROUP_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}CloudWatch Log Groups:${NC}"
        echo "$LOG_GROUPS" | jq -r '.[] | "  📋 \(.Name)\n     Size: \(.Size) bytes"'
    fi
fi

echo ""
echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}                    ⚠️  WARNING ⚠️                              ${NC}"
echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}Deletion is PERMANENT and CANNOT be undone!${NC}"
echo -e "${RED}All data, configurations, and resources will be lost forever.${NC}"
echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
echo ""

if ! ask_confirmation "${RED}Are you ABSOLUTELY SURE you want to delete ALL these resources?${NC}"; then
    echo -e "${YELLOW}Cleanup cancelled. No resources were deleted.${NC}"
    exit 0
fi

# ============================================================================
# STEP 2: DELETE CLOUDFORMATION STACKS
# ============================================================================

if [ "$STACK_COUNT" -gt 0 ]; then
    print_header "STEP 2: DELETING CLOUDFORMATION STACKS"
    
    if ask_confirmation "Delete $STACK_COUNT CloudFormation stack(s)?"; then
        for STACK_NAME in $(echo "$STACKS" | jq -r '.[].Name'); do
            echo -e "${YELLOW}🗑️  Deleting stack: $STACK_NAME${NC}"
            
            aws cloudformation delete-stack \
                --stack-name "$STACK_NAME" \
                --region "$REGION" 2>/dev/null || {
                echo -e "${RED}❌ Failed to delete stack: $STACK_NAME${NC}"
                continue
            }
            
            echo -e "${CYAN}⏳ Waiting for stack deletion to complete...${NC}"
            echo -e "${CYAN}   (This may take 5-10 minutes)${NC}"
            
            aws cloudformation wait stack-delete-complete \
                --stack-name "$STACK_NAME" \
                --region "$REGION" 2>/dev/null && {
                echo -e "${GREEN}✅ Stack deleted successfully: $STACK_NAME${NC}"
            } || {
                echo -e "${YELLOW}⚠️  Stack deletion in progress or completed: $STACK_NAME${NC}"
            }
        done
    else
        echo -e "${YELLOW}⏭️  Skipping CloudFormation stack deletion${NC}"
    fi
else
    echo -e "${YELLOW}⏭️  No CloudFormation stacks to delete${NC}"
fi

# ============================================================================
# STEP 3: DELETE S3 BUCKETS
# ============================================================================

if [ "$BUCKET_COUNT" -gt 0 ]; then
    print_header "STEP 3: DELETING S3 BUCKETS"
    
    if ask_confirmation "Delete $BUCKET_COUNT S3 bucket(s) and ALL their contents?"; then
        for BUCKET_NAME in $(echo "$BUCKETS" | jq -r '.[].Name'); do
            echo -e "${YELLOW}🗑️  Deleting bucket: $BUCKET_NAME${NC}"
            
            # Get object count
            OBJECT_COUNT=$(aws s3 ls s3://$BUCKET_NAME --recursive --region "$REGION" 2>/dev/null | wc -l || echo "0")
            echo -e "${CYAN}   Found $OBJECT_COUNT object(s) to delete${NC}"
            
            # Empty bucket (delete all objects)
            echo -e "${CYAN}   Emptying bucket...${NC}"
            aws s3 rm s3://$BUCKET_NAME --recursive --region "$REGION" 2>/dev/null || {
                echo -e "${YELLOW}⚠️  Bucket may already be empty${NC}"
            }
            
            # Delete all versions (if versioning is enabled)
            echo -e "${CYAN}   Deleting versions...${NC}"
            aws s3api delete-objects \
                --bucket $BUCKET_NAME \
                --delete "$(aws s3api list-object-versions \
                    --bucket $BUCKET_NAME \
                    --region $REGION \
                    --output json \
                    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}')" \
                --region $REGION 2>/dev/null || {
                echo -e "${YELLOW}⚠️  No versions to delete${NC}"
            }
            
            # Delete all delete markers
            echo -e "${CYAN}   Deleting delete markers...${NC}"
            aws s3api delete-objects \
                --bucket $BUCKET_NAME \
                --delete "$(aws s3api list-object-versions \
                    --bucket $BUCKET_NAME \
                    --region $REGION \
                    --output json \
                    --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}')" \
                --region $REGION 2>/dev/null || {
                echo -e "${YELLOW}⚠️  No delete markers${NC}"
            }
            
            # Delete the bucket itself
            echo -e "${CYAN}   Deleting bucket...${NC}"
            aws s3api delete-bucket \
                --bucket $BUCKET_NAME \
                --region $REGION 2>/dev/null && {
                echo -e "${GREEN}✅ Bucket deleted successfully: $BUCKET_NAME${NC}"
            } || {
                echo -e "${RED}❌ Failed to delete bucket: $BUCKET_NAME${NC}"
                echo -e "${YELLOW}   You may need to empty it manually${NC}"
            }
        done
    else
        echo -e "${YELLOW}⏭️  Skipping S3 bucket deletion${NC}"
    fi
else
    echo -e "${YELLOW}⏭️  No S3 buckets to delete${NC}"
fi

# ============================================================================
# STEP 4: DELETE ECR REPOSITORIES
# ============================================================================

if [ "$ECR_COUNT" -gt 0 ]; then
    print_header "STEP 4: DELETING ECR REPOSITORIES"
    
    if ask_confirmation "Delete $ECR_COUNT ECR repositor(ies) and all Docker images?"; then
        for REPO_NAME in $(echo "$ECR_REPOS" | jq -r '.[].Name'); do
            echo -e "${YELLOW}🗑️  Deleting ECR repository: $REPO_NAME${NC}"
            
            # Get image count
            IMAGE_COUNT=$(aws ecr list-images --repository-name "$REPO_NAME" --region "$REGION" --query 'imageIds' --output json 2>/dev/null | jq '. | length' || echo "0")
            echo -e "${CYAN}   Found $IMAGE_COUNT image(s) to delete${NC}"
            
            aws ecr delete-repository \
                --repository-name "$REPO_NAME" \
                --force \
                --region "$REGION" 2>/dev/null && {
                echo -e "${GREEN}✅ ECR repository deleted: $REPO_NAME${NC}"
            } || {
                echo -e "${RED}❌ Failed to delete ECR repository: $REPO_NAME${NC}"
            }
        done
    else
        echo -e "${YELLOW}⏭️  Skipping ECR repository deletion${NC}"
    fi
else
    echo -e "${YELLOW}⏭️  No ECR repositories to delete${NC}"
fi

# ============================================================================
# STEP 5: DELETE CLOUDWATCH LOG GROUPS
# ============================================================================

if [ "$LOG_GROUP_COUNT" -gt 0 ]; then
    print_header "STEP 5: DELETING CLOUDWATCH LOG GROUPS"
    
    if ask_confirmation "Delete $LOG_GROUP_COUNT CloudWatch log group(s)?"; then
        for LOG_GROUP_NAME in $(echo "$LOG_GROUPS" | jq -r '.[].Name'); do
            echo -e "${YELLOW}🗑️  Deleting log group: $LOG_GROUP_NAME${NC}"
            
            aws logs delete-log-group \
                --log-group-name "$LOG_GROUP_NAME" \
                --region "$REGION" 2>/dev/null && {
                echo -e "${GREEN}✅ Log group deleted: $LOG_GROUP_NAME${NC}"
            } || {
                echo -e "${RED}❌ Failed to delete log group: $LOG_GROUP_NAME${NC}"
            }
        done
    else
        echo -e "${YELLOW}⏭️  Skipping CloudWatch log group deletion${NC}"
    fi
else
    echo -e "${YELLOW}⏭️  No CloudWatch log groups to delete${NC}"
fi

# ============================================================================
# STEP 6: DELETE ORPHANED LAMBDA FUNCTIONS (if any remain)
# ============================================================================

if [ "$FUNCTION_COUNT" -gt 0 ]; then
    print_header "STEP 6: CHECKING FOR ORPHANED LAMBDA FUNCTIONS"
    
    # Re-scan for functions (some may have been deleted with the stack)
    REMAINING_FUNCTIONS=$(aws lambda list-functions \
        --region "$REGION" \
        --query 'Functions[?contains(FunctionName, `travel-planner`) || contains(FunctionName, `stp-`) || contains(FunctionName, `shared-services`) || contains(FunctionName, `intent-requirements`)].FunctionName' \
        --output json 2>/dev/null)
    REMAINING_FUNCTION_COUNT=$(echo "$REMAINING_FUNCTIONS" | jq -r '. | length')
    
    if [ "$REMAINING_FUNCTION_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}Found $REMAINING_FUNCTION_COUNT orphaned Lambda function(s)${NC}"
        
        if ask_confirmation "Delete orphaned Lambda functions?"; then
            for FUNCTION_NAME in $(echo "$REMAINING_FUNCTIONS" | jq -r '.[]'); do
                echo -e "${YELLOW}🗑️  Deleting function: $FUNCTION_NAME${NC}"
                
                aws lambda delete-function \
                    --function-name "$FUNCTION_NAME" \
                    --region "$REGION" 2>/dev/null && {
                    echo -e "${GREEN}✅ Function deleted: $FUNCTION_NAME${NC}"
                } || {
                    echo -e "${RED}❌ Failed to delete function: $FUNCTION_NAME${NC}"
                }
            done
        else
            echo -e "${YELLOW}⏭️  Skipping orphaned Lambda function deletion${NC}"
        fi
    else
        echo -e "${GREEN}✅ No orphaned Lambda functions found${NC}"
    fi
fi

# ============================================================================
# STEP 7: VERIFICATION
# ============================================================================

print_header "STEP 7: VERIFYING CLEANUP"

echo -e "${CYAN}Re-scanning for remaining resources...${NC}"
echo ""

# Re-scan all resources
REMAINING_STACKS=$(aws cloudformation list-stacks \
    --region "$REGION" \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE UPDATE_ROLLBACK_COMPLETE \
    --query 'StackSummaries[?contains(StackName, `travel-planner`)].StackName' \
    --output json 2>/dev/null | jq -r '. | length')

REMAINING_BUCKETS=$(aws s3api list-buckets \
    --region "$REGION" \
    --query 'Buckets[?contains(Name, `stp-state`)].Name' \
    --output json 2>/dev/null | jq -r '. | length')

REMAINING_FUNCTIONS=$(aws lambda list-functions \
    --region "$REGION" \
    --query 'Functions[?contains(FunctionName, `travel-planner`) || contains(FunctionName, `stp-`) || contains(FunctionName, `shared-services`) || contains(FunctionName, `intent-requirements`)].FunctionName' \
    --output json 2>/dev/null | jq -r '. | length')

REMAINING_APIS=$(aws apigatewayv2 get-apis \
    --region "$REGION" \
    --query 'Items[?contains(Name, `travel`)].ApiId' \
    --output json 2>/dev/null | jq -r '. | length')

REMAINING_ECR=$(aws ecr describe-repositories \
    --region "$REGION" \
    --query 'repositories[?contains(repositoryName, `travel-planner-stack`)].repositoryName' \
    --output json 2>/dev/null | jq -r '. | length')

REMAINING_LOGS=$(aws logs describe-log-groups \
    --region "$REGION" \
    --query 'logGroups[?contains(logGroupName, `travel-planner-stack`)].logGroupName' \
    --output json 2>/dev/null | jq -r '. | length')

REMAINING_TOTAL=$((REMAINING_STACKS + REMAINING_BUCKETS + REMAINING_FUNCTIONS + REMAINING_APIS + REMAINING_ECR + REMAINING_LOGS))

echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                  VERIFICATION RESULTS                          ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "  CloudFormation Stacks:    $REMAINING_STACKS"
echo -e "  S3 Buckets:               $REMAINING_BUCKETS"
echo -e "  Lambda Functions:         $REMAINING_FUNCTIONS"
echo -e "  API Gateways:             $REMAINING_APIS"
echo -e "  ECR Repositories:         $REMAINING_ECR"
echo -e "  CloudWatch Log Groups:    $REMAINING_LOGS"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "  ${YELLOW}Total Remaining Resources: $REMAINING_TOTAL${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$REMAINING_TOTAL" -eq 0 ]; then
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                               ║${NC}"
    echo -e "${GREEN}║  ✅  CLEANUP COMPLETE - ALL RESOURCES DELETED SUCCESSFULLY   ║${NC}"
    echo -e "${GREEN}║                                                               ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}🎉 Your AWS account is now clean!${NC}"
    echo ""
    echo -e "${CYAN}💰 Cost Impact:${NC}"
    echo -e "   • No more charges for Lambda, API Gateway, or S3 storage"
    echo -e "   • CloudWatch logs will stop accumulating"
    echo -e "   • ECR image storage costs eliminated"
    echo ""
    echo -e "${CYAN}📊 Next Steps:${NC}"
    echo -e "   1. Check AWS Billing Dashboard in 24-48 hours to confirm $0 charges"
    echo -e "   2. Review CloudWatch Insights for any orphaned log groups"
    echo -e "   3. Check for any SAM-created buckets: aws s3 ls | grep sam"
    echo ""
else
    echo -e "${YELLOW}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║                                                               ║${NC}"
    echo -e "${YELLOW}║  ⚠️  CLEANUP INCOMPLETE - SOME RESOURCES REMAIN              ║${NC}"
    echo -e "${YELLOW}║                                                               ║${NC}"
    echo -e "${YELLOW}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}⚠️  $REMAINING_TOTAL resource(s) could not be deleted${NC}"
    echo ""
    
    if [ "$REMAINING_STACKS" -gt 0 ]; then
        echo -e "${CYAN}Remaining CloudFormation Stacks:${NC}"
        aws cloudformation list-stacks \
            --region "$REGION" \
            --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE ROLLBACK_COMPLETE UPDATE_ROLLBACK_COMPLETE \
            --query 'StackSummaries[?contains(StackName, `travel-planner`)].{Name:StackName, Status:StackStatus}' \
            --output table
    fi
    
    if [ "$REMAINING_BUCKETS" -gt 0 ]; then
        echo -e "${CYAN}Remaining S3 Buckets:${NC}"
        aws s3api list-buckets \
            --region "$REGION" \
            --query 'Buckets[?contains(Name, `stp-state`)].Name' \
            --output table
    fi
    
    if [ "$REMAINING_FUNCTIONS" -gt 0 ]; then
        echo -e "${CYAN}Remaining Lambda Functions:${NC}"
        aws lambda list-functions \
            --region "$REGION" \
            --query 'Functions[?contains(FunctionName, `travel-planner`) || contains(FunctionName, `stp-`) || contains(FunctionName, `shared-services`) || contains(FunctionName, `intent-requirements`)].FunctionName' \
            --output table
    fi
    
    echo ""
    echo -e "${CYAN}💡 Manual Cleanup Commands:${NC}"
    echo ""
    
    if [ "$REMAINING_STACKS" -gt 0 ]; then
        echo -e "${YELLOW}# Delete CloudFormation Stack:${NC}"
        echo "aws cloudformation delete-stack --stack-name <STACK_NAME> --region $REGION"
        echo ""
    fi
    
    if [ "$REMAINING_BUCKETS" -gt 0 ]; then
        echo -e "${YELLOW}# Force delete S3 Bucket:${NC}"
        echo "aws s3 rb s3://<BUCKET_NAME> --force --region $REGION"
        echo ""
    fi
    
    if [ "$REMAINING_FUNCTIONS" -gt 0 ]; then
        echo -e "${YELLOW}# Delete Lambda Function:${NC}"
        echo "aws lambda delete-function --function-name <FUNCTION_NAME> --region $REGION"
        echo ""
    fi
    
    echo -e "${CYAN}Or re-run this script to try again.${NC}"
fi

echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}Additional Verification Commands:${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}# List all CloudFormation stacks:${NC}"
echo "aws cloudformation list-stacks --region $REGION --output table"
echo ""
echo -e "${YELLOW}# List all S3 buckets:${NC}"
echo "aws s3 ls --region $REGION"
echo ""
echo -e "${YELLOW}# List all Lambda functions:${NC}"
echo "aws lambda list-functions --region $REGION --output table"
echo ""
echo -e "${YELLOW}# Check today's AWS costs:${NC}"
echo "aws ce get-cost-and-usage --time-period Start=\$(date +%Y-%m-%d),End=\$(date +%Y-%m-%d) --granularity DAILY --metrics BlendedCost --region $REGION"
echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}✨ Cleanup script completed!${NC}"
echo ""