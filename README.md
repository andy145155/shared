Hi team, I’d like your input on the run_ingress_tests automation.

Context: The current test attempts to verify Ingress functionality by running a curl command from inside a pod within the cluster, targeting the Ingress Gateway’s internal IP.

The Issue: This is failing consistently in the app cluster with a TLS handshake error (SSL routines::unexpected eof while reading), likely due to how the mesh handles internal traffic hair-pinning to the Gateway.

Proposal: I suggest we drop this specific test case. Reasoning: Testing Ingress from inside the cluster is technically an antipattern. Ingress is designed for external-to-internal traffic. simulating this via internal hairpinning introduces artificial network complexity (TLS/mTLS conflicts) that doesn't reflect real-world usage.



Here is the updated draft. I have added a section specifically detailing the `curl` mechanics—how it bypasses DNS using `--resolve` to force traffic to the internal ClusterIP.

### Option 2: Technical Breakdown (Updated with specific `curl` details)

**Subject:** Issue with Ingress Verification in App Cluster & Proposal to Remove

I wanted to share technical details on why the `run_ingress_tests` automation is failing in the app cluster and propose we deprecate it.

**How the test is implemented:**
The test verifies Ingress connectivity by running a `curl` command from inside a pod. To simulate external access, it manually overrides DNS resolution using the `--resolve` flag:

```bash
# General pattern used in the script
curl -k --resolve <INGRESS_HOST>:443:<INGRESS_GATEWAY_CLUSTER_IP> https://<INGRESS_HOST>/...

```

Specifically, the script does the following:

1. **Fetches the Internal IP:** It queries the `istio-ingressgateway` service to get its internal ClusterIP (e.g., `172.20.x.x`).
2. **Forces Resolution:** It constructs a curl command that forces the external domain (e.g., `verification-istio.example.com`) to resolve directly to that internal ClusterIP.
3. **Executes Internally:** It runs this command via `kubectl exec` from inside a client pod within the mesh.

**The Problem:**
This test fails consistently in the **app cluster** with a TLS handshake error:
`curl: (35) TLS connect error: error:0A000126:SSL routines::unexpected eof while reading`

**Root Cause:**
By using `--resolve` to target the Ingress Gateway's internal IP from *inside* the cluster, we are forcing "hairpin" traffic. The client pod (and its sidecar) sees traffic destined for an internal IP and attempts to handle it differently than true external ingress traffic. This causes a conflict during the TLS handshake (likely between the sidecar's mTLS expectations and the Gateway's TLS termination), resulting in the connection reset.

**Proposal:**
**I recommend we drop this test case.**
Testing Ingress via internal hairpinning is technically an antipattern. It introduces artificial network complexity that does not reflect how actual external users reach our services.

---

### If you want to just explain the `curl` part in a chat:

"To clarify how the test works: We aren't hitting the external Load Balancer. The script grabs the internal ClusterIP of the ingress gateway and runs a curl with `--resolve domain.com:443:internal_ip`.

Essentially, we are forcing the pod to talk directly to the ingress gateway service IP. This works in some environments, but in the app cluster, it seems to confuse the mesh/sidecars regarding TLS termination, causing the `unexpected eof` error."