<div align="center">

```mermaid
flowchart TD
    %% --- Styling Definitions ---
    classDef default fill:#fff,stroke:#333,stroke-width:1px,rx:5px,ry:5px;
    classDef primary fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
    classDef success fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef warning fill:#fff3e0,stroke:#ef6c00,stroke-width:2px;
    classDef error fill:#ffebee,stroke:#c62828,stroke-width:2px;
    classDef secure fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;

    %% --- Initialization Phase ---
    Start([🚀 Start Job]) --> Detect(🔍 Detect Config)
    
    Detect -- No Pod --> FailInit[❌ Fail: No Pods]:::error
    Detect --> Setup(🛠 Create Temp Namespace):::primary
    
    Setup --> Bootstrap(🔐 Bootstrap RBAC):::secure
    Bootstrap --> LoopStart{{ 🔄 For Each Source }}:::warning

    %% --- The Verification Loop ---
    subgraph Loop ["Verification Logic"]
        direction TB
        LoopStart --> PreClean(🧹 Clean Route53)
        PreClean --> Deploy(🚀 Deploy Test Resource)
        Deploy --> CheckCreate{DNS Created?}
        
        %% Success Path
        CheckCreate -- Yes --> SyncCheck{Sync Mode?}
        SyncCheck -- Yes --> K8sDelete(🗑 Delete K8s Res)
        K8sDelete --> CheckDelete{DNS Deleted?}
        
        CheckDelete -- Yes --> Cleanup
        SyncCheck -- No/Upsert --> Cleanup(✨ Cleanup)
        
        %% Error Paths
        CheckCreate -- No --> FailLoop[❌ Fail: Timeout]:::error
        CheckDelete -- No --> FailLoop
    end

    %% --- Loop Back & Termination ---
    Cleanup --> LoopStart
    
    LoopStart -- Done --> Teardown(🗑 Delete Namespace):::primary
    FailLoop --> Teardown
    FailInit --> Teardown
    
    Teardown --> End([✅ Success]):::success

    %% --- Apply Styles ---
    class Start,End,Detect,PreClean,Deploy,K8sDelete,Cleanup default
    
    %% Hide the subgraph border for a cleaner look
    style Loop fill:none,stroke:none