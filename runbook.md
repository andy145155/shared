Here is the complete, standalone `README.md` file. You can copy and paste this directly into your repository.

---

# External-DNS Release Verifier

This tool provides automated "Black Box" verification for `external-dns` releases on EKS. It is designed to run as an **ArgoCD PostSync Job** in non-production environments (`ptdev`, `dev`, `stg`) to certify that a new version of `external-dns` is fully functional before it is promoted.

## 🌊 Verification Logic Flowchart

The following flowchart illustrates the decision logic for the verification process, including the specific handling of `upsert-only` environments to prevent "zombie" DNS records.

```mermaid
flowchart TD
    A[Start: PostSync Job Triggered] --> B{Check Version}
    B -- Mismatch --> C[FAIL: Alert Version Mismatch]
    B -- Match --> D[Step 1: Create Test Service]
    
    D --> E{Verify Route53 Creation}
    E -- Timeout/Not Found --> F[FAIL: DNS Creation Failed]
    E -- Found --> G[Step 2: Delete Test Service]
    
    G --> H{Is UPSERT_ONLY_MODE?}
    
    H -- NO (Standard Sync) --> I{Verify Route53 Deletion}
    I -- Record Persists --> J[FAIL: DNS Deletion Failed]
    I -- Record Gone --> K[SUCCESS: Full Lifecycle Verified]
    
    H -- YES (Upsert Only) --> L[Skip Deletion Verification]
    L --> M[Step 3: Force Manual Cleanup via Boto3]
    M --> N[SUCCESS: Creation Verified & Cleaned Up]
    
    style C fill:#ffcccc,stroke:#ff0000
    style F fill:#ffcccc,stroke:#ff0000
    style J fill:#ffcccc,stroke:#ff0000
    style K fill:#ccffcc,stroke:#00aa00
    style N fill:#ccffcc,stroke:#00aa00

```

## 📋 Overview

This automation replaces manual "curl" or "dig" checks with a deterministic verification process. It handles the two primary operation modes of `external-dns`:

1. **Sync Mode (e.g., `ptdev`):** Verifies the full lifecycle (**Create**  **Verify**  **Delete**  **Verify**). This proves `external-dns` can *add* and *remove* records.
2. **Upsert-Only Mode (e.g., `stg`):** Verifies creation only. Since `external-dns` is forbidden from deleting records in these environments, the verifier creates the record, verifies it, and then **self-cleans** the Route53 record using the AWS API to prevent polluting the zone with test data.

## 🛠 Prerequisites
Here is the updated **README.md** reflecting your specific cross-namespace architecture (`external-dns` App  `af-toolkit` Job  `verification-external-dns` Resource).

---

# External-DNS Release Verifier

This tool provides automated "Black Box" verification for `external-dns` releases on EKS. It is designed to run as an **ArgoCD PostSync Job** to certify that a new version of `external-dns` is fully functional before the release is considered successful.

## 🏗 Architecture & Design

The verification process involves three distinct namespaces to ensure isolation and security.

```mermaid
flowchart TD
    subgraph K8s_Cluster [EKS Cluster]
        subgraph NS_ExtDNS [Namespace: external-dns]
            Controller[External-DNS Pod]
        end
        
        subgraph NS_Toolkit [Namespace: af-toolkit]
            Job[Verifier Job]
            SA[ServiceAccount]
        end
        
        subgraph NS_Verify [Namespace: verification-external-dns]
            TestSvc[Test Service<br>external-dns-test]
        end
    end
    
    subgraph AWS [AWS Cloud]
        R53[Route53 API]
    end

    %% Flows
    Job -- "1. Deploy (Cross-NS RBAC)" --> TestSvc
    Controller -- "2. Watch Service" --> TestSvc
    Controller -- "3. Create Record" --> R53
    Job -- "4. Poll/Verify" --> R53
    
    %% Styles
    style Job fill:#ccf,stroke:#333
    style TestSvc fill:#cfc,stroke:#333
    style R53 fill:#f9f,stroke:#333

```

### Workflow

1. **Trigger:** ArgoCD syncs `external-dns` and triggers the PostSync Job in `af-toolkit`.
2. **Execution:** The Job uses a ServiceAccount in `af-toolkit` to create a `Service` in the `verification-external-dns` namespace.
3. **Validation:** The script polls AWS Route53 to confirm `external-dns` successfully propagated the record.
4. **Cleanup:**
* **Sync Mode (PTDEV):** Deletes the Service and verifies Route53 record removal.
* **Upsert Mode (STG):** Verifies creation, then performs a "Self-Cleanup" of the Route53 record via Boto3 (bypassing the controller).



---

## 🌊 Verification Logic

```mermaid
flowchart TD
    A[Start: PostSync Job Triggered] --> B{Check Version}
    B -- Mismatch --> C[FAIL: Alert Version Mismatch]
    B -- Match --> D[Step 1: Create Test Service<br>in 'verification-external-dns']
    
    D --> E{Verify Route53 Creation}
    E -- Timeout/Not Found --> F[FAIL: DNS Creation Failed]
    E -- Found --> G[Step 2: Delete Test Service]
    
    G --> H{Is UPSERT_ONLY_MODE?}
    
    H -- NO (Standard Sync) --> I{Verify Route53 Deletion}
    I -- Record Persists --> J[FAIL: DNS Deletion Failed]
    I -- Record Gone --> K[SUCCESS: Full Lifecycle Verified]
    
    H -- YES (Upsert Only) --> L[Skip Deletion Verification]
    L --> M[Step 3: Force Manual Cleanup via Boto3]
    M --> N[SUCCESS: Creation Verified & Cleaned Up]
    
    style C fill:#ffcccc,stroke:#ff0000
    style F fill:#ffcccc,stroke:#ff0000
    style J fill:#ffcccc,stroke:#ff0000
    style K fill:#ccffcc,stroke:#00aa00
    style N fill:#ccffcc,stroke:#00aa00

```

---

## 🛠 Prerequisites & RBAC

Because the Job runs in `af-toolkit` but manages resources in `verification-external-dns`, strict RBAC is required.

### 1. AWS Permissions (IRSA)

The IAM Role attached to the `af-toolkit` ServiceAccount must have:

* `route53:ListResourceRecordSets` (For verification)
* `route53:ChangeResourceRecordSets` (For self-cleanup in upsert-only envs)

### 2. Kubernetes Cross-Namespace RBAC

You must apply these manifests to allow the "namespace jump":

**ServiceAccount (in `af-toolkit`)**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
    name: external-dns-verifier-sa
    namespace: af-toolkit

```

**Role & Binding (in `verification-external-dns`)**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
    name: external-dns-verifier-role
    namespace: verification-external-dns
rules:
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["create", "get", "delete", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
    name: external-dns-verifier-binding
    namespace: verification-external-dns
subjects:
  - kind: ServiceAccount
    name: external-dns-verifier-sa
    namespace: af-toolkit
roleRef:
    kind: Role
    name: external-dns-verifier-role
    apiGroup: rbac.authorization.k8s.io

```

---

## ⚙️ Configuration

The container is configured via Environment Variables.

| Variable | Description | Default |
| --- | --- | --- |
| `AWS_REGION` | AWS Region (e.g., `ap-east-1`). | `ap-east-1` |
| `HOSTED_ZONE_ID` | **Required.** The Route53 Zone ID to test against. | - |
| `TEST_DOMAIN_NAME` | **Required.** FQDN for the test record. | - |
| `TARGET_NAMESPACE` | The namespace to create test resources in. | `verification-external-dns` |
| `UPSERT_ONLY_MODE` | Set `true` if cluster forbids automatic deletions. | `false` |
| `EXPECTED_VERSION` | Image tag expected to be running. | `latest` |

---

## 🚀 Deployment Guide (ArgoCD)

We use the **Multiple Sources** pattern to inject this Job into the `external-dns` Application.

### 1. Job Template

Add this to your chart or a secondary source folder.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: external-dns-verifier
  namespace: af-toolkit  # <-- Job runs here
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      serviceAccountName: external-dns-verifier-sa
      containers:
      - name: verifier
        image: platform-docker-images/external-dns-verifier:v1.0.0
        env:
        - name: TARGET_NAMESPACE
          value: "verification-external-dns" # <-- Resources created here
        - name: HOSTED_ZONE_ID
          value: {{ .Values.hostedZoneId | quote }}
        - name: TEST_DOMAIN_NAME
          value: {{ .Values.testDomainName | quote }}
        - name: UPSERT_ONLY_MODE
          value: {{ .Values.upsertOnly | quote }}

```

### 2. ArgoCD Application Config

Update your `external-dns` Application to include the source and inject the Zone ID.

```yaml
spec:
  sources:
    - repoURL: https://kubernetes-sigs.github.io/external-dns
      chart: external-dns
      targetRevision: 1.14.0
    - repoURL: https://github.com/your-org/platform-charts.git
      path: apps/external-dns-verifier
      helm:
        values: |
          hostedZoneId: {{ index .Values.cluster.zoneIdMap .Values.cluster.name }}
          testDomainName: "ext-dns-verify-{{ .Values.cluster.name }}.dev.mox.com"
          upsertOnly: {{ if eq .Values.cluster.env "stg" }}true{{ else }}false{{ end }}

```

---

## 🛡 Safety & Troubleshooting

### Safety Locks

* **Prefix Check:** The script will **REFUSE** to perform manual cleanup if the domain name does not start with `ext-dns-`, `ver-test`, or `canary`.
* **Timeout:** The job fails after 5 minutes (300s) to prevent indefinite hanging.

### Troubleshooting Steps

If the PostSync hook fails:

1. **View Logs:**
```bash
kubectl logs job/external-dns-verifier -n af-toolkit

```


2. **Check Test Resource:**
```bash
kubectl get svc -n verification-external-dns

```


* *If Service exists but DNS is missing:* `external-dns` controller is likely broken or permissions are missing.
* *If Service is missing:* The Job failed to create it (check RBAC).


3. **Manual Cleanup:**
If the script crashed hard, you may need to manually delete the service:
```bash
kubectl delete svc external-dns-test-service -n verification-external-dns

```
### AWS Permissions (IRSA)

The Pod running this image requires an IAM Role (IRSA) with the following Route53 permissions.

* **ListResourceRecordSets**: Required for verification.
* **ChangeResourceRecordSets**: Required **only** if running in `UPSERT_ONLY_MODE` (to perform self-cleanup).

### Kubernetes RBAC

The Job needs a ServiceAccount with permissions to:

* `create`, `get`, `delete` Services (to manage the test fixture).
* `get`, `list` Pods (to verify the running `external-dns` version).

## ⚙️ Configuration

The container is configured entirely via Environment Variables passed from your Helm Chart.

| Variable | Description | Required | Default |
| --- | --- | --- | --- |
| `AWS_REGION` | AWS Region (e.g., `ap-east-1`). | ✅ | `ap-east-1` |
| `HOSTED_ZONE_ID` | The Route53 Zone ID to test against. | ✅ | - |
| `TEST_DOMAIN_NAME` | FQDN for the test record (e.g., `ver-test.dev.mox.com`). | ✅ | - |
| `UPSERT_ONLY_MODE` | Set to `true` if the cluster forbids automatic deletions. | ❌ | `false` |
| `EXPECTED_VERSION` | The image tag expected to be running (e.g., `v0.15.0`). | ❌ | `latest` |
| `TARGET_NAMESPACE` | Namespace where the test Service is deployed. | ❌ | `af-toolkit` |

## 🚀 Deployment Guide

### 1. Build Image

```bash
docker build -t platform-docker-images/external-dns-verifier:v1.0.0 .

```

### 2. Helm Integration (ArgoCD)

Add this Job to your `af-toolkit` or `external-dns` Helm chart template.

**Example: `templates/verification-job.yaml**`

```yaml
{{- if .Values.verification.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: external-dns-verifier
  namespace: {{ .Values.verification.namespace | default "af-toolkit" }}
  annotations:
    # Runs AFTER the new external-dns pods are healthy
    argocd.argoproj.io/hook: PostSync
    # Deletes the Job on success to keep the cluster clean
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: external-dns-verifier-sa
      restartPolicy: Never
      containers:
      - name: verifier
        image: {{ .Values.verification.image }}
        env:
        - name: HOSTED_ZONE_ID
          value: {{ .Values.verification.hostedZoneId | quote }}
        - name: TEST_DOMAIN_NAME
          value: "ext-dns-verify-{{ .Values.cluster.name }}.dev.mox.com"
        - name: EXPECTED_VERSION
          value: {{ .Values.image.tag | quote }}
        # Set this to true for STG if STG uses upsert-only policy
        - name: UPSERT_ONLY_MODE
          value: {{ .Values.verification.upsertOnly | default "false" | quote }}
{{- end }}

```

## 🛡 Safety Mechanisms

1. **Prefix Lock:** The verification script includes a safety lock. It will **refuse** to perform manual cleanup on any domain that does not start with specific prefixes (e.g., `ext-dns-`, `ver-test`), preventing accidental deletion of production records if the configuration is incorrect.
2. **Self-Cleanup:** If the test fails in `ptdev` (Sync Mode), the script attempts to clean up the Kubernetes Service to avoid leaving orphan resources in the cluster.

## 🚨 Troubleshooting

If the verification Job fails, the ArgoCD sync will be marked as Failed.

**Steps to resolve:**

1. **Check Job Logs:**
```bash
kubectl logs job/external-dns-verifier -n af-toolkit

```


2. **Manual Cleanup (K8s):**
If the script crashed before cleanup, remove the test service:
```bash
kubectl delete svc external-dns-test-service -n af-toolkit

```


3. **Manual Cleanup (Route53):**
If the script failed to delete the DNS record, manually remove the `TEST_DOMAIN_NAME` record via AWS Console or CLI.