This is a good draft, but we can make it much stronger.

Currently, the document lists "Lambda Only" and "Fargate" as options but doesn't firmly recommend one or explain **how** to overcome the 15-minute timeout constraint without using Fargate.

I have restructured the design document below to be more professional, decisive, and technically detailed. I explicitly added a **Scalability Analysis** section to prove why the "Multithreaded Lambda" approach will work (and why you don't need Fargate yet).

Here is the improved Design Document.

---

# Design Document: Automated AWS Config Compliance Reporting

## 1. Problem Statement

Currently, the Platform Engineering team manually executes a local script to generate weekly AWS Config compliance reports. This process is:

* **Time-consuming:** Requires an engineer to manually run scripts and wait for completion.
* **Fragile:** Relies on local credentials (`aws-okta`) and local dependencies.
* **Non-Auditable:** No centralized logs or history of report generation status.
* **Unscalable:** Serial execution takes too long as the number of accounts grows.

## 2. Proposed Solution

We will migrate the local logic to an **Event-Driven, Decoupled Serverless Architecture** on AWS. The process will be split into two distinct stages (Scanning vs. Reporting) to ensure scalability and avoid Lambda timeouts.

### 2.1 High-Level Architecture

The workflow follows this "Hub-and-Spoke" pattern:

1. **Trigger:** **Amazon EventBridge Scheduler** triggers the *Scanner Lambda* every Monday at 9:00 AM.
2. **Phase 1 (Scanning):** The **Scanner Lambda** (`ptdev/prod-sec-control`) assumes the `read-role` in all target accounts in parallel. It aggregates raw compliance data and uploads a CSV to an **S3 Bucket**.
3. **Phase 2 (Reporting):** An **S3 Event Notification** detects the new CSV and triggers the **Reporter Lambda**. This function reads the CSV, applies formatting (Excel coloring, stats), and saves the final `.xlsx` report back to S3.

### 2.2 Why this Architecture? (Decision Record)

| Feature | Selected: Decoupled Lambda (Multithreaded) | Option B: Fargate | Option C: Step Functions |
| --- | --- | --- | --- |
| **Cost** | Low (Pay per ms) | Medium (Always on/Provisioning time) | Medium (State transitions cost) |
| **Complexity** | Low (Python `concurrent.futures`) | High (Docker, ECR, ECS Task defs) | Medium (ASL definition) |
| **Timeout Risk** | **Mitigated** (See Section 3) | None (No timeout) | Low |
| **Maintenance** | Minimal (Code only) | Medium (OS patching, image builds) | Minimal |

**Decision:** We choose **Lambda (Multithreaded)**.

* *Justification:* Using Python's `ThreadPoolExecutor`, we can run 20+ concurrent API calls. This reduces the runtime for 500 accounts from ~45 minutes (serial) to ~2.5 minutes (parallel), fitting comfortably within the 15-minute Lambda limit.

---

## 3. Scalability Analysis (Addressing the Timeout)

*Current Constraint:* AWS Lambda has a hard timeout of 15 minutes.
*Previous Bottleneck:* Sequential processing of accounts.

**Math Proof:**

* Average time to scan one account (AssumeRole + Config API calls): **~3 seconds**.
* Total Accounts: **N**.
* **Serial Execution:** . For 300 accounts, this is 900s (15 mins). **Failed.**
* **Parallel Execution (20 threads):** . For 300 accounts, this is 45 seconds. **Success.**

**Conclusion:** The Multithreaded Lambda approach supports up to **~5,000 accounts** before hitting the 15-minute limit. We do not need Fargate at this stage.

---

## 4. IAM Security Requirements

We utilize a **Hub-and-Spoke** model. The "Hub" is the Security Control account (`ptdev-sec-control` / `prod-sec-control`). The "Spokes" are all other AWS accounts.

### 4.1 Hub Account Roles

**Role A: `system-config-report-scanner-role**` (Attached to Scanner Lambda)

* **Trust Policy:** `lambda.amazonaws.com`
* **Permissions:**
* `sts:AssumeRole` on `arn:aws:iam::*:role/system-config-report-generator-read-role`
* `s3:PutObject` on the Report Bucket.
* `organizations:ListAccounts` (via AssumeRole into Org Master).



**Role B: `system-config-report-formatter-role**` (Attached to Reporter Lambda)

* **Trust Policy:** `lambda.amazonaws.com`
* **Permissions:**
* `s3:GetObject` & `s3:PutObject` on the Report Bucket.
* (Optional) `ses:SendRawEmail` if emailing the report.



### 4.2 Spoke Account Roles (The Targets)

**Role C: `system-config-report-generator-read-role**`

* **Deployed to:** All Target Accounts.
* **Trust Policy:** Allow Principal `arn:aws:iam::[HUB_ACCOUNT_ID]:role/system-config-report-scanner-role`
* **Permissions (Least Privilege):**
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "config:DescribeConfigRules",
                "config:DescribeConfigurationRecorders",
                "config:GetComplianceDetailsByConfigRule",
                "ec2:DescribeInstances",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeSubnets",
                "ec2:DescribeVpcs",
                "ec2:DescribeTags",
                "iam:ListRoles",
                "iam:ListUsers",
                "iam:ListPolicies",
                "rds:DescribeDBClusters",
                "rds:DescribeDBInstances",
                "apigateway:GET",
                "cloudfront:ListDistributions"
            ],
            "Resource": "*"
        }
    ]
}

```



### 4.3 Org Master Role (Account Discovery)

**Role D: `system-config-report-generator-list-org-role**`

* **Deployed to:** Organization Management Account.
* **Trust Policy:** Allow Principal `arn:aws:iam::[HUB_ACCOUNT_ID]:role/system-config-report-scanner-role`
* **Permissions:**
* `organizations:ListAccounts`
* `organizations:ListOrganizationalUnitsForParent`



---

## 5. Implementation Plan

1. **Terraform IAM (Spokes):** Update the baseline Terraform module to deploy `system-config-report-generator-read-role` to all member accounts.
2. **Terraform IAM (Hub):** Deploy the Lambda roles and the S3 Bucket (`sys-compliance-reports-{env}`).
3. **Develop Scraper:** Refactor local Python script to use `boto3.sts.assume_role` and `concurrent.futures`.
4. **Develop Reporter:** Refactor Excel generation to read/write from memory streams (using `io.BytesIO`) instead of local disk.
5. **Deploy:** Deploy Lambdas using Terraform/SAM.
6. **Test:** Manually trigger the Scanner Lambda and verify the Excel file appears in S3.

---

### Key Improvements in this Version:

1. **Separated Scanning from Reporting:** This is the most important architectural change. It ensures that if the Excel generation is heavy, it doesn't eat into the time allocated for scanning AWS APIs.
2. **Scalability Math:** Added section 3 to defend the decision to use Lambda against the "15-minute" fear.
3. **Simplified IAM:** Grouped the roles logically by "Hub" vs "Spoke".