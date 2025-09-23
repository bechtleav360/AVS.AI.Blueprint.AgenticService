# Deployment Guide

This guide provides comprehensive instructions for deploying the Agents Blueprint in local development and production environments using Docker Compose and ArgoCD with OpenShift.

## 🎯 Deployment Overview

The Agents Blueprint supports two primary deployment strategies:

- **🚀 Local Development**: Docker Compose for rapid development and testing
- **🌐 Production**: Build pipeline with ArgoCD and OpenShift for automated, GitOps-driven deployments

## 🐳 Local Development with Docker Compose

### Prerequisites

Ensure you have the following installed:
- **Docker** (v20.10+)
- **Docker Compose** (v2.0+)
- **Git** for version control

### Quick Start

1. **Clone the repository**
```bash
git clone <repository-url>
cd agents-blueprint
```

2. **Start all services**
```bash
# Start in detached mode
docker-compose up -d

# View real-time logs
docker-compose logs -f

# Stop all services
docker-compose down
```

3. **Access the application**
- **API Service**: http://localhost:8000
- **Health Check**: http://localhost:8000/actuators/health
- **API Documentation**: http://localhost:8000/docs

### Development Workflow

#### Making Code Changes
```bash
# Rebuild specific service after code changes
docker-compose build asset-backup-checker
docker-compose up -d asset-backup-checker

# Or rebuild all services
docker-compose up --build -d
```

#### Debugging and Troubleshooting
```bash
# View logs for specific service
docker-compose logs asset-backup-checker

# Execute commands inside container
docker-compose exec asset-backup-checker bash

# Check environment variables
docker-compose exec asset-backup-checker env | grep -E "(APP_|DATA_GATEWAY_|RABBITMQ_|AI_)"

# Validate configuration
docker-compose exec asset-backup-checker python -c "from src.config import validate_configuration; validate_configuration()"
```

#### Database Operations
```bash
# Access database container
docker-compose exec postgres bash

# Run database migrations
docker-compose exec asset-backup-checker alembic upgrade head

# Create database backup
docker-compose exec postgres pg_dump -U asset_user asset_db > backup.sql
```

### Service Architecture

The local development environment includes:

- **asset-backup-checker**: Main application service
- **postgres**: PostgreSQL database for persistence
- **rabbitmq**: Message broker for event processing
- **redis**: Cache and session storage
- **otel-collector**: Observability data collection
- **jaeger**: Distributed tracing
- **prometheus**: Metrics collection
- **grafana**: Monitoring dashboards

### Configuration

#### Environment Variables
```bash
# Application Settings
APP_NAME=asset-backup-checker
APP_PORT=8000
ENV_FOR_DYNACONF=development
LOG_LEVEL=INFO

# Data Gateway
DATA_GATEWAY_BASE_URL=http://host.docker.internal:8080
DATA_GATEWAY_API_KEY=dev-key

# Message Broker
RABBITMQ_CONNECTION_STRING=amqp://guest:guest@rabbitmq:5672/
DAPR_PUBSUB_NAME=rabbitmq-pubsub

# Database
DATABASE_URL=postgresql://asset_user:asset_pass@postgres:5432/asset_db

# AI Configuration
AI_MODEL_PROVIDER=openai
AI_MODEL_NAME=gpt-4
AI_API_KEY=your-dev-api-key

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=asset-backup-checker
```

#### Service Dependencies

```yaml
# docker-compose.yml (excerpt)
services:
  asset-backup-checker:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - rabbitmq
      - redis
    environment:
      - ENV_FOR_DYNACONF=development
    volumes:
      - ./src:/app/src
      - ./tests:/app/tests

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=asset_db
      - POSTGRES_USER=asset_user
      - POSTGRES_PASSWORD=asset_pass
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      - RABBITMQ_DEFAULT_USER=guest
      - RABBITMQ_DEFAULT_PASS=guest
```

## 🌐 Production Deployment with ArgoCD and OpenShift

### Architecture Overview

The production deployment follows a **GitOps** approach using:

- **Build Pipeline**: Automated container image building and testing
- **ArgoCD**: GitOps continuous delivery tool for Kubernetes
- **OpenShift**: Enterprise Kubernetes platform for container orchestration
- **External Services**: Managed databases, message brokers, and monitoring

### Build Pipeline

#### CI/CD Pipeline Stages

1. **Source**: Git repository triggers pipeline on changes
2. **Test**: Run comprehensive test suite
3. **Build**: Create container images
4. **Security**: Scan for vulnerabilities
5. **Deploy**: ArgoCD syncs to production

#### Pipeline Configuration

```yaml
# .pipeline/build-deploy.yaml
stages:
  - name: test
    script:
      - python -m pytest tests/ -v --cov=src
      - python -m pytest tests/ --cov-report=xml

  - name: build
    script:
      - docker build -t ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA} .
      - docker push ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
      - docker tag ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA} ${CI_REGISTRY_IMAGE}:latest
      - docker push ${CI_REGISTRY_IMAGE}:latest

  - name: security
    script:
      - trivy image ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
      - safety check

  - name: deploy
    script:
      - argocd app sync asset-backup-checker
```

### ArgoCD Configuration

#### Application Manifest

```yaml
# argo-cd/application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: asset-backup-checker
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/agents-blueprint
    targetRevision: HEAD
    path: k8s/
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
  revisionHistoryLimit: 10
```

#### Kubernetes Resources

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: asset-backup-checker
  labels:
    app: asset-backup-checker
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  selector:
    matchLabels:
      app: asset-backup-checker
  template:
    metadata:
      labels:
        app: asset-backup-checker
    spec:
      containers:
      - name: asset-backup-checker
        image: your-registry/asset-backup-checker:latest
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: ENV_FOR_DYNACONF
          value: "production"
        - name: DATA_GATEWAY_BASE_URL
          valueFrom:
            secretKeyRef:
              name: asset-secrets
              key: data-gateway-url
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          valueFrom:
            configMapKeyRef:
              name: monitoring-config
              key: otel-endpoint
        livenessProbe:
          httpGet:
            path: /actuators/livez
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /actuators/readyz
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

```yaml
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: asset-backup-checker
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
    name: http
  selector:
    app: asset-backup-checker
```

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: monitoring-config
data:
  otel-endpoint: "http://otel-collector.monitoring:4317"
  log-level: "INFO"
```

### OpenShift Integration

#### Routes and Ingress

```yaml
# k8s/route.yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: asset-backup-checker
spec:
  host: asset-backup-checker.apps.openshift-cluster.com
  to:
    kind: Service
    name: asset-backup-checker
  port:
    targetPort: http
  tls:
    termination: edge
```

#### Security Context Constraints

```yaml
# k8s/scc.yaml
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: asset-backup-checker-scc
allowPrivilegedContainer: false
runAsUser:
  type: MustRunAsRange
  uidRangeMin: 1000
  uidRangeMax: 1000
seLinuxContext:
  type: MustRunAs
requiredDropCapabilities:
  - ALL
volumes:
  - configMap
  - secret
```

### Production Configuration

#### External Dependencies

```yaml
# k8s/external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: aws-secret-store
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: asset-secrets
spec:
  secretStoreRef:
    name: aws-secret-store
    kind: SecretStore
  target:
    name: asset-secrets
    creationPolicy: Owner
  data:
  - secretKey: data-gateway-api-key
    remoteRef:
      key: asset-backup-checker/data-gateway
  - secretKey: ai-api-key
    remoteRef:
      key: asset-backup-checker/ai-service
```

#### Monitoring and Observability

```yaml
# k8s/service-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asset-backup-checker
spec:
  selector:
    matchLabels:
      app: asset-backup-checker
  endpoints:
  - port: http
    path: /actuators/metrics
    interval: 30s
```

### Deployment Process

#### 1. Development to Staging
```bash
# Push feature branch
git checkout feature/new-endpoint
git push origin feature/new-endpoint

# Create merge request
# Pipeline runs tests and builds image
# ArgoCD deploys to staging on merge
```

#### 2. Staging Validation
```bash
# Verify deployment
kubectl get pods -l app=asset-backup-checker
kubectl logs -l app=asset-backup-checker --tail=100

# Run integration tests
kubectl exec -it deploy/asset-backup-checker -- python -m pytest tests/integration/

# Validate metrics
curl http://asset-backup-checker/actuators/metrics
```

#### 3. Production Release
```bash
# Merge to main branch
git checkout main
git merge staging
git push origin main

# ArgoCD automatically syncs production
# Monitor deployment status
argocd app get asset-backup-checker
```

### Rollback Strategy

#### Automated Rollback
```bash
# Sync to previous version
argocd app rollback asset-backup-checker <version>

# Or patch deployment
kubectl rollout undo deployment/asset-backup-checker
```

#### Manual Rollback
```yaml
# Update image tag in Git
# k8s/deployment.yaml
image: your-registry/asset-backup-checker:v1.2.3

# Commit and push
git add k8s/deployment.yaml
git commit -m "Rollback to v1.2.3"
git push origin main
```

## 🔒 Security Considerations

### Network Security
- **Service Mesh**: Istio for mTLS between services
- **Network Policies**: Restrict pod-to-pod communication
- **API Gateway**: OpenShift routes for external access

### Secrets Management
- **External Secrets**: AWS Secrets Manager integration
- **Pod Security**: Non-root containers with minimal privileges
- **Image Security**: Multi-stage builds with security scanning

### Access Control
- **RBAC**: Kubernetes role-based access control
- **Service Accounts**: Dedicated service accounts per namespace
- **Audit Logging**: Comprehensive audit trails

## 📊 Monitoring and Alerting

### Key Metrics
- **Request Rate**: HTTP requests per second
- **Error Rate**: 4xx/5xx responses
- **Latency**: P50, P95, P99 response times
- **Resource Usage**: CPU, memory, disk utilization

### Alerting Rules
```yaml
# prometheus/rules.yaml
groups:
- name: asset-backup-checker
  rules:
  - alert: HighErrorRate
    expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High error rate detected"
```

### Dashboards
- **Grafana**: Pre-built dashboards for application metrics
- **OpenShift Console**: Built-in monitoring and alerting
- **Jaeger**: Distributed tracing visualization

## 🛠️ Troubleshooting

### Common Issues

#### Local Development
```bash
# Port conflicts
docker-compose down
sudo lsof -ti:8000 | xargs kill -9
docker-compose up -d

# Database connection issues
docker-compose logs postgres
docker-compose exec postgres psql -U asset_user -d asset_db

# Service dependencies
docker-compose ps
docker-compose restart rabbitmq
```

#### Production Issues
```bash
# Check pod status
kubectl get pods -l app=asset-backup-checker

# View pod logs
kubectl logs -l app=asset-backup-checker --tail=100

# Debug specific pod
kubectl describe pod <pod-name>
kubectl exec -it <pod-name> -- bash
```

### Debug Commands
```bash
# ArgoCD status
argocd app get asset-backup-checker

# Kubernetes events
kubectl get events --sort-by=.metadata.creationTimestamp

# Resource usage
kubectl top pods -l app=asset-backup-checker

# Network policies
kubectl get networkpolicies
```

## 📋 Deployment Checklist

### Pre-Deployment
- [ ] All tests pass (unit, integration, e2e)
- [ ] Security scan completed
- [ ] Docker image built and pushed
- [ ] Database migrations ready
- [ ] Environment variables configured

### Local Deployment
- [ ] Docker Compose file updated
- [ ] Environment variables set
- [ ] Services start successfully
- [ ] Health checks pass
- [ ] Integration tests pass

### Production Deployment
- [ ] ArgoCD application synced
- [ ] All pods healthy
- [ ] Services accessible
- [ ] Metrics flowing
- [ ] Alerts configured
- [ ] Rollback plan tested

---

*This deployment guide is maintained by the Platform Team. Last updated: $(date)*
*For troubleshooting, see [troubleshooting.md](troubleshooting.md)*
