# Deployment Guide

Deploy your agent service to production.

---

## Prerequisites

- Docker installed
- Kubernetes cluster (for K8s deployment)
- Container registry (Docker Hub, ECR, GCR, etc.)

---

## Docker Deployment

### Step 1: Create Dockerfile

**File:** `Dockerfile`

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 2: Create .dockerignore

**File:** `.dockerignore`

```
__pycache__
*.pyc
.pytest_cache
.venv
.env
.git
.gitignore
README.md
docs/
tests/
```

### Step 3: Build Image

```bash
docker build -t my-agent-service:latest .
```

### Step 4: Run Container

```bash
docker run -p 8000:8000 \
  -e OPENAI_API_KEY="sk-..." \
  -e DAPR_HTTP_PORT=3500 \
  my-agent-service:latest
```

### Step 5: Push to Registry

```bash
# Tag image
docker tag my-agent-service:latest myregistry/my-agent-service:latest

# Push to registry
docker push myregistry/my-agent-service:latest
```

---

## Kubernetes Deployment

### Step 1: Create Namespace

```bash
kubectl create namespace agents
```

### Step 2: Create ConfigMap for Settings

**File:** `k8s/configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-config
  namespace: agents
data:
  settings.toml: |
    [default]
    app_name = "my-agent-service"
    log_level = "INFO"

    [default.ai.default]
    provider = "openai"
    model_name = "gpt-4-mini"
```

### Step 3: Create Secret for API Keys

```bash
kubectl create secret generic agent-secrets \
  --from-literal=openai-api-key="sk-..." \
  -n agents
```

### Step 4: Create Deployment

**File:** `k8s/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-service
  namespace: agents
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agent-service
  template:
    metadata:
      labels:
        app: agent-service
      annotations:
        dapr.io/enabled: "true"
        dapr.io/app-id: "agent-service"
        dapr.io/app-port: "8000"
    spec:
      containers:
      - name: agent
        image: myregistry/my-agent-service:latest
        ports:
        - containerPort: 8000
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: agent-secrets
              key: openai-api-key
        - name: LOG_LEVEL
          value: "INFO"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

### Step 5: Create Service

**File:** `k8s/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: agent-service
  namespace: agents
spec:
  selector:
    app: agent-service
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

### Step 6: Deploy to Kubernetes

```bash
# Apply configurations
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# Check deployment status
kubectl get deployments -n agents
kubectl get pods -n agents
kubectl get svc -n agents
```

### Step 7: Monitor Deployment

```bash
# View logs
kubectl logs -f deployment/agent-service -n agents

# Check pod status
kubectl describe pod <pod-name> -n agents

# Port forward for local testing
kubectl port-forward svc/agent-service 8000:80 -n agents
```

---

## Environment Variables

### Required for Production

```bash
OPENAI_API_KEY=sk-...
LOG_LEVEL=INFO
```

### Optional

```bash
DAPR_HTTP_PORT=3500
DAPR_GRPC_PORT=50001
```

---

## Health Checks

### Liveness Probe

Checks if service is running:

```bash
curl http://localhost:8000/health
```

### Readiness Probe

Checks if service is ready to accept requests:

```bash
curl http://localhost:8000/health
```

---

## Scaling

### Horizontal Scaling

Increase replicas in Kubernetes:

```yaml
spec:
  replicas: 5  # Increase from 3 to 5
```

### Vertical Scaling

Increase resource limits:

```yaml
resources:
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

---

## Monitoring

### Logs

View application logs:

```bash
# Docker
docker logs <container-id>

# Kubernetes
kubectl logs <pod-name> -n agents
```

### Metrics

Enable metrics in settings:

```toml
[default]
log_level = "DEBUG"  # More detailed logging
```

### Health Endpoint

Monitor service health:

```bash
curl http://localhost:8000/health
```

---

## Troubleshooting Deployment

### Pod Won't Start

```bash
# Check pod status
kubectl describe pod <pod-name> -n agents

# Check logs
kubectl logs <pod-name> -n agents
```

### Service Unreachable

```bash
# Check service
kubectl get svc -n agents

# Check endpoints
kubectl get endpoints -n agents

# Port forward to test
kubectl port-forward svc/agent-service 8000:80 -n agents
```

### Out of Memory

Increase memory limits:

```yaml
resources:
  limits:
    memory: "1Gi"
```

---

## Best Practices

1. **Use specific image tags** — Don't use `latest` in production
2. **Set resource limits** — Prevent runaway containers
3. **Enable health checks** — Kubernetes can restart unhealthy pods
4. **Use secrets for sensitive data** — Never hardcode API keys
5. **Monitor logs** — Set up log aggregation (ELK, Datadog, etc.)
6. **Scale horizontally** — Use multiple replicas for high availability
7. **Use ConfigMaps** — Separate configuration from code
8. **Enable autoscaling** — Use Kubernetes HPA for dynamic scaling

---

## Next Steps

- Set up monitoring and alerting
- Configure log aggregation
- Set up CI/CD pipeline
- Plan for disaster recovery
