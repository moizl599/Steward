# Setting up Kubecost on AWS EKS for Steward

Steward analyzes data from a running Kubecost install. This guide walks you through the AWS side: getting Kubecost installed on an EKS cluster, exposed to Steward, with the right config so Steward's scans work end-to-end.

For installing **Steward itself**, see [INSTALL.md](INSTALL.md). This page is about the cluster-side prerequisites.

---

## Prerequisites

Before starting, you need:

- An **EKS cluster** (any actively-supported Kubernetes version — Kubecost supports 1.21+).
- **`kubectl`** configured to talk to that cluster: `kubectl get nodes` should work.
- **`helm`** v3.x installed locally: `helm version`.
- **AWS credentials** with at least `eks:DescribeCluster` and read access to EC2/EBS pricing APIs. The default `AdministratorAccess`-ish role most people use works fine.
- Enough cluster capacity for Kubecost: roughly 1 vCPU and 2 GB RAM for the default install. Bigger clusters need more — see Kubecost's [sizing guide](https://docs.kubecost.com/install-and-configure/install/getting-started#sizing).

If you don't yet have an EKS cluster, the fastest path is `eksctl create cluster --name kubecost-test --region us-east-1 --nodes 2`. Takes 15–20 minutes.

---

## Step 1: Install Kubecost via Helm

Add the Kubecost Helm repo and install with sensible defaults for a Steward deployment:

```bash
helm repo add kubecost https://kubecost.github.io/cost-analyzer/
helm repo update

helm upgrade --install kubecost kubecost/cost-analyzer \
  --namespace kubecost \
  --create-namespace \
  --set kubecostProductConfigs.clusterName=<your-cluster-name> \
  --set prometheus.server.persistentVolume.size=32Gi \
  --set persistentVolume.size=32Gi
```

Replace `<your-cluster-name>` with your EKS cluster name (e.g. `prod-eks`). This name shows up in Kubecost's UI and in Steward's environment list.

The install takes ~3 minutes. Watch progress:

```bash
kubectl get pods -n kubecost -w
```

When all pods show `Running` and `Ready 1/1` (or `2/2` for the cost-analyzer pod), Kubecost is up. The most important pod is `kubecost-cost-analyzer-*` — that's the one Steward will talk to.

> **Note on the free token.** Kubecost's `helm install` will work without a `kubecostToken`. The token unlocks the hosted Kubecost UI's extended features but is **not required** for the API endpoints Steward uses (`/model/allocation`, `/model/assets`, `/model/savings`). You can ignore it.

### Verify Kubecost is collecting data

After install, Kubecost needs ~10 minutes to start producing useful allocation data (Prometheus has to gather a few scrape windows first). Wait, then check from inside the cluster:

```bash
kubectl exec -n kubecost deploy/kubecost-cost-analyzer -- \
  wget -qO- 'http://localhost:9090/model/allocation?window=24h&aggregate=namespace'
```

You should see JSON with namespace cost allocations. If it returns empty data, wait a few more minutes — Prometheus is still warming up.

---

## Step 2: Expose Kubecost's API to Steward

Steward's backend needs to reach Kubecost's HTTP API. There are three patterns, ordered by setup complexity:

### Option A — `kubectl port-forward` (laptop / dev installs)

Simplest. Open a port-forward on your laptop:

```bash
kubectl port-forward -n kubecost svc/kubecost-cost-analyzer 9090:9090
```

This runs in the foreground and keeps the connection open. In Steward's environment form, use:

- **Kubecost URL:** `http://host.docker.internal:9090`

The `host.docker.internal` hostname is Docker Desktop's way to reach your laptop from inside a container. On Linux Docker (no Docker Desktop), use `http://172.17.0.1:9090` or set `network_mode: host` for the backend service.

**Pros:** Zero AWS config changes. No security exposure outside your laptop.
**Cons:** Stops working when your laptop sleeps or you close the terminal. The port-forward must be running every time Steward runs a scan.

### Option B — Internal Load Balancer + Ingress (production-ish)

For an install you want to keep running, expose Kubecost behind an internal-facing AWS Load Balancer. This assumes you've got the AWS Load Balancer Controller installed on your cluster (most production EKS clusters do).

Create an `Ingress`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kubecost
  namespace: kubecost
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internal
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}]'
    # If you want HTTPS, add a cert ARN:
    # alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS": 443}]'
    # alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:...
spec:
  rules:
    - host: kubecost.internal.your-domain.com  # set up DNS pointing at the ALB
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kubecost-cost-analyzer
                port:
                  number: 9090
```

Apply:

```bash
kubectl apply -f kubecost-ingress.yaml
kubectl get ingress -n kubecost   # wait for ADDRESS to be populated
```

Then in Steward:

- **Kubecost URL:** `http://kubecost.internal.your-domain.com` (or the ALB hostname if you don't have DNS)

**Pros:** Always available. Reachable from a VPC-attached Steward host.
**Cons:** Requires the ALB Controller. The ALB is publicly addressable on the internet by default — make sure `scheme: internal` is set, or that your VPC routing doesn't bridge the public internet to internal ALBs.

**Lock down access.** An internal ALB is reachable from anywhere inside the VPC. Layer auth on top — either ALB authentication actions (Cognito, OIDC) or a sidecar like `oauth2-proxy`. Then set Steward's `auth_token` field to whatever bearer token your auth layer accepts.

### Option C — In-cluster ClusterIP (if Steward also runs in EKS)

If you deploy Steward itself into the same EKS cluster (a coherent v0.2 setup; not the v0.1 default), point at Kubecost's ClusterIP service directly:

- **Kubecost URL:** `http://kubecost-cost-analyzer.kubecost.svc.cluster.local:9090`

**Pros:** No external exposure. Service mesh / NetworkPolicy can lock down which pods can reach Kubecost.
**Cons:** Steward isn't packaged for in-cluster deployment in v0.1.

---

## Step 3: Auth (optional in most installs)

By default, Kubecost's API endpoints are unauthenticated — anyone who can reach `kubecost-cost-analyzer:9090` can query them. This is fine when only Steward (and your trusted users) can reach the service.

**If you put an authenticating proxy in front of Kubecost** (Option B with oauth2-proxy, or ALB auth actions), you'll need a bearer token Steward can include in API requests. That goes in the **Auth token** field of Steward's environment form. Steward includes it as `Authorization: Bearer <token>` on every request.

How you generate that token depends on your auth setup — there's no single answer. Common patterns:

- **oauth2-proxy with static bearer-token mode:** generate any random string, configure oauth2-proxy to accept it as a valid token, paste it into Steward.
- **ALB Cognito authentication:** Kubecost can validate against the Cognito-issued JWT. Use a long-lived service-account token from Cognito and paste it.
- **Basic auth in nginx:** put the `user:password` pair through `base64`, paste as `Basic <encoded>`, and update Steward's URL to match.

For laptop / dev installs (Option A above), **leave the Auth token field blank**. Kubecost's API is unauthenticated and the port-forward isn't exposed to anyone else.

---

## Step 4: Find your AWS region and cluster name

Steward's environment form asks for both. Pull them from AWS:

```bash
# Your AWS region
aws configure get region

# Or list clusters across regions
aws eks list-clusters --region us-east-1
aws eks list-clusters --region us-west-2
# ... etc.

# Describe a specific cluster (cluster name comes from the list-clusters output)
aws eks describe-cluster --name prod-eks --region us-east-1
```

In Steward:

- **AWS region:** pick from the dropdown matching the cluster's region (e.g. `us-east-1`).
- **Cluster name:** the value from `--name` above (e.g. `prod-eks`). Optional — used as a display tag in Steward's UI.

These don't have to match Kubecost's internal cluster name. They're informational for the operator.

---

## Step 5: Verify Steward can reach Kubecost

Before adding the environment in Steward, sanity-check the URL from the backend container:

```bash
# If Steward is already running:
docker compose exec backend curl -v "<your-kubecost-url>/model/allocation?window=24h&aggregate=namespace"
```

You should see a 200 OK and a JSON body. If you get:

- **`Connection refused`** — the URL is wrong, the port-forward died, or the Ingress isn't routing correctly.
- **`Could not resolve host`** — DNS issue. Use the IP or the ALB hostname directly.
- **`401 Unauthorized`** — auth proxy expects a token. Add it via Steward's environment form.
- **Empty `data: [null]`** — Kubecost is up but hasn't collected enough data yet. Wait 10 minutes.
- **HTML response instead of JSON** — you're hitting the Kubecost web UI, not the API. Make sure your URL doesn't include any path beyond the host:port.

When this `curl` succeeds, Steward will succeed too. Go add the environment via the UI.

---

## Common gotchas

### Security group blocks the ALB

If you use Option B and the ALB shows up but Steward can't reach it:

```bash
# Find the ALB's security group
aws elbv2 describe-load-balancers --names <alb-name> --query 'LoadBalancers[0].SecurityGroups'

# Add an inbound rule allowing traffic from Steward's source CIDR
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxx \
  --protocol tcp \
  --port 80 \
  --cidr <your-steward-host-or-vpc-cidr>/32
```

### Kubecost reports zero cost for everything

Usually means the AWS Spot Instance Data Feed or the Kubecost spot integration isn't configured. For on-demand instances the default install gets pricing from a public source automatically — should "just work." For Spot / Savings Plans / RIs, see [Kubecost's AWS integration docs](https://docs.kubecost.com/install-and-configure/install/cloud-integration/aws-cloud-integrations).

For Steward purposes, even rough costs are enough to surface the structural patterns (idle workloads, over-provisioning). Don't block on getting the dollar figures perfect.

### `kubecost-cost-analyzer-network-costs` pod is in `CrashLoopBackOff`

This is a separate DaemonSet that adds network attribution. It often fails to start on EKS because it expects host-network access and the right kernel modules. Steward doesn't need this pod — disable it:

```bash
helm upgrade kubecost kubecost/cost-analyzer \
  --namespace kubecost \
  --reuse-values \
  --set networkCosts.enabled=false
```

### Persistent volumes won't bind

The Helm chart asks for two PVs (Prometheus + Kubecost storage), 32 GB each. On EKS, you need an EBS CSI driver installed and a default StorageClass. If `kubectl get pv` shows nothing being provisioned:

```bash
# Install the EBS CSI driver if missing
aws eks create-addon --cluster-name <your-cluster> --addon-name aws-ebs-csi-driver

# Make sure gp3 (or gp2) is the default StorageClass
kubectl get storageclass
# Mark one as default if needed:
kubectl patch storageclass gp3 -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```

### Helm install fails on `prometheus-server` schema validation

You're probably on an older Helm version. Upgrade to v3.10+ and retry. If you really can't upgrade Helm, install with `--skip-schema-validation`.

---

## Uninstalling Kubecost

```bash
helm uninstall kubecost -n kubecost
kubectl delete namespace kubecost
```

The PVs will hang around as `Released` unless your StorageClass's `reclaimPolicy` is `Delete`. Clean them up manually with `kubectl delete pv <name>` if needed.

---

## When this all works

You should be able to:

1. Open Steward at `http://localhost:3000`.
2. Click **+ New environment**.
3. Paste the Kubecost URL from Step 2.
4. Pick your AWS region from the dropdown.
5. Submit — the connection pill turns green.
6. Click **Scan** on the new environment's card.
7. See a real cost analysis a minute or two later.

If something breaks along the way, [TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers the most common failure modes.
