This PR introduces a new, comprehensive Python-based automation suite for verifying the health and security of the Istio service mesh.

Instead of manual verification, this script automates the setup of test applications, validates the Control Plane status, and explicitly tests strict mTLS enforcement policies (allowing mesh-to-mesh traffic while blocking legacy-to-mesh traffic).

🚀 Key Features
1. Control Plane Verification (verify_istio_control_plane)
Deployment Status: verifies the istiod deployment is available and ready.

Proxy Synchronization: Checks for STALE proxies using istioctl proxy-status with retry logic to handle transient sync delays.

Configuration Analysis: Runs istioctl analyze to detect potential validation issues in the cluster.

2. mTLS Security Testing (run_istio_mtls_tests)
Implements a "Strict mTLS" validation suite that runs two specific connectivity scenarios:

✅ Allowed: Verifies that a mesh-enabled pod (Sidecar) can successfully communicate with another mesh-enabled pod.

❌ Blocked: Verifies that a non-mesh pod (No-Sidecar/Legacy) is forbidden from communicating with a mesh-enabled pod.

Note: Includes logic to dynamically resolve Pod names via labels to ensure kubectl exec commands target the correct containers.

3. Test Infrastructure (setup_test_apps)
Automates the deployment of Client and Target test applications via YAML templates.

Includes robust "Wait" logic to ensure Deployments and Pods are fully Ready before tests begin.

Verifies successful sidecar injection on targeted namespaces.

⚙️ Configuration & Linting Updates
Updated the Pylint configuration to align with Python PEP 8 standards and project requirements:

Indentation: Changed from 2 spaces to 4 spaces for better readability.

Rules: Disabled C0114 (Missing module docstring) to reduce noise in file headers.

🛡️ Error Handling
Implemented a Fail-Fast architecture.

Replaced generic exceptions with specific subprocess.CalledProcessError handling for command failures and RuntimeError for logical verification failures.

Ensures specific exit codes are returned to CI/CD pipelines upon failure.

🧪 Verification
How to run locally: