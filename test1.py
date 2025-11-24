import subprocess
import time
import logging
import sys
import re

# --- CONFIGURATION ---
# Adjust these variables to match your environment
TEST_NAMESPACE = "payment-service"    # The namespace where apps are deployed
CLIENT_APP_LABEL = "app=retry-after-curl" # Label to find the client pod
TARGET_APP_NAME = "template-service"  # DNS name of the target service
TARGET_APP_LABEL = "app=template-service" # Label to identify target for EnvoyFilter

# Test Parameters
RETRY_DELAY_SECONDS = 2
NUM_RETRIES = 3
# Expected Logic: 
# Initial Request (fail) + Wait(2s) + Retry1(fail) + Wait(2s) + Retry2(fail) + Wait(2s) + Retry3(fail)
# Minimum time = 2s * 3 = 6 seconds. 
EXPECTED_MIN_DURATION = RETRY_DELAY_SECONDS * NUM_RETRIES 
# We add a buffer for network overhead. If it takes > 10s, something might be timing out incorrectly.
EXPECTED_MAX_DURATION = EXPECTED_MIN_DURATION + 5 

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def run_kubectl(cmd, check=True):
    """Executes a kubectl command and returns stdout."""
    full_cmd = f"kubectl {cmd}"
    logger.debug(f"Executing: {full_cmd}")
    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {full_cmd}\nError: {e.stderr}")
        raise

def apply_manifests():
    """Applies the Client VS, Client EF, and Target EF."""
    logger.info("Applying Istio configurations...")

    # 1. Client VirtualService (Routing & Basic Retry Policy)
    client_vs = f"""
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: retry-client-routing
  namespace: {TEST_NAMESPACE}
spec:
  hosts:
  - "{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local"
  http:
  - name: "primary-retry-route"
    route:
    - destination:
        host: "{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local"
        port:
          number: 8080
    retries:
      attempts: {NUM_RETRIES}
      perTryTimeout: 2s
      retryOn: "gateway-error,connect-failure,503"
"""

    # 2. Client EnvoyFilter (The Logic: Wait on Header + Allow Single Replica)
    client_ef = f"""
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: client-retry-logic
  namespace: {TEST_NAMESPACE}
spec:
  workloadSelector:
    labels:
      {CLIENT_APP_LABEL.replace('=', ': ')}
  configPatches:
  - applyTo: HTTP_ROUTE
    match:
      context: SIDECAR_OUTBOUND
      routeConfiguration:
        vhost:
          name: "{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:8080"
          route:
            name: "primary-retry-route"
    patch:
      operation: MERGE
      value:
        route:
          retry_policy:
            retry_host_predicate: [] 
            rate_limited_retry_back_off:
              reset_headers:
              - name: retry-after
              max_interval: "10s"
"""

    # 3. Target EnvoyFilter (The Header Injector)
    target_ef = f"""
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: target-inject-header
  namespace: {TEST_NAMESPACE}
spec:
  workloadSelector:
    labels:
      {TARGET_APP_LABEL.replace('=', ': ')}
  configPatches:
  - applyTo: HTTP_ROUTE
    match:
      context: SIDECAR_INBOUND
      routeConfiguration:
        vhost:
          name: "inbound|http|8080"
          route:
            name: "default"
    patch:
      operation: MERGE
      value:
        route:
          response_headers_to_add:
          - header:
              key: "retry-after"
              value: "{RETRY_DELAY_SECONDS}"
            append_action: OVERWRITE_IF_EXISTS_OR_ADD
"""

    # Apply all manifests via stdin
    manifests = f"{client_vs}\n---\n{client_ef}\n---\n{target_ef}"
    
    # We use subprocess directly here to pipe the string
    process = subprocess.Popen(
        f"kubectl apply -f -", 
        shell=True, 
        stdin=subprocess.PIPE, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = process.communicate(input=manifests)
    
    if process.returncode != 0:
        logger.error(f"Failed to apply manifests: {stderr}")
        sys.exit(1)
    
    logger.info("Manifests applied successfully.")

def cleanup_manifests():
    """Deletes the applied resources."""
    logger.info("Cleaning up resources...")
    resources = [
        f"virtualservice/retry-client-routing -n {TEST_NAMESPACE}",
        f"envoyfilter/client-retry-logic -n {TEST_NAMESPACE}",
        f"envoyfilter/target-inject-header -n {TEST_NAMESPACE}"
    ]
    for res in resources:
        try:
            run_kubectl(f"delete {res} --ignore-not-found")
        except:
            pass # Suppress errors during cleanup

def get_pod_name(label_selector):
    """Gets the first pod name matching the label."""
    cmd = f"get pods -n {TEST_NAMESPACE} -l {label_selector} -o jsonpath='{{.items[0].metadata.name}}'"
    return run_kubectl(cmd)

def run_test():
    try:
        # 1. Prepare Environment
        apply_manifests()
        
        # Give Istio/Envoy a moment to sync config (Propagating to sidecars takes a few seconds)
        logger.info("Waiting 5 seconds for Envoy configuration propagation...")
        time.sleep(5)

        # 2. Identify Client Pod
        client_pod = get_pod_name(CLIENT_APP_LABEL)
        logger.info(f"Running test from pod: {client_pod}")

        # 3. Execute Curl
        # We use curl's write-out (-w) to get precise metrics: HTTP Code and Total Time
        target_url = f"http://{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:8080/fault/abort?statusCode=503"
        
        curl_cmd = (
            f"kubectl exec -n {TEST_NAMESPACE} {client_pod} -- "
            f"curl -s -o /dev/null -w '%{{http_code}},%{{time_total}}' "
            f"'{target_url}'"
        )
        
        logger.info(f"Executing: curl {target_url}")
        start_time_local = time.time()
        output = run_kubectl(curl_cmd)
        end_time_local = time.time()
        
        # 4. Parse Results
        try:
            http_code, duration_str = output.split(',')
            duration = float(duration_str)
        except ValueError:
            logger.error(f"Failed to parse curl output: {output}")
            sys.exit(1)

        logger.info(f"Test Result -> HTTP Code: {http_code}, Duration: {duration:.4f}s")

        # 5. Validation Logic
        failures = []
        
        # Check 1: Did we get the 503?
        if http_code != "503":
            failures.append(f"Expected HTTP 503, got {http_code}")

        # Check 2: Was the duration correct?
        # Logic: If duration is < MIN_EXPECTED, Envoy didn't wait.
        if duration < EXPECTED_MIN_DURATION:
            failures.append(
                f"Duration {duration:.2f}s is too fast! "
                f"Expected at least {EXPECTED_MIN_DURATION}s "
                f"(Retries: {NUM_RETRIES} * Wait: {RETRY_DELAY_SECONDS}s)"
            )
        
        # Check 3: Did it timeout?
        if duration > EXPECTED_MAX_DURATION:
             failures.append(f"Duration {duration:.2f}s is too slow (Possible timeout).")

        # 6. Final Verdict
        if not failures:
            logger.info("✅ TEST PASSED: Envoy respected the Retry-After header.")
        else:
            logger.error("❌ TEST FAILED:")
            for fail in failures:
                logger.error(f" - {fail}")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("Test interrupted by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        cleanup_manifests()

if __name__ == "__main__":
    run_test()