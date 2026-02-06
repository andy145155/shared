```mermaid
flowchart TD
    %% Define Styles
    classDef hub fill:#e8eaf6,stroke:#3949ab,stroke-width:2px;
    classDef master fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
    classDef spoke fill:#e0f2f1,stroke:#00695c,stroke-width:2px;
    classDef storage fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef user fill:#f3e5f5,stroke:#4a148c,stroke-width:2px,stroke-dasharray: 5 5;
    classDef invisible width:0px,height:0px,color:transparent,fill:transparent,stroke:none;
    
    subgraph PROD_Hub ["Hub Account: prod-primary-<br>sec-control"]
        direction TB
        
        TitleSpacer[ ]:::invisible

        subgraph K8s ["prod-cybsecops-cluster"]
            CronJob("aws-config-report-generator<br>(Python K8S CronJob)")
        end

        subgraph IAM ["Identity & Access"]
            WriterRole[("system-config-report-<br>generator-write-role<br>(IRSA)")]
            ReaderRole[("staff-aws-config-<br>report-reader-role<br>(User Assumable)")]
        end

        subgraph Data_Layer ["Data Persistence"]
            S3[("S3 Bucket<br>(Retention: 365 Days)")]
        end
    end

    subgraph Org_Master ["Root Org Master:<br> root-org-master"]
        ListRole[("system-config-report-<br>generator-list-org-role")]
    end

    subgraph Targets_All ["Allowed Targets <br> (Entire Organization)"]
        AllSpokes[("Account: All Dev / Stg / Prod / POC<br>(system-config-report-<br>generator-read-role)")]
    end

    User(["Auditor"])

    %% --- EXECUTION FLOW ---
    %% Link 0
    TitleSpacer ~~~ CronJob
    %% Link 1
    CronJob ==>|1. Assume via OIDC| WriterRole
    
    %% Discovery Step (New)
    %% Link 2
    WriterRole -->|2. List Org Accounts| ListRole

    %% Audit Flow
    %% Link 3
    WriterRole -->|3. Scan Compliance| AllSpokes

    %% --- S3 WRITE OPERATION ---
    %% Link 4 (Needs Orange Style)
    WriterRole == "|4. s3:PutObject (Write Only)|" ==> S3

    %% --- S3 READ OPERATION ---
    %% Link 5
    User -->|5. Assume Role| ReaderRole
    %% Link 6 (Needs Purple Style)
    ReaderRole == "|6. s3:GetObject (Read Only)|" ==> S3

    %% Styling
    class PROD_Hub,K8s,IAM hub;
    class Org_Master,ListRole master;
    class AllSpokes spoke;
    class S3,Data_Layer storage;
    class User,ReaderRole user;
    
    %% Link Styles (Indices updated: 4 is Write, 6 is Read)
    linkStyle 4 stroke:#e65100,stroke-width:3px; 
    linkStyle 6 stroke:#4a148c,stroke-width:3px;
```