import logging
import json
import time
import subprocess
# Assuming these are imported from your project structure
from lib.utils import run_command, apply_yaml_template 

# Configuration
TEST_NAMESPACE = "test-namespace" # Update as needed
HTTPBIN_TEMPLATE_PATH = "templates/httpbin_mtls.yaml"
TARGET_APP_NAME = "httpbin"
TARGET_PORT = 8000

def check_connection(source_pod: str, expect_success: bool, retries=3, delay=2):
    """
    Verifies connectivity AND mTLS encryption using httpbin.
    """
    # We hit the /headers endpoint to inspect incoming headers
    target_url = f"http://{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:{TARGET_PORT}/headers"
    
    # -s: Silent (no progress bar)
    # --connect-timeout: Fail fast if blocked
    cmd = f"kubectl exec {source_pod} -n {TEST_NAMESPACE} -- curl -s --connect-timeout 5 {target_url}"

    for attempt in range(1, retries + 1):
        try:
            logging.info("Attempt %d/%d: Connection from %s", attempt, retries, source_pod)
            
            # This returns the JSON body (stdout)
            response_body, _ = run_command(cmd) 

            # CASE 1: Expecting Success (Sidecar -> Sidecar)
            if expect_success:
                logging.info("Connection succeeded. Verifying mTLS headers...")
                
                try:
                    data = json.loads(response_body)
                    headers = data.get("headers", {})
                    
                    # THE CRITICAL CHECK:
                    # Envoy injects this header ONLY if mTLS handshake happened.
                    xfcc = headers.get("X-Forwarded-Client-Cert") or headers.get("X-Forwarded-Client-Cert")
                    
                    if xfcc:
                        logging.info("mTLS VERIFIED: Found 'X-Forwarded-Client-Cert' header.")
                        return # Success!
                    else:
                        raise RuntimeError(
                            f"SECURITY FAIL: Connection worked, but mTLS header is MISSING.\n"
                            f"Response: {response_body}"
                        )
                except json.JSONDecodeError:
                    raise RuntimeError(f"Failed to parse httpbin JSON response: {response_body}")

            # CASE 2: Expecting Failure (No-Sidecar -> Sidecar)
            else:
                # If we got here, the connection SUCCEEDED, which is BAD for this test case.
                raise RuntimeError(
                    f"SECURITY FAIL: Traffic from {source_pod} (No-Sidecar) was ALLOWED but should be BLOCKED."
                )

        except subprocess.CalledProcessError as e:
            # CASE 3: Connection Failed (Blocked)
            if not expect_success:
                logging.info(
                    "Connection blocked as expected (Strict mTLS enforcement working).\n"
                    "Pod: %s, Return Code: %s", source_pod, e.returncode
                )
                return # Success (we wanted it to fail)

            # If we expected success but failed, verify retry
            logging.warning("Connection failed (Attempt %d/%d). Retrying...", attempt, retries)
            if attempt < retries:
                time.sleep(delay)

    # Final Failure for Expected Success
    if expect_success:
        raise RuntimeError(f"Connectivity Test FAILED: Could not connect from {source_pod}")

def verify_istio_mtls():
    """
    Orchestrates the mTLS verification tests.
    """
    logging.info("--- Starting Istio mTLS Verification Tests ---")
    
    # 0. Deploy httpbin with Strict mTLS
    logging.info("Deploying httpbin target with Strict mTLS...")
    apply_yaml_template(HTTPBIN_TEMPLATE_PATH, TEST_NAMESPACE)
    
    # (Add logic here to wait for httpbin to be ready, similar to your wait command)
    logging.info("Waiting for httpbin to be ready...")
    run_command(f"kubectl wait --for=condition=Ready pod -l app={TARGET_APP_NAME} -n {TEST_NAMESPACE} --timeout=120s")

    # 1. Test Authorized (Sidecar -> Sidecar)
    # Assumes CLIENT_APP_NAME is already defined/deployed in your setup
    logging.info("Test 1: Sidecar -> Sidecar (Should Pass + Have mTLS Header)")
    check_connection(CLIENT_APP_NAME, expect_success=True)

    # 2. Test Unauthorized (No-Sidecar -> Sidecar)
    logging.info("Test 2: No-Sidecar -> Sidecar (Should be Blocked)")
    
    # Deploy your no-sidecar pod (same as your original logic)
    apply_yaml_template(
        NO_SIDECAR_TEMPLATE_PATH,
        # ... your other args ...
    )
    # Wait for ready...
    
    check_connection(NO_SIDECAR_CLIENT_APP_NAME, expect_success=False)

    logging.info("All Istio mTLS tests PASSED successfully.")