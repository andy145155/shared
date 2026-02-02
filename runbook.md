This is a smart move. Splitting the documentation ensures clarity: the **Requirements** stay static, the **Decision Log** preserves the "why" for future engineers, and the **Design/Implementation** docs become the active technical references for the Kubernetes approach.

Here are your four distinct documents.

### Document 1: Requirements Definition

**Purpose:** Defines the business problem and success criteria.

---

# Requirements: AWS Config Compliance Automation

## 1. Problem Statement

The Platform Engineering team currently executes a manual, local Python script to generate weekly AWS Config compliance reports. This process is inefficient because:

* **Manual Effort:** It consumes engineering time every week.
* **Security Risk:** It relies on local credentials (`aws-okta`) which is not a best practice for automated tasks.
* **Lack of Auditability:** There is no centralized log of execution or report generation.

## 2. Business Goals

* **Automation:** The report generation must run automatically every Monday morning without human intervention.
* **Integration:** The system must generate an Excel report (`.xlsx`) and ideally create a Jira ticket for tracking.
* **Scalability:** The solution must support hundreds of AWS accounts without timing out or requiring manual batching.

## 3. Technical Requirements

* **Hub-and-Spoke Security:** A central security account (`*-sec-control`) must act as the "Hub" to scan all "Spoke" accounts.
* **Least Privilege:** Access must be granted via IAM Roles, not long-lived user access keys.
* **Cost Efficiency:** The solution should leverage existing infrastructure where possible to minimize additional costs.

---

### Document 2: Decision Log (ADR)

**Purpose:** Records the architectural options considered and justifies the final choice.

---

# Architecture Decision Record (ADR): Compliance Reporting Engine

## 1. Context

We need a compute platform to run the compliance Python script. The script makes API calls to hundreds of accounts, which is an I/O-bound task that can exceed 15 minutes as the organization grows.

## 2. Options Evaluated

| Option | Description | Pros | Cons |
| --- | --- | --- | --- |
| **1. Lambda Sharding** | Trigger multiple Lambdas with different "shards" of the account list. | Bypasses timeout. | High complexity (merging results). Brittle logic. |
| **2. Multi-threaded Lambda** | Single Lambda using python threading. | Simple setup. Low cost. | **Hard limit of 15 mins.** Risk of future failure as account count grows. |
| **3. Step Functions** | Distributed Map state triggers one Lambda per account. | Infinite scale. | Higher complexity. Higher cost due to state transitions. |
| **4. Fargate Task** | Run container as a standalone task. | No timeouts. | Slow startup. Higher cost per execution. |
| **5. Kubernetes CronJob** | Schedule a Pod on existing EKS clusters (`cybsecops-cluster`). | **No timeouts.** Uses existing compute (sunk cost). | Requires Docker build pipeline and IRSA setup. |

## 3. Decision

**We define the architecture using Option 5: Kubernetes CronJob.**

## 4. Rationale

While Multi-threaded Lambda (Option 2) is simpler for an MVP, we are selecting **Kubernetes** because:

1. **Zero Timeout Risk:** Unlike Lambda, a Pod can run for hours if necessary, future-proofing us against organization growth.
2. **Existing Investment:** We already operate `ptdev-cybsecops-cluster`. Running this as a CronJob consumes spare capacity we are already paying for.
3. **Security Standard:** We can utilize **IRSA (IAM Roles for Service Accounts)**, which is the team's standard for workload identity, avoiding the need to manage Lambda execution roles separately.

---

### Document 3: System Design

**Purpose:** Technical specification of the Kubernetes solution.

---

# System Design: AWS Config Report (Kubernetes)

## 1. High-Level Architecture

The system runs as a containerized **CronJob** inside the `ptdev/prod-cybsecops-cluster` EKS cluster.

* **Namespace:** `security-compliance` (or `aws-config-report-automation`).
* **Schedule:** Weekly (e.g., `0 9 * * 1`).
* **Identity:** The Pod uses a Kubernetes ServiceAccount annotated with an AWS IAM Role ARN (IRSA).

## 2. IAM Security Model (Hub & Spoke)

We utilize a **Hub-and-Spoke** pattern where the EKS cluster acts as the Hub.

### A. Hub Account (`*-sec-control`)

* **Identity:** `system-config-report-generator-write-role`
* **Type:** IAM Role for Service Accounts (IRSA).
* **Trust Policy:** Trusts the EKS Cluster's OIDC Provider (Federated identity), *not* `lambda.amazonaws.com`.
* **Permissions:**
* `sts:AssumeRole`: Allowed to assume the "Read Role" in spoke accounts.
* `s3:PutObject`: Allowed to upload reports to the S3 bucket.



### B. Spoke Accounts (Target Accounts)

* **Identity:** `system-config-report-generator-read-role`
* **Type:** Cross-Account Role.
* **Trust Policy:** Allows `arn:aws:iam::[HUB-ACCOUNT-ID]:role/system-config-report-generator-write-role` to assume it.
* **Permissions:** Read-only access to AWS Config, EC2, IAM, and RDS metadata.

### C. Org Master Account

* **Identity:** `system-config-report-generator-list-org-role`
* **Purpose:** Allows the script to discover all active account IDs dynamically.

## 3. Data Flow

1. **Trigger:** K8s CronJob spawns a Pod.
2. **Auth:** Pod authenticates via OIDC and receives temporary AWS credentials for the *Hub Role*.
3. **Discovery:** Script assumes the *Org Master Role* to fetch the list of all active accounts.
4. **Scan:** Script iterates through accounts, assuming the *Spoke Read Role* in each one to fetch compliance data.
5. **Output:** Script generates `.xlsx` in memory and uploads it directly to the S3 Bucket.

---

### Document 4: Implementation Plan

**Purpose:** Step-by-step engineering guide.

---

# Implementation Plan

## Phase 1: IAM Deployment (Terraform)

*Before deploying code, we must establish the identity web.*

1. **Define Spoke Roles (Read-Only)**
* **Repo:** `ProjectDrgn/terraform-infrastructure-skeleton` path `/common/baseline/global`.
* **Action:** Add `system-config-report-generator-read-role` module. Ensure Trust Policy allows the Hub Account ID.
* **Promote:** `ptdev` -> `stg` -> `prod`.


2. **Define Org Discovery Role**
* **Repo:** `ProjectDrgn/terraform-infra-orgmaster`.
* **Action:** Deploy `system-config-report-generator-list-org-role`.


3. **Define Hub Role (IRSA)**
* **Repo:** `ProjectDrgn/terraform-infra-security-control`.
* **Action:** Create `system-config-report-generator-write-role`.
* **Critical:** The Trust Policy must specify the `Condition` for the specific ServiceAccount namespace and name:
```json
"StringEquals": {
  "oidc.eks...:sub": "system:serviceaccount:security-compliance:report-generator-sa"
}

```





## Phase 2: Containerization

1. **Dockerize Script:**
* Create `Dockerfile` in the script repository.
* Base image: `python:3.11-slim`.
* Install dependencies: `boto3`, `pandas`, `openpyxl`.
* Entrypoint: `["python", "main.py"]`.


2. **Build & Push:**
* Build image and push to your internal ECR (Elastic Container Registry).



## Phase 3: Kubernetes Deployment

1. **Create Manifests (Helm Chart):**
* **Namespace:** `security-compliance`
* **ServiceAccount:** `report-generator-sa` (Annotate with Hub Role ARN).
* **CronJob:** Schedule the container image. Set resources (e.g., `requests: cpu: 500m, memory: 512Mi`).


2. **Deploy:**
* Apply manifests to `ptdev-cybsecops-cluster` first for validation.



## Phase 4: Validation

1. **Dry Run:** Trigger the CronJob manually (`kubectl create job --from=cronjob/...`).
2. **Check Logs:** `kubectl logs -f job/...` to verify role assumption logic.
3. **Verify Output:** Check S3 bucket for the generated Excel report.