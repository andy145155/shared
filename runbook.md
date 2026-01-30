This is a significant improvement to your design document. Below is a refined, professional version that you can copy directly.

I have structured it to clearly contrast the **four architectural options**, specifically detailing the logic flow for each so stakeholders can understand *how* they differ. I also updated the comparison table to be more decisive.

---

# Design Document: AWS Config Compliance Report Automation

## 1. Problem Statement

We currently execute a manual, local Python script to generate weekly AWS Config compliance reports. This process is time-consuming, relies on local credentials (`aws-okta`), and lacks auditability. The goal is to migrate this logic to a fully automated, cloud-native solution on AWS that runs weekly and auto-generates a Jira ticket.

## 2. Requirements

* **Hub-and-Spoke Model:** A central security account (`*-sec-control`) must scan all target accounts.
* **Scalability:** Must handle hundreds of accounts without hitting AWS Lambda's 15-minute timeout.
* **Security:** Must use IAM Roles (not user credentials) with least-privilege permissions.
* **Output:** Generate an Excel report with conditional formatting and upload to S3.

---

## 3. Architecture Options Comparison

We evaluated four approaches to handle the scale and timeout constraints.

### Option 1: Lambda + EventBridge "Sharding" (Original Proposal)

* **Logic:** EventBridge is configured with 4 separate schedules (or targets) triggering the *same* Lambda function at the same time. Each trigger sends a different payload: `{"shard_id": 1, "total_shards": 4}`, `{"shard_id": 2...}`, etc.
* **Flow:**
1. EventBridge fires 4 concurrent Lambda invocations.
2. Each Lambda fetches *all* accounts but processes only its slice (e.g., `if account_index % 4 == shard_id`).
3. All 4 Lambdas write partial CSVs to S3.
4. A final "Merger" Lambda combines them (Complex).


* **Pros:** Bypasses 15-min timeout by splitting work.
* **Cons:** High complexity. "Sharding" logic is brittle; if one shard fails, the report is incomplete. Merging CSVs from multiple sources is error-prone.

### Option 2: Optimized Multi-Threaded Lambda (Recommended)

* **Logic:** A single Lambda function uses Python's `concurrent.futures` to make parallel API calls to hundreds of accounts simultaneously.
* **Flow:**
1. EventBridge triggers 1 Lambda.
2. Lambda fetches account list.
3. Lambda spawns 20+ threads. Each thread assumes a role and checks one account.
4. Because the task is I/O bound (waiting for AWS API), threads are extremely efficient.
5. Results are aggregated in memory and written to S3 in one go.


* **Pros:** Lowest operational overhead. Simple deployment (1 function). Fast (processing 200 accounts takes ~2-3 minutes).
* **Cons:** Hard limit of 15 minutes. If organization grows to 1000+ accounts, this may eventually time out.

### Option 3: Step Functions (Distributed Map)

* **Logic:** AWS Step Functions acts as an orchestrator. It fetches the account list and then "fans out" to trigger a tiny Lambda for *each* account.
* **Flow:**
1. Step Function fetches list of 500 accounts.
2. Step Function "Map State" triggers 500 separate Lambda executions in parallel.
3. Step Function collects all 500 results into a single array.
4. Final step generates the CSV.


* **Pros:** Infinite scalability. Zero timeout risk. Visual error handling per account.
* **Cons:** Higher cost (state transitions). Most complex setup (requires defining state machine JSON/ASL).

### Option 4: Serverless Fargate (ECS)

* **Logic:** Run the original script as a containerized task. Fargate has no 15-minute timeout.
* **Flow:**
1. EventBridge triggers an ECS Task Definition.
2. Fargate provisions a container (takes ~1-2 mins to boot).
3. Script runs sequentially or with simple loops until finished (can run for days).


* **Pros:** proven "Lift and shift" (almost no code changes needed). No timeout limits.
* **Cons:** Slow startup time. Higher cost (paying for vCPU/RAM per second). Overkill for a simple compliance check.

---

## 4. Decision Matrix

| Feature | **Option 1: Lambda Sharding** | **Option 2: Multi-threaded Lambda** | **Option 3: Step Functions** | **Option 4: Fargate** |
| --- | --- | --- | --- | --- |
| **Setup Complexity** | High (Sharding logic + Merging results) | **Low** (Standard Python code) | High (State Machine definition) | Medium (Docker + ECR + ECS) |
| **Scalability** | Medium (Manual shard management) | High (Up to ~800 accts within 15m) | **Infinite** (Distributed Map) | High (No timeouts) |
| **Cost** | Low | **Lowest** | Medium (State transitions) | High (Container compute time) |
| **Maintenance** | Difficult (Debugging partial failures) | **Easy** (Single script) | Medium | Medium (Docker image mgmt) |
| **Execution Time** | < 15 min (per shard) | < 15 min (total) | Unlimited | Unlimited |
| **Verdict** | 🔴 **Discard** | 🟢 **Select (MVP)** | 🟡 **Future Upgrade** | 🔴 **Discard** |

**Conclusion:** We will proceed with **Option 2 (Multi-threaded Lambda)**. Refactoring the code to use `concurrent.futures` allows us to process hundreds of accounts in minutes, well under the 15-minute limit, without the complexity of sharding or managing Docker containers.

---

## 5. IAM Architecture (Hub & Spoke)

### Hub Account (Report Generator)

* **Role Name:** `system-config-report-generator-write-role`
* **Location:** `*-sec-control` (Hub)
* **Permissions:**
* `sts:AssumeRole`: Resource `arn:aws:iam::*:role/system-config-report-generator-read-role`
* `s3:PutObject`: To report bucket.
* `logs:*`: CloudWatch logging.



### Root Account (Discovery)

* **Role Name:** `system-config-report-generator-list-org-role`
* **Location:** Organization Management Account
* **Permissions:**
* `organizations:ListAccountsForParent`
* `organizations:ListOrganizationalUnitsForParent`


* **Trust Policy:** Allow `system-config-report-generator-write-role` to assume this.

### Spoke Accounts (Targets)

* **Role Name:** `system-config-report-generator-read-role`
* **Location:** All Target Accounts
* **Permissions:** (Read-only access for auditing)
* `config:Describe*`, `config:Get*`
* `ec2:Describe*`
* `iam:List*`
* `rds:Describe*`
* `cloudfront:List*`


* **Trust Policy:** Allow `system-config-report-generator-write-role` from the Hub account to assume this.