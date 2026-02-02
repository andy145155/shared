# 1. Requirements Definition

## Target Capabilities & Metrics
The following table defines the mandatory elements for the AWS Config Compliance automation project, establishing concrete metrics for success.

| **Category** | **Requirement** | **Metric / Verification** | **Target Implementation** | **Current State** |
| :--- | :--- | :--- | :--- | :--- |
| **Automation** | **Zero-Touch Execution**<br>The system must generate and deliver the report automatically on a scheduled basis without human intervention. | • **Frequency:** Weekly (Mon 09:00 HKT)<br>• **Manual Steps:** 0 | **Kubernetes CronJob** triggered by cluster schedule. Report output is automatically uploaded to S3. | **Manual:** Engineer runs Python script locally on laptop. |
| **Performance** | **Execution Duration**<br>The solution must support long-running processes that exceed AWS Lambda's hard limits to accommodate future growth. | • **Max Duration:** > 15 minutes<br>• **Account Capacity:** Support 500+ accounts | **Containerized Workload (Pod)** running on EKS. No hard timeout limits applied to the process. | **Limited:** Local script runs until finished, but migrating to standard Lambda would impose a 15-min cap. |
| **Security** | **Identity Management**<br>Eliminate long-lived access keys. Use temporary, rotated credentials for all API access. | • **Creds Type:** STS Temporary Tokens<br>• **Long-lived Keys on Disk:** 0 | **IRSA (IAM Roles for Service Accounts):** Pod authenticates via OIDC. Hub-and-Spoke role assumption for cross-account access. | **Risk:** Relies on `aws-okta` and local `~/.aws/credentials` files on user laptops. |
| **Output** | **Report Integrity**<br>The output must match the current Excel format exactly, including conditional formatting and tab structure. | • **Format:** `.xlsx`<br>• **Accuracy:** 100% match with legacy script | **Python Pandas/OpenPyXL:** Logic ported to container to generate identical binary Excel file in memory. | **Manual:** Script generates file locally; engineer manually uploads or shares it. |
| **Scalability** | **Concurrency**<br>The system must process accounts in parallel to ensure the report creates within a reasonable maintenance window. | • **Concurrency:** 20+ Threads<br>• **Total Runtime:** < 30 mins (Target) | **Multi-threading:** `concurrent.futures` implementation within the Python container. | **Serial:** Current script runs sequentially or with limited local parallelism. |

---

# 2. Architecture Decision Record (ADR)

## Options Evaluated & Decision Matrix
We evaluated four options to host the compliance engine. **Option 5 (Kubernetes CronJob)** was selected to meet the specific requirement of supporting execution times > 15 minutes.

| **Option** | **Architecture Logic** | **Pros** | **Cons** | **Verdict** |
| :--- | :--- | :--- | :--- | :--- |
| **1. Lambda Sharding** | • EventBridge fires 4 concurrent Lambdas.<br>• Each Lambda processes a "shard" (e.g., `index % 4`).<br>• A final "Merger" function combines 4 CSVs. | • Bypasses 15-min timeout.<br>• Low cost (Serverless). | • **High Complexity:** Merging logic is brittle.<br>• **Partial Failures:** Hard to debug if only Shard 3 fails. | 🔴 **Discard** |
| **2. Multi-threaded Lambda** | • Single Lambda spawns 20 threads.<br>• Aggregates results in-memory.<br>• Writes final report to S3. | • **Simple:** Single script deployment.<br>• **Fast:** Low operational overhead. | • **Hard Limit:** FAILS if execution exceeds **15 minutes**.<br>• **Risk:** Will break as Org grows > 800 accounts. | 🔴 **Discard**<br>*(Fails Requirement)* |
| **3. Step Functions** | • "Distributed Map" state triggers 500 tiny Lambdas (one per account).<br>• Step Function aggregates results. | • **Infinite Scale:** No timeout limits.<br>• **Visual Debugging:** See exactly which account failed. | • **Cost:** High (State transitions).<br>• **Complexity:** Requires ASL (Amazon States Language) definition. | 🟡 **Backup Option** |
| **4. Fargate Task** | • EventBridge triggers a standalone Fargate Container.<br>• Runs script until completion. | • **No Timeouts:** Can run for days.<br>• **Simple Porting:** Lift-and-shift of local script. | • **Slow:** Startup takes ~2 mins.<br>• **Cost:** Higher per-execution cost than existing cluster. | 🔴 **Discard** |
| **5. K8s CronJob (EKS)** | • **Scheduler:** K8s CronJob triggers Pod on `ptdev-cybsecops`.<br>• **Auth:** Pod assumes IAM Role via **IRSA**.<br>• **Run:** Script runs on existing worker nodes. | • **No Timeouts:** Meets performance requirement.<br>• **Sunk Cost:** Utilizes spare cluster capacity (Free).<br>• **Standard:** Aligns with Platform team's K8s strategy. | • **Setup:** Requires Dockerfile & Helm Chart.<br>• **Deps:** Requires OIDC/IRSA setup (already planned). | 🟢 **Selected** |