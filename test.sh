Here are the updated sections for your Confluence pages. I have added the two new items to the **Requirements** table and created a specific **Data Storage & Access Design** section to technically detail how we achieve retention and access control.

### Part 1: Updated Requirements Definition

*Copy and paste this table to replace your existing "Mandatory Capabilities" table.*

```markdown
# 1. Requirements Definition

## Mandatory Capabilities & Metrics
The following table defines the mandatory elements for the AWS Config Compliance automation project.

| **Category** | **Requirement** | **Metric / Verification** | **Target Implementation** | **Current State** |
| :--- | :--- | :--- | :--- | :--- |
| **Automation** | **Zero-Touch Execution**<br>The system must generate and deliver the report automatically on a scheduled basis without human intervention. | • **Frequency:** Weekly (Mon 09:00 HKT)<br>• **Manual Steps:** 0 | **Kubernetes CronJob** triggered by cluster schedule. Report output is automatically uploaded to S3. | **Manual:** Engineer runs Python script locally on laptop. |
| **Performance** | **Execution Duration**<br>The solution must support long-running processes that exceed AWS Lambda's hard limits to accommodate future growth. | • **Max Duration:** > 15 minutes<br>• **Account Capacity:** Support 500+ accounts | **Containerized Workload (Pod)** running on EKS. No hard timeout limits applied to the process. | **Limited:** Local script runs until finished, but migrating to standard Lambda would impose a 15-min cap. |
| **Security** | **Identity Management**<br>Eliminate long-lived access keys in the cloud environment. Use temporary, rotated credentials for all API access. | • **Creds Type:** STS Temporary Tokens<br>• **Long-lived Keys on Disk:** 0 | **IRSA (IAM Roles for Service Accounts):** Pod authenticates via OIDC. Hub-and-Spoke role assumption. | **Risk:** Relies on `aws-okta` and local `~/.aws/credentials` files on user laptops. |
| **Storage** | **Historical Retention**<br>Reports must be persisted for a specific duration for audit purposes, then automatically purged to manage costs. | • **Retention Period:** 365 Days (Configurable)<br>• **Deletion Mechanism:** Auto-Lifecycle | **S3 Lifecycle Policy:** Rules configured on the bucket to transition to Standard-IA after 30 days and expire after 1 year. | **None:** Files exist only on the laptop of the engineer who ran the script. |
| **Access** | **Strict Read-Only Access**<br>Access to download/view reports must be restricted to authorized personnel via a specific IAM Role, decoupled from the generation process. | • **Access Principle:** Least Privilege<br>• **Identity:** Dedicated Reader Role | **IAM Role:** `system-config-report-reader-role` with `s3:GetObject` permission strictly scoped to the report bucket. | **Ad-hoc:** Reports are shared via email/Slack (Unsecured). |
| **Observability**| **Log-Based Alerting (Datadog)**<br>The system must emit structured logs. A Datadog Monitor must be configured to detect error logs for the specific service and trigger a Slack alert immediately. | • **Log Query:** `logs("service:aws-config-compliance status:error").rollup("count") > 0`<br>• **Alert Latency:** < 5 mins | **Datadog Log Monitor:** Configured to catch `status:error` logs emitted by the Python script.<br>**Notification:** Datadog `@slack-[channel]` integration. | **None:** Failures are silent; no one knows if the script crashes unless they manually check. |
| **Output** | **Report Integrity**<br>The output must match the current Excel format exactly, including conditional formatting and tab structure. | • **Format:** `.xlsx`<br>• **Accuracy:** 100% match with legacy script | **Python Pandas/OpenPyXL:** Logic ported to container to generate identical binary Excel file in memory. | **Manual:** Script generates file locally; engineer manually uploads or shares it. |

```

---

### Part 2: Data Storage & Access Design

*Add this new section to your "System Design" document to detail the technical implementation of the new requirements.*

```markdown
# 3. Data Storage & Access Design

This section details the architecture for the S3 persistence layer and the segregated access control model.

## 3.1 S3 Bucket Configuration
**Bucket Name:** `s3-config-compliance-reports-[env]` (e.g., `s3-config-compliance-reports-prod`)
**Encryption:** SSE-S3 (Server-Side Encryption) enabled by default.
**Versioning:** Enabled (To prevent accidental overwrite or deletion of audit evidence).

### Lifecycle Policy (Retention)
To satisfy the **Historical Retention** requirement, the following Lifecycle Rule will be applied via Terraform:

| **Rule Scope** | **Transition** | **Expiration** | **Rationale** |
| :--- | :--- | :--- | :--- |
| `prefix: reports/` | **30 Days:** Move to `STANDARD_IA` (Infrequent Access) | **365 Days:** Expire (Delete) | Keeps reports immediately available for monthly reviews, then moves to cheaper storage, and finally purges after the audit year closes. |

## 3.2 Access Control Model (RBAC)
We implement a segregation of duties between the **Writer** (The Job) and the **Reader** (The Auditor/User).

### A. The Writer (The Job)
* **Identity:** `system-config-report-generator-write-role` (Attached to K8s Pod).
* **Permission:** `s3:PutObject`
* **Constraint:** Can *only* write new files. cannot delete or read old ones (WORM-like compliance).

### B. The Reader (The User)
* **Identity:** `system-config-report-reader-role`
* **Purpose:** This role is assumable by the Platform Team or Auditors to download reports.
* **IAM Policy Definition:**
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowListBucket",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::s3-config-compliance-reports-prod"
        },
        {
            "Sid": "AllowDownloadReports",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::s3-config-compliance-reports-prod/reports/*"
        }
    ]
}

```