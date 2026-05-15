#!/bin/bash

###############################################################################
# Responsible AI Enterprise Ready - AWS Infrastructure Deployment Script
#
# This script automates the deployment of the infrastructure and services
# to AWS using Terragrunt. It follows the recommended deployment order and
# handles all prerequisites.
#
# Usage:
#   ./deploy.sh [init|plan|apply|destroy] [module] [--skip-backend] [--dry-run]
#
# Examples:
#   ./deploy.sh init                    # Initialize all modules
#   ./deploy.sh plan                    # Plan all modules
#   ./deploy.sh apply network           # Apply only network module
#   ./deploy.sh destroy                 # Destroy all resources (reverse order)
#   ./deploy.sh init --skip-backend     # Skip backend setup
#
###############################################################################

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="responsible-ai"
ENVIRONMENT="dev"
AWS_REGION="ap-southeast-1"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INFRA_DIR="${SCRIPT_DIR}/infra"
LIVE_DIR="${INFRA_DIR}/live/${ENVIRONMENT}"

# Deployment order (dependencies)
DEPLOYMENT_ORDER=(
    "network"
    "secrets"
    "cognito"
    "aurora-postgres"
    "ecr"
    "ecs-ai-gateway"
    "api-gateway"
    "frontend-s3-cloudfront"
    "observability"
)

# Reverse deployment order for destroy
DESTROY_ORDER=(
    "observability"
    "frontend-s3-cloudfront"
    "api-gateway"
    "ecs-ai-gateway"
    "ecr"
    "aurora-postgres"
    "cognito"
    "secrets"
    "network"
)

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if Terragrunt is installed
    if ! command -v terragrunt &> /dev/null; then
        log_error "Terragrunt is not installed. Please install it from https://terragrunt.gruntwork.io/docs/getting-started/install/"
        exit 1
    fi
    
    # Check if Terraform is installed
    if ! command -v terraform &> /dev/null; then
        log_error "Terraform is not installed. Please install it from https://www.terraform.io/downloads.html"
        exit 1
    fi
    
    # Check if AWS CLI is installed
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed. Please install it from https://aws.amazon.com/cli/"
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Please run 'aws configure'"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# Setup S3 backend for remote state
setup_backend() {
    log_info "Setting up S3 backend for Terraform remote state..."

    local account_id="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
    local state_bucket="${PROJECT_NAME}-terraform-state-${ENVIRONMENT}-${account_id}"
    local lock_table="${PROJECT_NAME}-terraform-locks-${ENVIRONMENT}"
    
    # Create S3 bucket for state
    if aws s3 ls "s3://${state_bucket}" 2>/dev/null; then
        log_warning "S3 bucket ${state_bucket} already exists"
    else
        log_info "Creating S3 bucket ${state_bucket}..."
        aws s3 mb "s3://${state_bucket}" --region "${AWS_REGION}"
        
        # Enable versioning
        aws s3api put-bucket-versioning \
            --bucket "${state_bucket}" \
            --versioning-configuration Status=Enabled
        
        # Enable encryption
        aws s3api put-bucket-encryption \
            --bucket "${state_bucket}" \
            --server-side-encryption-configuration '{
                "Rules": [{
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256"
                    }
                }]
            }'
        
        log_success "S3 bucket created"
    fi
    
    # Create DynamoDB table for state locking
    if aws dynamodb describe-table --table-name "${lock_table}" --region "${AWS_REGION}" 2>/dev/null; then
        log_warning "DynamoDB table ${lock_table} already exists"
    else
        log_info "Creating DynamoDB table ${lock_table}..."
        aws dynamodb create-table \
            --table-name "${lock_table}" \
            --attribute-definitions AttributeName=LockID,AttributeType=S \
            --key-schema AttributeName=LockID,KeyType=HASH \
            --billing-mode PAY_PER_REQUEST \
            --region "${AWS_REGION}"
        
        log_success "DynamoDB table created"
    fi
}

# Initialize Terragrunt modules
init_modules() {
    local modules=("$@")
    
    log_info "Initializing Terragrunt modules..."
    
    for module in "${modules[@]}"; do
        log_info "Initializing module: ${module}"
        cd "${LIVE_DIR}/${module}"
        
        if terragrunt init; then
            log_success "Module ${module} initialized"
        else
            log_error "Failed to initialize module ${module}"
            exit 1
        fi
    done
}

# Plan Terragrunt modules
plan_modules() {
    local modules=("$@")
    
    log_info "Planning Terragrunt modules..."
    
    for module in "${modules[@]}"; do
        log_info "Planning module: ${module}"
        cd "${LIVE_DIR}/${module}"
        
        if terragrunt plan -out="${module}.tfplan"; then
            log_success "Plan for module ${module} completed"
        else
            log_error "Failed to plan module ${module}"
            exit 1
        fi
    done
}

# Apply Terragrunt modules
apply_modules() {
    local modules=("$@")
    local auto_approve="${AUTO_APPROVE:-false}"
    
    log_info "Applying Terragrunt modules..."
    
    for module in "${modules[@]}"; do
        log_info "Applying module: ${module}"
        cd "${LIVE_DIR}/${module}"
        
        if [ "${auto_approve}" = "true" ]; then
            if terragrunt apply -auto-approve; then
                log_success "Module ${module} applied"
            else
                log_error "Failed to apply module ${module}"
                exit 1
            fi
        else
            if terragrunt apply; then
                log_success "Module ${module} applied"
            else
                log_error "Failed to apply module ${module}"
                exit 1
            fi
        fi
    done
}

# Destroy Terragrunt modules
destroy_modules() {
    local modules=("$@")
    local auto_approve="${AUTO_APPROVE:-false}"
    
    log_warning "Destroying Terragrunt modules in reverse order..."
    
    for module in "${modules[@]}"; do
        log_warning "Destroying module: ${module}"
        cd "${LIVE_DIR}/${module}"
        
        if [ "${auto_approve}" = "true" ]; then
            if terragrunt destroy -auto-approve; then
                log_success "Module ${module} destroyed"
            else
                log_warning "Failed to destroy module ${module}, continuing..."
            fi
        else
            if terragrunt destroy; then
                log_success "Module ${module} destroyed"
            else
                log_warning "Failed to destroy module ${module}, continuing..."
            fi
        fi
    done
}

# Validate configuration
validate_config() {
    log_info "Validating Terragrunt configuration..."
    
    cd "${LIVE_DIR}"
    
    if terragrunt hcl validate; then
        log_success "Configuration is valid"
    else
        log_error "Configuration validation failed"
        exit 1
    fi
}

# Display help
show_help() {
    echo "Usage: $0 [COMMAND] [MODULE] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  init      Initialize Terragrunt modules"
    echo "  plan      Plan infrastructure changes"
    echo "  apply     Apply infrastructure changes"
    echo "  destroy   Destroy infrastructure (CAUTION!)"
    echo "  validate  Validate Terragrunt configuration"
    echo ""
    echo "Modules (optional, defaults to all):"
    for module in "${DEPLOYMENT_ORDER[@]}"; do
        echo "  - ${module}"
    done
    echo ""
    echo "Options:"
    echo "  --skip-backend   Skip S3 backend setup"
    echo "  --auto-approve   Auto-approve apply/destroy (use with caution!)"
    echo ""
    echo "Examples:"
    echo "  $0 init                                    # Initialize all modules"
    echo "  $0 plan network                            # Plan network module only"
    echo "  $0 apply --auto-approve                    # Apply all with auto-approval"
}

# Main script logic
main() {
    local command="${1:-}"
    local module=""
    local skip_backend=false
    local auto_approve=false

    if [[ $# -gt 0 ]]; then
        shift
    fi

    # Parse options
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-backend)
                skip_backend=true
                shift
                ;;
            --auto-approve)
                auto_approve=true
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                if [[ -z "${module}" ]]; then
                    module="$1"
                    shift
                else
                    log_error "Unexpected argument: $1"
                    show_help
                    exit 1
                fi
                ;;
        esac
    done
    
    # Set environment variables
    export AUTO_APPROVE="${auto_approve}"
    export AWS_REGION="${AWS_REGION}"
    
    # Validate command
    if [[ -z "${command}" ]] || [[ "${command}" == "-h" ]] || [[ "${command}" == "--help" ]]; then
        show_help
        exit 0
    fi
    
    # Check prerequisites
    check_prerequisites
    
    # Determine which modules to deploy
    local modules_to_deploy=("${DEPLOYMENT_ORDER[@]}")
    if [[ -n "${module}" ]]; then
        if [[ " ${DEPLOYMENT_ORDER[@]} " =~ " ${module} " ]]; then
            modules_to_deploy=("${module}")
        else
            log_error "Unknown module: ${module}"
            exit 1
        fi
    fi
    
    # Execute command
    case "${command}" in
        init)
            if [ "${skip_backend}" = false ]; then
                setup_backend
            fi
            init_modules "${modules_to_deploy[@]}"
            log_success "Initialization complete"
            ;;
        plan)
            plan_modules "${modules_to_deploy[@]}"
            log_success "Planning complete"
            ;;
        apply)
            apply_modules "${modules_to_deploy[@]}"
            log_success "Application complete"
            ;;
        destroy)
            if [ "${module}" = "" ]; then
                destroy_modules "${DESTROY_ORDER[@]}"
            else
                destroy_modules "${module}"
            fi
            log_success "Destruction complete"
            ;;
        validate)
            validate_config
            ;;
        *)
            log_error "Unknown command: ${command}"
            show_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
