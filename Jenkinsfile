// Jenkinsfile — Declarative Pipeline
// This is the sample pipeline that AutoPatch will monitor and self-heal.
// Place this in the root of the repo Jenkins is building.

pipeline {
    agent any

    environment {
        PYTHON_VERSION = '3.12'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                echo "Branch: ${env.GIT_BRANCH} | Commit: ${env.GIT_COMMIT}"
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'python3 -m venv --clear .venv && .venv/bin/pip install -r requirements.txt'
            }
        }

        stage('Lint') {
            steps {
                sh '.venv/bin/ruff check src/'
            }
        }

        stage('Type Check') {
            steps {
                sh '.venv/bin/mypy src/'
            }
        }

        stage('Test') {
            steps {
                sh '.venv/bin/pytest tests/ --cov=src --cov-report=xml -v --junitxml=test-results.xml'
            }
            post {
                always {
                    junit 'test-results.xml'
                    publishCoverage adapters: [coberturaAdapter('coverage.xml')]
                }
            }
        }
    }

    post {
        failure {
            // Notify AutoPatch agent via webhook on build failure
            script {
                def autopatchUrl = env.AUTOPATCH_WEBHOOK_URL ?: 'http://localhost:8000'
                def token = env.AUTOPATCH_WEBHOOK_TOKEN ?: ''
                try {
                    httpRequest(
                        url: "${autopatchUrl}/webhook/jenkins?token=${token}",
                        httpMode: 'POST',
                        contentType: 'APPLICATION_JSON',
                        requestBody: groovy.json.JsonOutput.toJson([
                            name : env.JOB_NAME,
                            build: [
                                number: env.BUILD_NUMBER.toInteger(),
                                phase : 'FINALIZED',
                                status: 'FAILURE',
                                scm   : [
                                    branch: env.GIT_BRANCH,
                                    url   : env.GIT_URL,
                                ]
                            ]
                        ])
                    )
                } catch (hudson.AbortException e) {
                    echo "AutoPatch webhook notification failed: ${e.message}"
                }
            }
        }
        success {
            echo 'Build succeeded!'
        }
    }
}
