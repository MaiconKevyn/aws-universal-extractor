pipeline {
    agent any

    options {
        disableConcurrentBuilds()
    }

    parameters {
        string(name: 'AWS_REGION', defaultValue: 'sa-east-1', description: 'AWS region for the deployment')
        string(name: 'STACK_NAME', defaultValue: 'universal-extractor-dev', description: 'CloudFormation stack name')
        string(name: 'APP_STAGE', defaultValue: 'dev', description: 'Template parameter StageName')
        string(name: 'DOCUMENTS_BUCKET_NAME', defaultValue: '', description: 'Optional documents bucket name. Leave blank to use payroll-<stage>-<account>-<region>')
        string(name: 'OPENAI_API_KEY_SECRET_ARN', defaultValue: '', description: 'Secrets Manager ARN containing the OpenAI API key')
        string(name: 'OPENAI_MODEL', defaultValue: 'gpt-4.1-mini', description: 'Template parameter OpenAIModel')
        string(name: 'SAM_S3_BUCKET', defaultValue: '', description: 'Optional S3 bucket for SAM artifacts. Leave blank to use --resolve-s3')
        booleanParam(name: 'DEPLOY_ENABLED', defaultValue: true, description: 'If disabled, the job stops after validate/build')
        booleanParam(name: 'SYNC_PAYROLL_FIXTURES', defaultValue: true, description: 'Upload tests/fixtures/payroll/{pdf,xlsx,csv,docx} to datasets/fixtures/payroll/ in the deployed documents bucket after deploy')
    }

    environment {
        AWS_DEFAULT_REGION = "${params.AWS_REGION}"
        SAM_CLI_TELEMETRY = '0'
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
        PYTHONUNBUFFERED = '1'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Preflight') {
            steps {
                sh '''
                    set -eu
                    command -v python3.13 >/dev/null 2>&1
                    test -f template.yml
                '''
            }
        }

        stage('Prepare Python') {
            steps {
                sh '''
                    set -eux
                    python3.13 -m venv .venv
                    ./.venv/bin/python -m pip install --upgrade pip
                    ./.venv/bin/pip install -r requirements.txt awscli aws-sam-cli
                    rm -rf .aws-sam/runtime-deps
                    mkdir -p .aws-sam/runtime-deps
                    ./.venv/bin/pip install -r requirements.txt -t .aws-sam/runtime-deps --upgrade --no-compile
                    ./.venv/bin/python --version
                    ./.venv/bin/aws --version
                    ./.venv/bin/sam --version
                '''
            }
        }

        stage('Resolve AWS Identity') {
            steps {
                sh '''
                    set -eux
                    ./.venv/bin/aws sts get-caller-identity
                '''
            }
        }

        stage('Validate') {
            steps {
                sh '''
                    set -eux
                    ./.venv/bin/sam validate --template-file template.yml --region "$AWS_DEFAULT_REGION"
                '''
            }
        }

        stage('Build') {
            steps {
                sh '''
                    set -eux
                    ./.venv/bin/sam build --template-file template.yml
                '''
            }
        }

        stage('Deploy') {
            when {
                expression { params.DEPLOY_ENABLED }
            }
            steps {
                sh '''
                    set -eux

                    stack_name="${STACK_NAME:-universal-extractor-dev}"
                    deploy_stage="${APP_STAGE:-${STAGE_NAME:-dev}}"
                    documents_bucket_name="${DOCUMENTS_BUCKET_NAME:-}"
                    openai_model="${OPENAI_MODEL:-gpt-4.1-mini}"
                    openai_secret_arn="${OPENAI_API_KEY_SECRET_ARN:-}"
                    sam_s3_bucket="${SAM_S3_BUCKET:-}"

                    if [ -z "$openai_secret_arn" ]; then
                      echo "OPENAI_API_KEY_SECRET_ARN is required for deploy."
                      exit 1
                    fi

                    case "$openai_secret_arn" in
                      arn:aws:secretsmanager:*)
                        ;;
                      *)
                        echo "OPENAI_API_KEY_SECRET_ARN must be a valid Secrets Manager ARN."
                        exit 1
                        ;;
                    esac

                    set -- ./.venv/bin/sam deploy \
                      --template-file .aws-sam/build/template.yaml \
                      --stack-name "$stack_name" \
                      --region "$AWS_DEFAULT_REGION" \
                      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
                      --no-fail-on-empty-changeset \
                      --parameter-overrides \
                        StageName="$deploy_stage" \
                        OpenAIApiKeySecretArn="$openai_secret_arn" \
                        OpenAIModel="$openai_model"

                    if [ -n "$documents_bucket_name" ]; then
                      set -- "$@" DocumentsBucketName="$documents_bucket_name"
                    fi

                    if [ -n "$sam_s3_bucket" ]; then
                      set -- "$@" --s3-bucket "$sam_s3_bucket"
                    else
                      set -- "$@" --resolve-s3
                    fi

                    "$@"
                '''
            }
        }

        stage('Sync Payroll Fixtures') {
            when {
                allOf {
                    expression { params.DEPLOY_ENABLED }
                    expression { params.SYNC_PAYROLL_FIXTURES == null || params.SYNC_PAYROLL_FIXTURES }
                }
            }
            steps {
                sh '''
                    set -eux

                    stack_name="${STACK_NAME:-universal-extractor-dev}"
                    bucket_name="$(./.venv/bin/aws cloudformation describe-stacks \
                      --stack-name "$stack_name" \
                      --region "$AWS_DEFAULT_REGION" \
                      --query "Stacks[0].Outputs[?OutputKey=='DocumentsBucketName'].OutputValue | [0]" \
                      --output text)"

                    if [ -z "$bucket_name" ] || [ "$bucket_name" = "None" ]; then
                      echo "Could not resolve DocumentsBucketName from CloudFormation outputs."
                      exit 1
                    fi

                    ./.venv/bin/aws s3 sync tests/fixtures/payroll "s3://$bucket_name/datasets/fixtures/payroll/" \
                      --region "$AWS_DEFAULT_REGION" \
                      --exclude "*" \
                      --include "*.pdf" \
                      --include "*.xlsx" \
                      --include "*.csv" \
                      --include "*.docx"
                '''
            }
        }
    }
}
