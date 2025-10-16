# Helm Chart Quick Start Guide

This guide walks you through deploying a new agent to the Kubernetes cluster using ArgoCD. Expected time: **~10 minutes**.

---

## Prerequisites

- Access to Azure DevOps repositories
- Helm CLI installed (`helm version`)
- kubectl configured for the target cluster
- ArgoCD UI credentials

---

## Step 1: Clone the Infrastructure Repository

Clone the ArgoCD deployment repository where all application manifests are stored:

```bash
git clone https://dev.azure.com/av360/Bechtle-Index-of-Sovereignty/_git/argocd-deployment
cd argocd-deployment
```

---

## Step 2: Customize the Helm Chart Values

Navigate to your agent's Helm chart directory (e.g., `docs/deployment/chart/`) and edit `values.yaml` to match your environment:

- Update `image.repository` and `image.tag` with your agent's Docker image
- Configure RabbitMQ connection details under `daprComponents.rabbitmq`
- Set application-specific settings under `appSettings`

**Validate your changes:**

```bash
cd docs/deployment/chart
helm lint .
```

**Optional: Test installation locally** (dry-run):

```bash
helm install test-agent . --dry-run --debug
```

---

## Step 3: Render Kubernetes Manifests

Generate the final Kubernetes YAML files from your Helm chart:

```bash
cd docs/deployment
sh render_resources.sh
```

This creates manifests in `docs/deployment/resources/`. **Review them carefully** to ensure:
- Correct image references
- Proper secret references
- Valid Dapr annotations (if using operator injection)

---

## Step 4: Create an ArgoCD Application Manifest

In the `argocd-deployment` repository, navigate to the `apps/` directory and create a new Application YAML file.

**Naming convention:** Use prefix `bios-agent-<service-name>`, e.g., `bios-agent-invoiceprocessor.yaml`

**Example Application manifest:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: bios-agent-invoiceprocessor
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  labels:
    tags: agents,llm
spec:
  destination:
    namespace: dev-bios-bechtle
    server: https://kubernetes.default.svc
  project: dev-bios-bechtle
  source:
    directory:
      recurse: true
    path: dev-bios-bechtle/bios-agents/invoice-processor
    repoURL: https://dev.azure.com/av360/Bechtle-Index-of-Sovereignty/_git/argocd-deployment
    targetRevision: HEAD
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Key fields:**
- `metadata.name`: Unique name for your agent (follow naming convention)
- `spec.destination.namespace`: Target Kubernetes namespace
- `spec.source.path`: Directory in the repo where your rendered manifests will live
- `syncPolicy.automated`: Enables automatic sync when manifests change

---

## Step 5: Copy Rendered Manifests to ArgoCD Repository

Copy the generated Kubernetes manifests from Step 3 into the path specified in your Application manifest:

```bash
# From your agent repository
cp -r docs/deployment/resources/agent-blueprint/* \
  /path/to/argocd-deployment/dev-bios-bechtle/bios-agents/invoice-processor/
```

**Commit and push** the changes:

```bash
cd /path/to/argocd-deployment
git add dev-bios-bechtle/bios-agents/invoice-processor/
git add apps/bios-agent-invoiceprocessor.yaml
git commit -m "Add invoice processor agent deployment"
git push origin main
```

---

## Step 6: Sync the Application in ArgoCD

1. Open the ArgoCD UI:
   [https://openshift-gitops-server-openshift-gitops.apps.mgmt.env.av360.org/](https://openshift-gitops-server-openshift-gitops.apps.mgmt.env.av360.org/)

2. Navigate to the **app-of-apps** application (this manages all agent applications)

3. Click **Sync** to deploy your new agent

4. Monitor the sync progress in the UI

---

## Step 7: Verify Deployment

Once ArgoCD reports the application as **Healthy** and **Synced**:

1. **Check pod status:**
   ```bash
   kubectl get pods -n dev-bios-bechtle -l app.kubernetes.io/name=agent-blueprint
   ```

2. **Verify Dapr sidecar:**
   ```bash
   kubectl logs <pod-name> -n dev-bios-bechtle -c daprd
   ```
   Look for successful RabbitMQ component initialization.

3. **Check RabbitMQ queues:**
   - Access RabbitMQ management UI
   - Verify that queues for your agent's subscriptions are created
   - Confirm consumer connections are active

4. **Test health endpoints:**
   ```bash
   kubectl port-forward -n dev-bios-bechtle <pod-name> 8000:8000
   curl http://localhost:8000/health/live
   curl http://localhost:8000/health/ready
   ```

---

## Troubleshooting

- **Pod fails to start:** Check logs with `kubectl logs <pod-name> -n dev-bios-bechtle`
- **Dapr sidecar errors:** Verify Dapr annotations and component configurations
- **RabbitMQ connection issues:** Confirm secret `rabbitmq-default-user` exists in the namespace
- **ArgoCD sync fails:** Review the Application status and events in the ArgoCD UI

---

## Next Steps

- Set up monitoring and alerting for your agent
- Configure horizontal pod autoscaling if needed
- Review and update resource limits based on actual usage
- Document agent-specific configuration and operational procedures
