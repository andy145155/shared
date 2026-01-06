# External DNS Release Verification

This tool provides automated verification for `external-dns` releases on EKS. It is designed to run as an **ArgoCD PostSync Job** in non-production environments (e.g., `ptdev`, `dev`, `stg`) to certify that a new version of `external-dns` is fully functional before it is promoted to production environments.

## Overview

This automation replaces manual checks with a deterministic verification process. It handles the two primary operation modes of `external-dns`:

1. **Sync Mode:** Verifies the full lifecycle. This proves `external-dns` can **add** and **remove** records.
2. **Upsert-Only Mode:** Verifies creation only. Since `external-dns` is forbidden from deleting records in some clusters, the verifier creates the record, verifies it, and then **self-cleans** the Route53 record using the AWS API to prevent polluting the zone with test data.

## Architecture & Design

The verification process has been consolidated. The Verifier Job now resides within the `external-dns` namespace to simplify permission management and locality.

* **Namespace: `external-dns**`
* **External-DNS Pod:** The actual application being tested.
* **Verifier Job:** The ArgoCD PostSync hook that orchestrates the test.
* **ServiceAccount:** The identity used by the Verifier Job.


* **Namespace: `verification-external-dns**` (Target Namespace)
* **Test Service:** A temporary Kubernetes Service (`external-dns-test`) created by the Verifier Job to trigger DNS record creation.



### Data Flow

1. **Deploy:** The Verifier Job creates a `Test Service` in the `verification-external-dns` namespace.
2. **Watch:** The Verifier Job watches the `External-DNS Pod` logs or status.
3. **Create Record:** `external-dns` detects the new Service and creates a TXT/A record in AWS Route53.
4. **Poll & Verify:** The Verifier Job polls the Route53 API to confirm the record exists and matches the expected value.

## Verification Logic

The verification process follows this decision logic:

1. **Start:** PostSync Job Triggered.
2. **Version Check:** Confirms the running Pod version matches the deployed version.
* *Mismatch:* **FAIL** (Alert Version Mismatch).
* *Match:* Proceed to Step 3.


3. **Step 1: Create Test Service:** Deploys a fixture service.
4. **Verify Route53 Creation:**
* *Timeout/Not Found:* **FAIL** (DNS Creation Failed).
* *Found:* Proceed to Step 5.


5. **Step 2: Delete Test Service:** Removes the fixture service.
6. **Check Mode (`UPSERT_ONLY_MODE`?):**
* **NO (Standard Sync):**
* Verify Route53 Deletion.
* *Record Persists:* **FAIL** (DNS Deletion Failed).
* *Record Gone:* **SUCCESS** (Full Lifecycle Verified).


* **YES (Upsert Only):**
* Skip deletion verification (as `external-dns` will not delete it).
* **Step 3: Force Manual Cleanup:** The script uses Boto3 to remove the Route53 record directly.
* **SUCCESS** (Creation Verified & Cleaned Up).





## Safety Mechanisms

1. **Pre-Flight Cleanup:** Before starting, the script checks if the test DNS record already exists (from a previous failed run) and forcibly removes it to ensure a clean test state.
2. **Graceful Shutdown:** The script catches `SIGTERM` signals (e.g., if the job is cancelled) and attempts to clean up the Kubernetes Service and Route53 record immediately.

## Prerequisites

### AWS Permissions

The Pod running the `verification-external-dns` container image requires an IAM Role with the following Route53 permissions:

* `route53:ListResourceRecordSets`: Required for verification (checking if records exist).
* `route53:ChangeResourceRecordSets`: Required **only** if running in `UPSERT_ONLY_MODE` (to perform self-cleanup via Boto3).

### Kubernetes RBAC

Since the Verifier Job runs in the `external-dns` namespace, the ServiceAccount requires the following permissions:

* **ClusterRole / Role (Target Namespace `verification-external-dns`):**
* `create`, `get`, `delete` on `Services` (To manage the test fixture).


* **Role (Local Namespace `external-dns`):**
* `get`, `list` on `Pods` (To verify the running `external-dns` version).



---

### Runbook

[Link to your internal Confluence/Wiki Runbook]

### Changes for "Use"

If you would like me to generate the **Mermaid.js code** to render the flowchart or architecture diagram directly in your README (so you don't have to rely on screenshots), let me know!