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
    
    # 0. Depfrom lib.config import (
    CLIENT_APP_NAME,
    RETRY_ATTEMPTS,
    RETRY_SECONDS,
    RETRY_SECONDS_IN_STRING,
    RETRY_TEMPLATE_PATH,
    TARGET_APP_NAME,
    TEST_NAMESPACE,
)
from lib.utils import apply_yaml_template, run_command
import logging
import time

def run_retry_after_header_tests():
    """
    Verifies that Istio respects the Retry-After header during retries.
    
    Architecture:
    - Client Sidecar: Configured with 'rate_limited_retry_back_off'.
    - Target Sidecar: Injects 'Retry-After' header on 503 responses.
    
    Critical Fix:
    We use "-H 'Connection: close'" in the curl command. This forces the 
    Client Envoy to open a brand new TCP connection for the test request, 
    ensuring it is handled by a fresh Worker Thread that has the latest 
    configuration loaded. Without this, Envoy might reuse a "warmed up" 
    connection from an old Worker Thread (Stale Config), causing the 
    header injection to be missed on the first attempt.
    """

    logging.info("--- Starting Retry-After Header Tests ---")

    # Calculate expected duration
    # Logic: 3 retries = 3 waits. (Wait -> Retry1 -> Wait -> Retry2 -> Wait -> Retry3)
    # The first request (failure) happens immediately.
    # The subsequent 3 retries each wait 'RETRY_SECONDS'.
    min_expected_time = RETRY_SECONDS * RETRY_ATTEMPTS
    max_expected_time = min_expected_time + 3  # Allow 3s buffer for network/processing overhead

    try:
        logging.info("Applying VirtualService and EnvoyFilter for the retry-after test")
        apply_yaml_template(
            template_path=RETRY_TEMPLATE_PATH,
            test_namespace=TEST_NAMESPACE,
            target_app_name=TARGET_APP_NAME,
            retry_attempts=RETRY_ATTEMPTS,
            retry_seconds=RETRY_SECONDS,
            client_app_name=CLIENT_APP_NAME,
            retry_seconds_in_string=RETRY_SECONDS_IN_STRING,
        )

        # Wait for RDS/LDS propagation. 
        # Even with this sleep, idle connections might remain on old workers 
        # if we don't force closure later.
        logging.info("Waiting 5 seconds for Envoy configuration propagation")
        time.sleep(5)

        target_url = "http://%s.%s.svc.cluster.local:8080/status/503" % (TARGET_APP_NAME, TEST_NAMESPACE)

        logging.info("TEST 1: Curling endpoint that returns 503")
        logging.info(
            "Expectation: Should take > %ds due to Retry-After: %ds" % 
            (min_expected_time, RETRY_SECONDS)
        )

        # CRITICAL: Added -H 'Connection: close' to prevent connection reuse.
        # Note: We use %% to escape the percentage sign for the python string formatting
        curl_cmd = (
            "kubectl exec -n %s %s -- "
            "curl -s -vv -H 'Connection: close' -o /dev/null -w '%%{http_code},%%{time_total}' "
            "'%s'"
        ) % (TEST_NAMESPACE, CLIENT_APP_NAME, target_url)

        stdout, stderr = run_command(curl_cmd, check=False)

        try:
            http_code, duration_str = stdout.strip().split(",")
            real_time = float(duration_str)
        except ValueError:
            logging.error("Failed to parse curl output: %s. Stderr: %s" % (stdout, stderr))
            raise RuntimeError("Retry-After test FAILED: Could not parse metrics")

        logging.info("Test completed: HTTP code: '%s', Elapsed time: %.2fs" % (http_code, real_time))

        if http_code == "503" and min_expected_time <= real_time < max_expected_time:
            logging.info(
                "SUCCESS: Test took %.2fs (Expected range: %d-%ds) and returned 503" %
                (real_time, min_expected_time, max_expected_time)
            )
            logging.info("Retry-After header was correctly respected")
            
        else:
            logging.error("FAILURE: Retry logic mismatch")
            if http_code != "503":
                logging.error("Expected HTTP 503, got %s" % http_code)
            
            if real_time < min_expected_time:
                logging.error(
                    "Too Fast! %.2fs < %ds (Envoy ignored the header)" % 
                    (real_time, min_expected_time)
                )
            elif real_time >= max_expected_time:
                logging.error(
                    "Too Slow! %.2fs > %ds (Possible timeout)" % 
                    (real_time, max_expected_time)
                )
            
            raise RuntimeError("Retry-After test FAILED")

    except Exception as e:
        logging.error("Retry-After test FAILED with error: %s" % e)
        raiseloy httpbin with Strict mTLS
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