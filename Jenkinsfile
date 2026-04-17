pipeline {
    agent any

    options {
        disableConcurrentBuilds()
    }

    parameters {
        string(name: 'AWS_REGION', defaultValue: 'sa-east-1', description: 'AWS region for the deployment')
        string(name: 'STACK_NAME', defaultValue: 'universal-extractor-dev', description: 'CloudFormation stack name')
        string(name: 'STAGE_NAME', defaultValue: 'dev', description: 'Template parameter StageName')
        string(name: 'OPENAI_API_KEY_SECRET_ARN', defaultValue: '', description: 'Secrets Manager ARN containing the OpenAI API key')
        string(name: 'OPENAI_MODEL', defaultValue: 'gpt-4.1-mini', description: 'Template parameter OpenAIModel')
        string(name: 'SAM_S3_BUCKET', defaultValue: '', description: 'Optional S3 bucket for SAM artifacts. Leave blank to use --resolve-s3')
        booleanParam(name: 'DEPLOY_ENABLED', defaultValue: true, description: 'If disabled, the job stops after validate/build')
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

                    if [ -z "$OPENAI_API_KEY_SECRET_ARN" ]; then
                      echo "OPENAI_API_KEY_SECRET_ARN is required for deploy."
                      exit 1
                    fi

                    set -- ./.venv/bin/sam deploy \
                      --template-file .aws-sam/build/template.yaml \
                      --stack-name "$STACK_NAME" \
                      --region "$AWS_DEFAULT_REGION" \
                      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
                      --no-fail-on-empty-changeset \
                      --parameter-overrides \
                        StageName="$STAGE_NAME" \
                        OpenAIApiKeySecretArn="$OPENAI_API_KEY_SECRET_ARN" \
                        OpenAIModel="$OPENAI_MODEL"

                    if [ -n "$SAM_S3_BUCKET" ]; then
                      set -- "$@" --s3-bucket "$SAM_S3_BUCKET"
                    else
                      set -- "$@" --resolve-s3
                    fi

                    "$@"
                '''
            }
        }
    }
}
