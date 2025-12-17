from lib.config import (
    CLIENT_APP_NAME,
    RETRY_ATTEMPTS,
    RETRY_SECONDS,
    RETRY_SECONDS_IN_STRING,
    RETRY_TEMPLATE_PATH,
    TARGET_APP_NAME,
    TEST_NAMESPACE,
    RETRY_ROUTE_NAME,
)
from lib.utils import apply_yaml_template, run_command
import logging
import time

def get_pod_name(namespace, app_label, max_retries=5, delay_seconds=2):
    """
    Dynamically fetches the name of a running pod that matches the given app label.
    """
    cmd = (
        f"kubectl get pods -n {namespace} -l app={app_label} "
        "-o jsonpath='{.items[0].metadata.name}'"
    )

    for attempt in range(1, max_retries + 1):
        stdout, stderr = run_command(cmd, check=False)
        pod_name = stdout.strip()
        if pod_name:
            return pod_name
        
        logging.info("Waiting for pod 'app=%s'... (Attempt %d/%d)", app_label, attempt, max_retries)
        time.sleep(delay_seconds)
        
    raise RuntimeError(f"Timeout: No pod found for app '{app_label}' in namespace '{namespace}'")

def wait_for_config_propagation(namespace, app_label, grep_cmd_arg, max_retries=30, delay_seconds=1):
    """
    Polls Envoy Admin API to ensure configuration has arrived.
    """
    pod_name = get_pod_name(namespace, app_label)
    
    logging.info("Checking Envoy config on '%s' for keyword '%s'...", pod_name, grep_cmd_arg)

    # Use f-string for command construction
    cmd = (
        f"kubectl exec -n {namespace} {pod_name} -c istio-proxy -- "
        f"/bin/sh -c \"curl -s http://localhost:15000/config_dump | grep '{grep_cmd_arg}'\""
    )

    for attempt in range(1, max_retries + 1):
        try:
            run_command(cmd, check=True)
            logging.info("Confirmed: Config '%s' found on '%s'!", grep_cmd_arg, pod_name)
            return True
        except Exception:
            if attempt < max_retries:
                time.sleep(delay_seconds)

    raise RuntimeError(f"Timeout: Config '{grep_cmd_arg}' not found on '{pod_name}'")

def wait_for_target_app_health(namespace, client_pod_name, target_url, max_retries=30):
    """
    Ensures the Target App is listening.
    """
    logging.info("Checking Target App Health at %s...", target_url)
    
    # f-string for command. Note the double {{ }} for curl output format is NOT needed 
    # here because we aren't using % variables, but good habit to remember.
    # We use -H 'Connection: close' to keep the pool clean.
    cmd = (
        f"kubectl exec -n {namespace} {client_pod_name} -- "
        f"curl -s -o /dev/null -w '%{{http_code}}' -H 'Connection: close' "
        f"'{target_url}'"
    )

    for _ in range(max_retries):
        stdout, _ = run_command(cmd, check=False)
        if stdout.strip() == "200":
            logging.info("Target App is Healthy (200 OK)")
            return True
        time.sleep(1)
        
    raise RuntimeError("Target App failed to become healthy (did not return 200)")

def run_retry_after_header_tests():
    logging.info("--- Starting Retry-After Header Tests ---")

    min_expected_time = RETRY_SECONDS * RETRY_ATTEMPTS
    max_expected_time = min_expected_time + 3

    try:
        logging.info("Applying VirtualService and EnvoyFilter...")
        apply_yaml_template(
            template_path=RETRY_TEMPLATE_PATH,
            test_namespace=TEST_NAMESPACE,
            target_app_name=TARGET_APP_NAME,
            retry_attempts=RETRY_ATTEMPTS,
            retry_seconds=RETRY_SECONDS,
            client_app_name=CLIENT_APP_NAME,
            retry_seconds_in_string=RETRY_SECONDS_IN_STRING,
            retry_route_name=RETRY_ROUTE_NAME
        )

        # 1. Wait for Envoy Config
        wait_for_config_propagation(TEST_NAMESPACE, CLIENT_APP_NAME, RETRY_ROUTE_NAME)
        wait_for_config_propagation(TEST_NAMESPACE, TARGET_APP_NAME, "retry-after")

        # 2. Wait for App Health
        client_pod_name = get_pod_name(TEST_NAMESPACE, CLIENT_APP_NAME)
        target_vhost = f"{TARGET_APP_NAME}.{TEST_NAMESPACE}.svc.cluster.local:8080"
        
        wait_for_target_app_health(
            TEST_NAMESPACE, 
            client_pod_name, 
            f"http://{target_vhost}/status/200"
        )

        # 3. Run the Test
        target_url = f"http://{target_vhost}/status/503"
        logging.info("TEST: Curling %s (Expect >%ds duration)...", target_url, min_expected_time)

        # CRITICAL: f-string used here.
        # We MUST use double braces {{...}} for curl's formatting variables.
        curl_cmd = (
            f"kubectl exec -n {TEST_NAMESPACE} {client_pod_name} -- "
            f"curl -s -vv -H 'Connection: close' -o /dev/null -w '%{{http_code}},%{{time_total}}' "
            f"'{target_url}'"
        )

        stdout, stderr = run_command(curl_cmd, check=False)

        try:
            http_code, duration_str = stdout.strip().split(",")
            real_time = float(duration_str)
        except ValueError:
            logging.error("Failed to parse curl output: %s. Stderr: %s", stdout, stderr)
            raise RuntimeError("Test FAILED: Could not parse metrics")

        logging.info("Result: HTTP %s, Time %.2fs", http_code, real_time)

        if http_code == "503" and min_expected_time <= real_time < max_expected_time:
            logging.info(
                "SUCCESS: Test passed! Time %.2fs is within valid range.", real_time
            )
        else:
            logging.error("FAILURE: Retry logic mismatch")
            if real_time < min_expected_time:
                logging.error("Too Fast! %.2fs < %ds (Old Connection Reused?)", real_time, min_expected_time)
            elif real_time >= max_expected_time:
                logging.error("Too Slow! %.2fs > %ds", real_time, max_expected_time)
            
            raise RuntimeError("Retry-After test FAILED")

    except Exception as e:
        logging.error("Test FAILED with error: %s", e)
        raise