This is a great addition, especially given your background with EKS and platform engineering. Since you are already comfortable with Kubernetes, running this as a **CronJob** inside your existing cluster is a very strong contender because it solves the timeout issue without the cold-start latency or cost of Fargate.

Here are the updated **Architecture Options** and **Decision Matrix** sections including Kubernetes.

---

### Option 5: Kubernetes CronJob (EKS)

* **Logic:** Leverage your existing EKS cluster to schedule the script as a native Kubernetes `CronJob`. The container runs on existing worker nodes.
* **Authentication:** Uses **IRSA (IAM Roles for Service Accounts)**. The Pod acts as the identity, assuming the IAM role via OIDC, eliminating the need for access keys.
* **Flow:**
1. K8s Controller triggers the `CronJob` resource on the schedule (e.g., `schedule: "0 9 * * 1"`).
2. K8s spins up a Pod using your Docker image.
3. The Pod assumes the IAM Role (via ServiceAccount annotation).
4. Script runs until completion (no 15-minute timeout).
5. Pod terminates; logs are sent to your cluster's logging solution (e.g., Fluentbit -> CloudWatch/Datadog).


* **Pros:** Zero timeout limits. Highly portable. easy to debug (just `kubectl logs`). Uses existing compute capacity (cost-efficient if you have spare capacity on nodes).
* **Cons:** Requires maintaining a Docker image registry (ECR). Requires configuring IRSA (OIDC provider + Trust Relationship). Slightly more "moving parts" (Manifests, Helm charts) than a simple Python script in Lambda.

---

### Updated Decision Matrix

| Feature | **Option 1: Lambda Sharding** | **Option 2: Multi-threaded Lambda** | **Option 3: Step Functions** | **Option 4: Fargate** | **Option 5: K8s CronJob** |
| --- | --- | --- | --- | --- | --- |
| **Setup Complexity** | High | **Low** (Script only) | High (State Machine) | Medium (Docker) | Medium (Docker + Helm/Manifests) |
| **Scalability** | Medium | High (< 800 accts) | **Infinite** | High | High (Dependent on Node capacity) |
| **Cost** | Low | **Lowest** | Medium | High (Dedicated Task) | **Low/Sunk** (Uses existing Cluster capacity) |
| **Maintenance** | Difficult | **Easy** | Medium | Medium | Medium (Image patching required) |
| **Timeout Risk** | Low | Medium (15m limit) | **None** | **None** | **None** |
| **Verdict** | 🔴 Discard | 🟢 **Select (MVP)** | 🟡 Future Upgrade | 🔴 Discard | 🔵 **Strong Alternative** |

**Updated Conclusion:**
We will proceed with **Option 2 (Multi-threaded Lambda)** for the MVP because it requires the least amount of infrastructure setup (no Dockerfiles, ECR, or Helm charts required).

* *However*, if we approach the 15-minute timeout limit in the future, **Option 5 (K8s CronJob)** is the preferred backup plan over Fargate, as it leverages our existing EKS investment and IRSA security model without the per-task overhead of Fargate.

---

### Updated Logic Flow (Visual Comparison)

**Option 2: Lambda (Selected)**
`EventBridge Rule` → `Trigger Lambda` → `(Spawn 20 Threads)` → `Write to S3`

**Option 5: K8s CronJob (Alternative)**
`K8s CronJob Schedule` → `Pod Created` → `Assume IRSA Role` → `Run Script (Linear or Threaded)` → `Write to S3` → `Pod Terminated`