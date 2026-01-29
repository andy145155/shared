Here is a system design level README for your repository. It focuses on the architecture, data flow, and the "Map-Reduce" pattern your Lambda uses.

---

# AWS Config Compliance Reporter

## Overview

This system is a serverless data pipeline designed to aggregate AWS Config compliance status across a multi-account organization. It fetches compliance rules from dispersed AWS accounts and consolidates them into a single, formatted Excel dashboard for security and operations teams.

## Architecture

The system utilizes a **serverless Map-Reduce architecture** orchestrated by AWS Lambda and S3. This design allows it to scale to hundreds of accounts without hitting Lambda timeout limits by splitting the work into parallel shards.

### High-Level Data Flow

1. **Trigger (Map Phase):** EventBridge triggers multiple parallel Lambda executions ("workers"), each assigned a specific shard of accounts.
2. **Process:** Each worker assumes a cross-account IAM role, fetches compliance data from AWS Config, and saves the raw results to an intermediate S3 bucket.
3. **Aggregation (Reduce Phase):** A final Lambda execution consolidates all intermediate files from S3, deduplicates the data, and generates a formatted Excel report.

---

## Event Schema (Input)

The Lambda function is triggered by an EventBridge Rule. The payload dictates the mode of operation (`batch` vs `final`) and the scope of work.

```json
{
  "accounts": [
    { "account_id": "123456789012", "account_name": "prod-app-01" },
    { "account_id": "987654321098", "account_name": "prod-db-01" }
  ],
  "group_id": "2023-10-27", 
  "mode": "batch",
  "role_name": "configreport-read-role",
  "shard_id": "01"
}

```

| Field | Description |
| --- | --- |
| `mode` | Controls execution logic. **`batch`** (default) fetches data; **`final`** aggregates data. |
| `group_id` | Unique identifier for the report run (usually the Date), used as the S3 folder prefix. |
| `accounts` | List of target accounts for this specific shard. |
| `shard_id` | Unique ID for the batch worker to prevent filename collisions in S3. |
| `role_name` | The IAM role name to assume in target accounts (e.g., `configreport-read-role`). |

---

## Execution Modes

### 1. Batch Mode (The "Map" Phase)

* **Responsibility:** Data Collection.
* **Action:**
1. Iterates through the provided list of `accounts`.
2. Assumes `configreport-read-role` in the target account.
3. Calls AWS Config APIs (`DescribeConfigRules`, `GetComplianceDetailsByConfigRule`).
4. Extracts tags (specifically `mox.*` tags) for resource ownership.


* **Output:** uploads a JSON file to `s3://<bucket>/batches/<group_id>/<shard_id>.json`.

### 2. Final Mode (The "Reduce" Phase)

* **Trigger:** A separate event with `"mode": "final"`.
* **Responsibility:** Aggregation & Reporting.
* **Action:**
1. Scans `s3://<bucket>/batches/<group_id>/` for all worker files.
2. Merges JSON datasets and filters out duplicate headers.
3. Calculates compliance statistics (Prod vs. Non-Prod ratios).
4. Applies conditional formatting (Red/Yellow/Green) to an Excel sheet.


* **Output:** Uploads the final report `ConfigRule_<Date>.xlsx` to the S3 report bucket.

---

## IAM & Security

The system operates on a **Hub-and-Spoke** security model.

* **Hub (Lambda):** Requires `sts:AssumeRole` permission to access spoke accounts and `s3:PutObject/GetObject` access to the report bucket.
* **Spoke (Target Accounts):** Must have an IAM Role (e.g., `configreport-read-role`) with a Trust Policy allowing the Hub Lambda to assume it.
* **Required Permissions:**
* `config:DescribeConfigRules`
* `config:GetComplianceDetailsByConfigRule`
* `config:DescribeConfigurationRecorders`





## Infrastructure Requirements

* **Runtime:** Python 3.9+
* **Environment Variables:**
* `REPORT_BUCKET`: Target S3 bucket for intermediate files and final reports.
* `REPORT_PREFIX`: (Optional) Prefix for S3 objects.