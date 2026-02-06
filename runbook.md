```mermaid
flowchart TD
    %% Define Styles
    classDef hub fill:#e8eaf6,stroke:#3949ab,stroke-width:2px;
    classDef spoke fill:#e0f2f1,stroke:#00695c,stroke-width:2px;
    classDef storage fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef user fill:#f3e5f5,stroke:#4a148c,stroke-width:2px,stroke-dasharray: 5 5;
    classDef invisible width:0px,height:0px,color:transparent,fill:transparent,stroke:none;
    
    %% CHANGED: Added <br> to the subgraph title
    subgraph PROD_Hub ["Hub Account: prod-primary-<br>sec-control"]
        direction TB
        
        TitleSpacer[ ]:::invisible

        subgraph K8s ["prod-cybsecops-cluster"]
            CronJob("aws-config-report-generator<br>(Python Script)")
        end

        subgraph IAM ["Identity & Access"]
            WriterRole[("system-config-report-<br>generator-write-role<br>(IRSA)")]
            ReaderRole[("staff-aws-config-<br>report-reader-role<br>(User Assumable)")]
        end

        subgraph Data_Layer ["Data Persistence"]
            S3[("S3 Bucket<br>(Retention: 365 Days)")]
        end
    end

    subgraph Targets_All ["Allowed Targets (Entire Organization)"]
        AllSpokes[("Account: All Dev / Stg / Prod / POC<br>(system-config-report-<br>generator-read-role)")]
    end

    User(["Auditor"])

    %% --- EXECUTION FLOW ---
    TitleSpacer ~~~ CronJob
    CronJob ==>|1. Assume via OIDC| WriterRole
    
    WriterRole -->|2. Scan Compliance| AllSpokes

    %% --- S3 WRITE OPERATION ---
    WriterRole == "|3. s3:PutObject (Write Only)|" ==> S3

    %% --- S3 READ OPERATION ---
    User -->|4. Assume Role| ReaderRole
    ReaderRole == "|5. s3:GetObject (Read Only)|" ==> S3

    %% Styling
    class PROD_Hub,K8s,IAM hub;
    class AllSpokes spoke;
    class S3,Data_Layer storage;
    class User,ReaderRole user;
    
    %% Link Styles
    linkStyle 3 stroke:#e65100,stroke-width:3px; 
    linkStyle 5 stroke:#4a148c,stroke-width:3px;
```