flowchart TD
    %% Define Styles
    classDef process fill:#e6fffa,stroke:#2c7a7b,stroke-width:2px
    classDef decision fill:#fffaf0,stroke:#c05621,stroke-width:2px
    classDef fail fill:#fff5f5,stroke:#c53030,stroke-width:2px
    classDef secure fill:#e9d8fd,stroke:#6b46c1,stroke-width:2px

    %% Main Flow
    Start(["🚀 Start Job"]) --> Detect["🔍 Detect Config"]
    Detect --> CreateNS["🛠 Create Temp Namespace"]:::process
    
    CreateNS --> Bootstrap["🔐 Bootstrap RBAC\n(Bind to 'verification-rules' ClusterRole)"]:::secure
    
    Bootstrap --> LoopStart{"For Each Source"}:::decision
    
    %% Loop Logic
    subgraph TestLoop ["Verification Cycle"]
        direction TB
        LoopStart --> PreClean["Clean Route53 State"]
        PreClean --> Deploy["Deploy Test Resource"]
        Deploy --> CheckCreate{"DNS Created?"}:::decision
        
        CheckCreate -- No --> Fail["❌ Failure Detected"]:::fail
        CheckCreate -- Yes --> ModeCheck{"Is 'Sync' Mode?"}:::decision
        
        ModeCheck -- Yes --> K8sDelete["Delete K8s Resource"]
        K8sDelete --> CheckDelete{"DNS Deleted?"}:::decision
        CheckDelete -- No --> Fail
        CheckDelete -- Yes --> Cleanup
        
        ModeCheck -- No (Upsert) --> Cleanup["🧹 Force Route53 Cleanup"]
    end

    %% Teardown & Exit
    Cleanup --> LoopStart
    LoopStart -- Done --> Teardown["🗑 Delete Namespace"]:::process
    Fail --> Teardown
    Teardown --> End(["✅ Exit"]):::process