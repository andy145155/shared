import logging
import time
import re
# Assuming these are imported from your shared utils module
# from utils import apply_yaml_template, run_command

def check_retry_after_header():
    """
    Verifies that Istio respects the Retry-After header during retries.
    Uses Client Sidecar for retry logic and Target Sidecar for header injection.
    """
    logging.info("5. Checking Retry-After Header (EnvoyFilter Strategy)")

    # Configuration
    TEST_NAMESPACE = "payment-service" # Replace with your dynamic var if needed
    TARGET_APP_NAME = "template-service"
    CLIENT_APP_NAME = "retry-after-curl"
    RETRY_ATTEMPTS = 3
    RETRY_SECONDS = 2
    
    # Path to the template file provided above
    RETRY_TEMPLATE_PATH = "templates/retry_after_template.yaml.j2"

    # Calculate expected duration
    # Logic: 3 retries = 3 waits. (Wait -> Retry1 -> Wait -> Retry2 -> Wait -> Retry3)
    MIN_EXPECTED_TIME = RETRY_SECONDS * RETRY_ATTEMPTS
    MAX_EXPECTED_TIME = MIN_EXPECTED_TIME + 5  # Allow buffer for network overhead

    try:
        logging.info("STEP 1: Applying VirtualService and EnvoyFilters...")
        apply_yaml_template(
            RETRY_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TARGET_APP_NAME=TARGET_APP_NAME,
            CLIENT_APP_NAME=CLIENT_APP_NAME,
            RETRY_ATTEMPTS=RETRY_ATTEMPTS,
            RETRY_SECONDS=RETRY_SECONDS
        )

        logging.info("Waiting 5s for Envoy configuration propagation...")
        time.sleep(5)

        logging.info(f"STEP 2: Curling endpoint that returns 503...")
        logging.info(f"Expectation: Should take >{MIN_EXPECTED_TIME}s due to Retry-After: {RETRY_SECONDS}s")

        # Best Practice: Use curl -w to get exact timing instead of shell 'time'
        # %{http_code}: Returns the final status code (e.g., 503)
        # %{time_total}: Returns total duration in seconds
        target_url = f"http://{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:8080/fault/abort?statusCode=503"
        
        curl_cmd = (
            f"kubectl exec -n {TEST_NAMESPACE} {CLIENT_APP_NAME} -- "
            f"curl -s -o /dev/null -w '%{{http_code}},%{{time_total}}' "
            f"'{target_url}'"
        )

        # run_command returns (stdout, stderr) based on your screenshot
        output, stderr_output = run_command(curl_cmd, check=False)

        logging.info(f"Raw curl output: {output}")

        # Parse metrics from stdout (format: CODE,TIME)
        try:
            http_code, duration_str = output.strip().split(',')
            real_time = float(duration_str)
        except ValueError:
            logging.error(f"Failed to parse curl output: {output}. Stderr: {stderr_output}")
            raise Exception("Retry-After test FAILED: Could not parse metrics.")

        logging.info(f"Test completed. HTTP code: '{http_code}', Elapsed time: {real_time:.2f}s")

        # Validation
        if http_code == "503" and MIN_EXPECTED_TIME <= real_time < MAX_EXPECTED_TIME:
            logging.info(
                f"SUCCESS: Test took {real_time:.2f}s "
                f"(Expected range: {MIN_EXPECTED_TIME}-{MAX_EXPECTED_TIME}s) and returned 503."
            )
            logging.info("Retry-After header was correctly respected.")
        else:
            logging.error("FAILURE: Retry logic mismatch.")
            if http_code != "503":
                logging.error(f" - Expected HTTP 503, got {http_code}")
            if real_time < MIN_EXPECTED_TIME:
                logging.error(f" - Too Fast! {real_time:.2f}s < {MIN_EXPECTED_TIME}s (Envoy ignored the header)")
            elif real_time >= MAX_EXPECTED_TIME:
                logging.error(f" - Too Slow! {real_time:.2f}s > {MAX_EXPECTED_TIME}s (Possible timeout)")
            
            raise Exception("Retry-After test FAILED.")

    except Exception as e:
        logging.error(f"Test Execution Error: {e}")
        raise
    
    finally:
        logging.info("Cleaning up resources...")
        # Add your cleanup logic here, e.g., deleting the applied YAMLs
        # cleanup_manifests(...)