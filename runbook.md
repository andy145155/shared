Here is a significantly more detailed **System Design** document for the Kubernetes approach. I have expanded it to include component-level specifications, the exact authentication flow (IRSA), failure handling, and observability strategies.

You can replace the previous "Document 3" with this version.

---

# System Design: AWS Config Compliance Report (Kubernetes)

## 1. High-Level Architecture

The system is designed as a **cloud-native, scheduled batch job** running on Amazon EKS. It utilizes the "Hub-and-Spoke" security pattern, where the EKS cluster (Hub) assumes authority to audit all Organization accounts (Spokes).

### Core Components

* **Orchestrator:** Kubernetes `CronJob` resource controller.
* **Runtime:** Docker container (Python 3.11 slim) running the compliance scanner script.
* **Identity Provider:** AWS IAM OIDC Provider linked to the EKS cluster (IRSA).
* **Storage:** Amazon S3 for report retention (Audit trail).

## 2. Component Specifications

### A. Kubernetes Resources

We will deploy the following resources into the `security-compliance` namespace:

| Resource | Name | Purpose | Configuration Details |
| --- | --- | --- | --- |
| **Namespace** | `security-compliance` | Isolation | Network Policies to deny ingress; Egress allowed to AWS APIs only. |
| **ServiceAccount** | `report-generator-sa` | Identity | **Crucial:** Must have annotation `eks.amazonaws.com/role-arn: arn:aws:iam::[HUB-ID]:role/system-config-report-generator-write-role`. |
| **CronJob** | `aws-config-compliance-audit` | Scheduling | **Schedule:** `0 9 * * 1` (Mon 9AM HKT).<br>

<br>**ConcurrencyPolicy:** `Forbid` (Prevents overlapping runs).<br>

<br>**SuccessfulJobsHistoryLimit:** 3 (Keep logs of recent successes). |
| **ConfigMap** | `compliance-config` | Config | Stores non-sensitive settings: `IGNORED_OUS`, `IGNORED_ACCOUNTS`, `S3_BUCKET_NAME`. |
| **Secret** | `compliance-secrets` | Credentials | (Optional) Stores Jira API Token if ticket creation is enabled. |

### B. Compute Resources (Pod Spec)

To ensure the job runs reliably without starving other cluster workloads:

* **Requests:** `cpu: "500m"`, `memory: "512Mi"` (Guaranteed capacity).
* **Limits:** `cpu: "1000m"`, `memory: "1Gi"` (Burstable ceiling).
* **RestartPolicy:** `OnFailure` (K8s will retry the pod if the script crashes due to transient network errors).
* **BackoffLimit:** `3` (Max 3 retries before marking the Job as "Failed" to prevent infinite crash loops).

## 3. Authentication & Security Design (IRSA Flow)

We strictly avoid hardcoded AWS credentials (AK/SK). Instead, we use **IAM Roles for Service Accounts (IRSA)**.

**The Handshake Flow:**

1. **Pod Startup:** The K8s Pod starts. The Amazon EKS Pod Identity Webhook injects a token file (JWT) into the container at `/var/run/secrets/eks.amazonaws.com/serviceaccount/token`.
2. **Assume Role:** The Python script (using `boto3`) calls `sts:AssumeRoleWithWebIdentity`.
3. **Verification:** AWS STS validates the JWT signature against the cluster's OIDC provider.
4. **Credential Vending:** STS returns temporary AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) for the Hub Role (`system-config-report-generator-write-role`).
5. **Cross-Account Access:** Using these Hub credentials, the script then calls `sts:AssumeRole` to access the target "Spoke" roles (`system-config-report-generator-read-role`).

## 4. Application Logic Flow

The Python application logic has been refactored for the containerized environment:

1. **Initialization:**
* Load config from Environment Variables (populated by ConfigMap).
* Initialize `boto3` session using IRSA.


2. **Discovery (Org Master):**
* Assume `list-org-role` in the Org Master account.
* Fetch all active account IDs, filtering out `IGNORED_ACCOUNTS`.


3. **Parallel Execution (The "Workhorse"):**
* Use `concurrent.futures.ThreadPoolExecutor` (Max Workers: 20).
* **Per Thread:**
* Assume `read-role` in Target Account .
* Pull AWS Config compliance data.
* *Error Handling:* If an account fails (e.g., role missing), log the error but **do not crash** the main process. Record as "Skipped".




4. **Aggregation & Reporting:**
* Aggregate results in memory.
* Generate `.xlsx` using `pandas`.
* Upload to S3: `s3://[BUCKET]/reports/ConfigRule_YYYY-MM-DD.xlsx`.


5. **Termination:**
* Exit with Code 0 (Success) or Code 1 (Failure if critical threshold met).



## 5. Observability & Monitoring

### Logging Strategy

* **Format:** JSON (Structured logging).
* **Output:** `stdout` / `stderr`.
* **Ingestion:** Fluentbit (DaemonSet) -> Datadog/Splunk.
* **Log Levels:**
* `INFO`: "Scanned account 123456789 successfully."
* `WARN`: "Account 987654321 skipped (Role not found)."
* `ERROR`: "Critical failure: S3 bucket not accessible."



### Alerting (Prometheus/Datadog)

We will monitor the Kubernetes Job status.

* **Metric:** `kube_job_status_failed`
* **Alert Rule:** If `kube_job_status_failed > 0` for namespace `security-compliance`, page the Platform Team.
* **SLA:** Investigation within 24 hours (since report is weekly).

## 6. Network Requirements

The EKS Worker Nodes must have egress access to the following AWS Public Endpoints (via NAT Gateway):

1. `sts.amazonaws.com` (Authentication)
2. `organizations.amazonaws.com` (Account Discovery)
3. `config.amazonaws.com` (Compliance Data)
4. `s3.amazonaws.com` (Report Upload)
5. `ec2/iam/rds/etc` (Resource metadata)

*Note: No Ingress ports need to be opened.*