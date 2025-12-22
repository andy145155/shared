flowchart TD
    %% --- Soft Color Palette (Safe for all renderers) ---
    classDef k8s fill:#e0f2fe,stroke:#38bdf8,stroke-width:2px,color:#0c4a6e;
    classDef aws fill:#fff7ed,stroke:#f97316,stroke-width:2px,color:#7c2d12;
    classDef plain fill:#f8fafc,stroke:#94a3b8,stroke-width:1px,color:#334155;
    classDef hidden display:none;

    subgraph K8s_Cluster [EKS Cluster]
        direction TB
        subgraph NS_ExtDNS [Namespace: external-dns]
            Controller[External-DNS Pod]:::k8s
        end
        
        subgraph NS_Toolkit [Namespace: af-toolkit]
            Job[Verifier Job]:::k8s
            SA[ServiceAccount]:::plain
        end
        
        subgraph NS_Verify [Namespace: verification-external-dns]
            direction TB
            %% Invisible spacer to push the node down
            Spacer[ ]:::hidden
            TestSvc[Test Service<br>external-dns-test]:::k8s
            Spacer ~~~ TestSvc
        end
    end
    
    subgraph AWS [AWS Cloud]
        R53[Route53 API]:::aws
    end

    %% Flows (Renamed to avoid Markdown List errors)
    Job -- "Step 1: Deploy (Cross-NS RBAC)" --> TestSvc
    Controller -- "Step 2: Watch Service" --> TestSvc
    Controller -- "Step 3: Create Record" --> R53
    Job -- "Step 4: Poll & Verify" --> R53