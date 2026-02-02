I have revised the **Requirements** and **Decision Log (ADR)** documents to align with Day's feedback.

### **Revisions Made:**

1. **Requirements:** Converted to a **Target Changes Table** format (matching your "Commit Signing" example). I made the metrics concrete (e.g., "> 15 minutes", "Zero manual touchpoints").
2. **Decision Log:** Consolidated **all** architecture details, logic flows, and pros/cons into a single **comprehensive table** so stakeholders don't have to read long paragraphs.

---

### **Document 1: Requirements Definition**

## **Target Capabilities & Requirements**

The following table defines the mandatory elements for the AWS Config Compliance automation project.

| Category | Requirement | Metric / Verification | Target Implementation | Current State |
| --- | --- | --- | --- | --- |
| **Automation** | **Zero-Touch Execution**<br>

<br>The system must generate and deliver the report automatically on a scheduled basis without human intervention. | **Frequency:** Weekly (Mon 9AM HKT)<br>

<br>**Manual Steps:** 0 | **Kubernetes CronJob** triggered by cluster schedule. Report output is automatically uploaded to S3. | **Manual:** Engineer runs Python script locally on laptop. |
| **Performance** | **Execution Duration**<br>

<br>The solution must support long-running processes that exceed AWS Lambda's hard limits to accommodate future growth. | **Max Duration:** > 15 minutes<br>

<br>**Account Capacity:** Support 500+ accounts | **Containerized Workload** (Pod) running on EKS. No hard timeout limits applied to the process. | **Limited:** Local script runs until finished, but migrating to Lambda would impose a 15-min cap. |
| **Security** | **Identity Management**<br>

<br>Eliminate long-lived access keys. Use temporary, rotated credentials for all API access. | **Creds Type:** STS Temporary Tokens<br>

<br>**Keys on Disk:** 0 | **IRSA (IAM Roles for Service Accounts):** Pod authenticates via OIDC. Hub-and-Spoke role assumption for cross-account access. | **Risk:** Relies on `aws-okta` and local `~/.aws/credentials` files on user laptops. |
| **Output** | **Report Integrity**<br>

<br>The output must match the current Excel format exactly, including conditional formatting and tab structure. | **Format:** `.xlsx`<br>

<br>**Accuracy:** 100% match with legacy script | **Python Pandas/OpenPyXL:** Logic ported to container to generate identical binary Excel file in memory. | **Manual:** Script generates file locally; engineer manually uploads or shares it. |
| **Scalability** | **Concurrency**<br>

<br>The system must process accounts in parallel to ensure the report creates within a reasonable maintenance window. | **Concurrency:** 20+ Threads<br>

<br>**Total Runtime:** < 30 mins (Target) | **Multi-threading:** `concurrent.futures` implementation within the Python container. | **Serial:** Current script runs sequentially or with limited local parallelism. |

---

### **Document 2: Decision Log (ADR)**

## **Architecture Options & Decision Matrix**

We evaluated four options to host the compliance engine. **Option 5 (Kubernetes CronJob)** was selected to meet the requirement of supporting execution times > 15 minutes.

| Option | Architecture Logic | Pros | Cons | Verdict |
| --- | --- | --- | --- | --- |
| **1. Lambda Sharding** | • EventBridge fires 4 concurrent Lambdas.<br>

<br>• Each Lambda processes a "shard" (e.g., `index % 4`).<br>

<br>• A final "Merger" function combines 4 CSVs. | • Bypasses 15-min timeout.<br>

<br>• Low cost (Serverless). | • **High Complexity:** Merging logic is brittle.<br>

<br>• **Partial Failures:** Hard to debug if only Shard 3 fails. | 🔴 **Discard** |
| **2. Multi-threaded Lambda** | • Single Lambda spawns 20 threads.<br>

<br>• Aggregates results in-memory.<br>

<br>• Writes final report to S3. | • **Simple:** Single script deployment.<br>

<br>• **Fast:** Low operational overhead. | • **Hard Limit:** FAILS if execution exceeds **15 minutes**.<br>

<br>• **Risk:** Will break as Org grows > 800 accounts. | 🔴 **Discard** (Fails Requirement) |
| **3. Step Functions** | • "Distributed Map" state triggers 500 tiny Lambdas (one per account).<br>

<br>• Step Function aggregates results. | • **Infinite Scale:** No timeout limits.<br>

<br>• **Visual Debugging:** See exactly which account failed. | • **Cost:** High (State transitions).<br>

<br>• **Complexity:** Requires ASL (Amazon States Language) definition. | 🟡 **Backup Option** |
| **4. Fargate Task** | • EventBridge triggers a standalone Fargate Container.<br>

<br>• Runs script until completion. | • **No Timeouts:** Can run for days.<br>

<br>• **Simple Porting:** Lift-and-shift of local script. | • **Slow:** Startup takes ~2 mins.<br>

<br>• **Cost:** Higher per-execution cost than existing cluster. | 🔴 **Discard** |
| **5. K8s CronJob (EKS)** | • **Scheduler:** K8s CronJob triggers Pod on `ptdev-cybsecops`.<br>

<br>• **Auth:** Pod assumes IAM Role via **IRSA**.<br>

<br>• **Run:** Script runs on existing worker nodes. | • **No Timeouts:** Meets performance requirement.<br>

<br>• **Sunk Cost:** Utilizes spare cluster capacity (Free).<br>

<br>• **Standard:** Aligns with Platform team's K8s strategy. | • **Setup:** Requires Dockerfile & Helm Chart.<br>

<br>• **Deps:** Requires OIDC/IRSA setup (already planned). | 🟢 **Selected** |

---

### **Next Steps**

1. **Approve:** Confirm these tables meet the "concrete metrics" and "consolidated view" requests.
2. **Deploy:** Proceed with **Phase 1 (IAM Foundation)** as outlined in the Implementation Plan.