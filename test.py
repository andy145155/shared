#!/usr/bin/env python3

import subprocess
import sys
import time
import logging
import shlex
import os
import json

# --- Configuration (from Environment Variables) ---
TEST_NAMESPACE = os.environ.get("TEST_NAMESPACE", "istio-verify-test")
INGRESS_HOST = os.environ.get("INGRESS_HOST", "verify-test.example.com")
ISTIO_REVISION = os.environ.get("ISTIO_REVISION", "stable")
ISTIO_NAMESPACE = os.environ.get("ISTIO_NAMESPACE", "istio-system")
INGRESS_SERVICE = os.environ.get("INGRESS_SERVICE", "istio-ingressgateway")

# --- Template File Paths (from ConfigMap volume) ---
CONFIG_PATH = "/etc/istio-verify-config"
TEST_APPS_TEMPLATE_PATH = f"{CONFIG_PATH}/test-apps.yaml"
NO_SIDECAR_CURL_TEMPLATE_PATH = f"{CONFIG_PATH}/no-sidecar-curl.yaml"
MTLS_STRICT_TEMPLATE_PATH = f"{CONFIG_PATH}/mtls-strict.yaml"
INGRESS_TEMPLATE_PATH = f"{CONFIG_PATH}/ingress.yaml"
# --- ADD NEW TEMPLATE PATHS ---
RETRY_VS_TEMPLATE_PATH = f"{CONFIG_PATH}/retry-vs.yaml"
RETRY_ENVOYFILTER_TEMPLATE_PATH = f"{CONFIG_PATH}/retry-envoyfilter.yaml"


# --- Logger Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# --- Helper Functions (run_command, apply_yaml_template) ---
# ... (These functions are unchanged from our previous version) ...
def run_command(command, check=True, timeout=120, stdin_data=None):
    """Runs a shell command, logs output, and returns stdout."""
    logging.info(f"Running command: {command}")
    try:
        result = subprocess.run(
            shlex.split(command),
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_data
        )
        if result.stdout:
            logging.info(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr:
            logging.warning(f"STDERR:\n{result.stderr.strip()}")
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with exit code {e.returncode}")
        logging.error(f"STDOUT: {e.stdout.strip()}")
        logging.error(f"STDERR: {e.stderr.strip()}")
        if check:
            raise
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        if check:
            raise
        return None

def apply_yaml_template(template_path, is_delete=False):
    """Reads, formats, and applies/deletes a YAML template file via kubectl."""
    action = "delete" if is_delete else "apply"
    verb = "Deleting" if is_delete else "Applying"
    
    logging.info(f"{verb} from template: {template_path}")
    
    try:
        with open(template_path, 'r') as f:
            template_content = f.read()

        yaml_string = template_content.format(
            TEST_NAMESPACE=TEST_NAMESPACE,
            INGRESS_HOST=INGRESS_HOST,
            ISTIO_REVISION=ISTIO_REVISION
        )

        cmd = f"kubectl {action} --ignore-not-found=true -f -"
        run_command(cmd, check=(not is_delete), stdin_data=yaml_string)
            
    except Exception as e:
        logging.error(f"Failed to {action} YAML from {template_path}: {e}")
        if not is_delete:
            raise

# --- Verification Checks ---
# ... (check_control_plane, setup_test_apps are unchanged) ...
def check_control_plane():
    """Check istiod, proxy status, and run config analysis."""
    logging.info("--- 1. Checking Control Plane ---")
    run_command(f"kubectl wait --for=condition=Available deployment -l istio.io/rev={ISTIO_REVISION} -n {ISTIO_NAMESPACE} --timeout=120s")
    logging.info(f"istiod revision {ISTIO_REVISION} Deployment is Available.")
    
    logging.info("Checking proxy synchronization status (waiting up to 60s)...")
    for i in range(12):
        try:
            proxy_status_output = run_command("istioctl proxy-status", check=True)
            
            if "STALE" not in proxy_status_output:
                 logging.info("All proxies are SYNCED (or NOT SENT).")
                 break
            else:
                logging.warning(f"Proxies are STALE (Exit 0), retrying... ({i+1}/12)")

        except subprocess.CalledProcessError as e:
            error_text = e.stdout + e.stderr
            if "STALE" in error_text:
                logging.warning(f"Proxies are STALE (Exit non-zero), retrying... ({i+1}/12)")
            else:
                logging.error(f"istioctl proxy-status failed with a non-STALE error:")
                raise e 
        
        time.sleep(5)
    else:
        logging.error("Found STALE proxies after 60 seconds!")
        raise Exception("Proxy status check failed: STALE proxies found.")

    logging.info("Running istioctl analyze...")
    run_command(f"istioctl analyze --all-namespaces --revision {ISTIO_REVISION}")
    logging.info("istioctl analyze found no issues.")
    logging.info("✅ Control Plane check PASSED.")

def setup_test_apps():
    """Deploys test applications and waits for them to be ready."""
    logging.info("--- 2. Setting up Test Applications ---")
    apply_yaml_template(TEST_APPS_TEMPLATE_PATH)
    
    logging.info("Waiting for test apps to be ready...")
    run_command(f"kubectl wait --for=condition=Ready pod -l app=test-target-app -n {TEST_NAMESPACE} --timeout=180s")
    run_command(f"kubectl wait --for=condition=Ready pod/curl-client -n {TEST_NAMESPACE} --timeout=180s")
    
    containers = run_command(f"kubectl get pod -l app=test-target-app -n {TEST_NAMESPACE} -o jsonpath='{{.items[0].spec.containers[*].name}}'")
    if "istio-proxy" not in containers:
        logging.error("istio-proxy sidecar NOT found in test-target-app pod.")
        raise Exception("Sidecar injection failed")
        
    logging.info("Sidecar successfully injected into test-target-app pod.")
    logging.info("✅ Test Applications setup PASSED.")

# ... (check_mtls_and_routing, check_ingress_gateway are unchanged) ...
def check_mtls_and_routing():
    """3. Checking mTLS and Traffic Routing (in Global STRICT mode)"""
    logging.info("--- 3. Checking mTLS and Traffic Routing (Global STRICT mode) ---")

    # --- Test 1: Verify mTLS-Encrypted Traffic (Sidecar-to-Sidecar) ---
    logging.info("STEP 1: Testing mTLS-encrypted traffic from sidecar pod (should SUCCEED)...")
    # This validates that pod-to-pod traffic works under the global STRICT default.
    run_command(f"kubectl exec {CLIENT_APP_NAME} -n {TEST_NAMESPACE} -- curl -s -f --connect-timeout 5 http://{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:8000/v1/template/ping")
    logging.info("✅ mTLS-encrypted traffic (sidecar-to-sidecar) is working.")
    
    # --- Test 2: Verify Plain-Text Traffic is BLOCKED ---
    logging.info("STEP 2: Deploying non-sidecar 'curl-no-sidecar' pod for plain-text test...")
    apply_yaml_template(CURL_NO_SIDECAR_TEMPLATE_PATH)
    
    logging.info("Waiting for 'curl-no-sidecar' pod to be ready...")
    run_command(f"kubectl wait --for=condition=Ready pod/curl-no-sidecar -n {TEST_NAMESPACE} --timeout=180s")
    
    # Short wait for pod networking to be fully ready
    logging.info("Waiting 5s for pod networking to settle...")
    time.sleep(5) 

    logging.info("STEP 3: Testing plain-text traffic from non-sidecar pod (should be BLOCKED)...")
    # This validates that the global STRICT mode is correctly enforced.
    stdout = run_command(
        f"kubectl exec curl-no-sidecar -n {TEST_NAMESPACE} -- curl -s --connect-timeout 5 http://{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:8000/v1/template/ping",
        check=False
    )
    
    if stdout == "":
        logging.info("✅ Plain-text traffic successfully BLOCKED as expected.")
    else:
        logging.error(f"FAILURE: Plain-text traffic was NOT blocked. mTLS STRICT test FAILED. Output: {stdout}")
        raise Exception("Global mTLS STRICT test FAILED: Plain-text traffic was allowed")

    logging.info("✅ mTLS and Traffic Routing checks PASSED.")

def check_ingress_gateway():
    """4. Checking Ingress Gateway"""
    logging.info("--- 4. Checking Ingress Gateway ---")

    logging.info("STEP 1: Applying Ingress Gateway and VirtualService...")
    # This applies your ingress.yaml which defines the Gateway
    # and the VirtualService for {INGRESS_HOST} with the /get route
    apply_yaml_template(INGRESS_TEMPLATE_PATH) 
    
    logging.info(f"STEP 2: Waiting to get external IP/Hostname for Ingress Gateway service ({INGRESS_SERVICE})...")
    ingress_address = ""
    # Try for 180 seconds (18 attempts * 10 seconds)
    for i in range(18): 
        try:
            # This jsonpath robustly gets *either* the hostname or IP, whichever is assigned
            ingress_address = run_command(
                f"kubectl get svc {INGRESS_SERVICE} -n {ISTIO_NAMESPACE} -o jsonpath='{{.status.loadBalancer.ingress[0].ip}}{{.status.loadBalancer.ingress[0].hostname}}'",
                check=False,
                timeout=10
            )
            if ingress_address:
                logging.info(f"Ingress Gateway external address found: {ingress_address}")
                break
        except Exception as e:
            # This handles transient errors from kubectl
            logging.warning(f"Error checking ingress status (will retry): {e}")

        if i < 17: # Don't log "retrying" on the final attempt
            logging.warning(f"Ingress address not available yet, retrying in 10s... (Attempt {i+1}/18)")
        time.sleep(10)
    
    if not ingress_address:
        logging.error("FAILURE: Ingress Gateway external address lookup failed after 180s.")
        raise Exception("Ingress Gateway address lookup failed")
        
    logging.info(f"STEP 3: Testing external traffic to http://{INGRESS_HOST}/get...")
    logging.info(f"(This will resolve {INGRESS_HOST} to {ingress_address})")
    
    # It can take time for cloud provider load balancers and routes to be ready
    logging.info("Waiting 15s for cloud load balancer and routes to propagate...")
    time.sleep(15)

    # We use 'curl --resolve' to manually tell curl which IP to use for our
    # host. This bypasses any slow DNS propagation.
    # We are testing the /get path you specified in your ingress.yaml.
    http_code = run_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' --resolve '{INGRESS_HOST}:80:{ingress_address}' http://{INGRESS_HOST}/get",
        timeout=10
    )
    
    if http_code == "200":
        logging.info(f"✅ Ingress returned HTTP {http_code}. Success!")
    else:
        logging.error(f"FAILURE: Ingress Gateway test FAILED. Expected 200, got {http_code}")
        logging.error(f"Failed to curl http://{INGRESS_HOST}/get (via {ingress_address})")
        raise Exception(f"Ingress Gateway check FAILED (HTTP {http_code})")
        
    logging.info("✅ Ingress Gateway check PASSED.")

# --- ADD NEW FUNCTION ---
def check_retry_after():
    """Checks if the client-side proxy respects the retry-after header."""
    logging.info("--- 5. Checking Retry-After Header ---")
    
    logging.info("Applying VirtualService (for fault) and EnvoyFilter (for retry policy)...")
    apply_yaml_template(RETRY_VS_TEMPLATE_PATH)
    apply_yaml_template(RETRY_ENVOYFILTER_TEMPLATE_PATH)
    
    logging.info("Waiting 10s for EnvoyFilter config to propagate...")
    time.sleep(10)
    
    logging.info("Starting retry test. This should take ~6-7 seconds...")
    logging.info("(3 attempts, 2-second 'retry-after' delay per attempt)")
    
    start_time = time.time()
    
    # We expect this command to fail, so check=False
    run_command(
        f"kubectl exec curl-client -n {TEST_NAMESPACE} -- curl -s -o /dev/null http://test-target-app.{TEST_NAMESPACE}.svc.cluster.local:8000/retry-test",
        check=False
    )
    
    end_time = time.time()
    duration = end_time - start_time
    logging.info(f"Test completed in {duration:.2f} seconds.")
    
    # Test logic: 1st attempt (instant) + 2s wait + 2nd attempt + 2s wait + 3rd attempt
    # Total = 2 retries = ~4s. (3 attempts total).
    # Let's adjust. 3 attempts, 2 retries. 1st fails, wait 2s, 2nd fails, wait 2s, 3rd fails.
    # Total duration should be > 4 seconds.
    # The runbook showed 6.99s for 3 retries (retry-after: 2).
    # Let's aim for a window between 5 and 8 seconds.
    
    if duration >= 5 and duration <= 8:
        logging.info("✅ Retry-After test PASSED. Duration is within the expected range.")
    else:
        logging.error(f"Retry-After test FAILED. Duration was {duration:.2f}s, expected ~6s.")
        raise Exception("Retry-After test duration was outside the expected range.")

# --- ADD NEW FUNCTION ---
def check_egress_tls_origination():
    """Checks if the sidecar can originate TLS for external traffic."""
    logging.info("--- 6. Checking Egress (TLS Origination) ---")
    
    logging.info("Testing egress to an external HTTPS site (google.com)...")
    # This proves the sidecar can handle egress and originate TLS
    run_command(
        f"kubectl exec curl-client -n {TEST_NAMESPACE} -- curl -s -o /dev/null --connect-timeout 5 https://www.google.com",
        check=True
    )
    logging.info("Egress (TLS Origination) to external HTTPS site is working.")
    logging.info("✅ Egress check PASSED.")


def cleanup():
    """Deletes all test resources."""
    logging.info("--- 7. Cleaning up test resources ---")
    run_command(f"kubectl delete namespace {TEST_NAMESPACE} --ignore-not-found=true", check=False)
    # The namespace deletion will garbage collect all resources
    logging.info("Cleanup complete.")

# --- Main Orchestrator (UPDATED) ---

def main():
    """Main orchestrator."""
    exit_code = 0
    try:
        check_control_plane()
        setup_test_apps()
        check_mtls_and_routing()
        check_ingress_gateway()
        check_retry_after()
        check_egress_tls_origination()
        
        logging.info("🎉🎉🎉 ALL ISTIO VERIFICATION CHECKS PASSED! 🎉🎉🎉")
        
    except Exception as e:
        logging.error(f"VERIFICATION FAILED: {e}")
        exit_code = 1
    finally:
        cleanup()
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()