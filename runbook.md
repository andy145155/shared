flowchart TD
    %% Define Styles
    classDef success fill:#e6fffa,stroke:#2c7a7b,stroke-width:2px;
    classDef fail fill:#fff5f5,stroke:#c53030,stroke-width:2px;
    classDef process fill:#ebf8ff,stroke:#2b6cb0,stroke-width:1px;
    classDef secure fill:#e9d8fd,stroke:#6b46c1,stroke-width:2px;

    %% Setup Phase
    Start(["Start Verification"]) --> Detect["🔍 Detect ExternalDNS Config"]
    
    Detect -- No Pod Found --> FailInit["FAIL: No Running Pods"]:::fail
    Detect -- Success --> Setup["🛠 Create Temp Namespace"]:::process

    %% NEW STEP: RBAC Bootstrapping
    Setup --> Bootstrap["🔐 Bootstrap RBAC\n(Bind to ClusterRole)"]:::secure
    Bootstrap --> LoopStart{"For Each Source"}

    %% Verification Loop
    subgraph TestLoop ["Verification Cycle"]
        LoopStart --> PreClean["Ensure Clean Route53 State"]
        PreClean --> Deploy["🚀 Deploy Test Resource"]
        Deploy --> CheckCreate{"DNS Created?"}
        
        CheckCreate -- Timeout --> FailCreate["FAIL: Propagation Timeout"]:::fail
        CheckCreate -- Yes --> ModeCheck{"Is 'Sync' Mode?"}
        
        ModeCheck -- Yes --> K8sDelete["Delete K8s Resource"]
        K8sDelete --> CheckDelete{"DNS Deleted?"}
        CheckDelete -- Timeout --> FailDelete["FAIL: Deletion Timeout"]:::fail
        CheckDelete -- Yes --> Cleanup
        
        ModeCheck -- No (Upsert) --> Cleanup["🧹 Force Route53 Cleanup"]
    end

    %% Teardown Phase
    Cleanup --> LoopStart
    LoopStart -- All Done --> Teardown["🗑 Delete Temp Namespace"]:::process
    Teardown --> Success(["✅ SUCCESS"]):::success