Hi team, I’d like your input on the run_ingress_tests automation.

Context: The current test attempts to verify Ingress functionality by running a curl command from inside a pod within the cluster, targeting the Ingress Gateway’s internal IP.

The Issue: This is failing consistently in the app cluster with a TLS handshake error (SSL routines::unexpected eof while reading), likely due to how the mesh handles internal traffic hair-pinning to the Gateway.

Proposal: I suggest we drop this specific test case. Reasoning: Testing Ingress from inside the cluster is technically an antipattern. Ingress is designed for external-to-internal traffic. simulating this via internal hairpinning introduces artificial network complexity (TLS/mTLS conflicts) that doesn't reflect real-world usage.