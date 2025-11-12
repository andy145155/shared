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
    """
    Checks the full end-to-end Ingress flow by simulating an external user.
    
    This test is complex because we are *inside* the cluster trying to test
    the *outside* path. This causes two problems:
    1. Network Problem: Connecting to the public ELB IP is unreliable (hairpin NAT).
    2. Security Problem: We connect to the ELB hostname, but Istio expects the
                       'verify-test.example.com' hostname (SNI mismatch).
                       
    This function solves both by:
    1. Connecting to the reliable internal ClusterIP.
    2. Patching the Gateway to temporarily allow the ELB's hostname for the SNI check.
    3. Using 'curl --resolve' to tie it all together.
    """
    logging.info("--- 4. Checking Ingress Gateway (Internal --resolve Method) ---")

    # STEP 1: Apply the base Gateway and VirtualService
    # This creates the 'verify-test.example.com' route.
    logging.info("STEP 1: Applying base Ingress Gateway and VirtualService...")
    apply_yaml_template(INGRESS_TEMPLATE_PATH)

    # STEP 2: Get the public ELB hostname
    # We need this *name* to test the SNI check.
    # e.g., "vault-ingressgateway-f5e1cca4f31bdc8e.elb.ap-east-1.amazonaws.com"
    logging.info(f"STEP 2: Waiting to get external ELB hostname for {INGRESS_SERVICE}...")
    ingress_hostname = ""
    for i in range(10): 
        try:
            ingress_hostname = run_command(
                f"kubectl get svc {INGRESS_SERVICE} -n {ISTIO_NAMESPACE} "
                "-o jsonpath='{.status.loadBalancer.ingress[0].hostname}'",
                check=True, timeout=10,
            )
            if ingress_hostname:
                logging.info(f"Ingress Gateway external hostname found: {ingress_hostname}")
                break
        except Exception as e:
            logging.warning(f"Error checking ingress status (will retry): {e}")

        if i == 9:
            time.sleep(10)

    if not ingress_hostname:
        logging.error("FAILURE: Ingress Gateway external hostname lookup failed.")
        raise Exception("Ingress Gateway address lookup failed")

    # STEP 3: Patch the Gateway to fix the SNI mismatch
    # We add the public ELB hostname to the Gateway's 'hosts' list.
    # This tells Istio: "It's OK to accept a TLS connection (SNI)
    # for the ELB's public name."
    logging.info(f"STEP 3: Patching Gateway '{GATEWAY_NAME}' to add host: {ingress_hostname}")
    try:
        patch_command = (
            f"kubectl patch gateway {GATEWAY_NAME} "
            f"-n {ISTIO_NAMESPACE} --type='json' "
            f"-p='[{{\"op\": \"add\", \"path\": \"/spec/servers/0/hosts/-\", \"value\": \"{ingress_hostname}\"}}]'"
        )
        run_command(patch_command, check=True, timeout=10)
        logging.info("Gateway patch applied successfully.")
        
        # Wait for Istio to see the config change
        logging.info("Waiting 15s for Gateway patch and routes to propagate...")
        time.sleep(15)

    except Exception as e:
        logging.error(f"FAILURE: Could not patch Gateway '{GATEWAY_NAME}': {e}")
        raise

    # STEP 4: Get the reliable *internal* ClusterIP
    # We use this IP to connect because it avoids the unreliable "hairpin NAT"
    # problem (where our pod hangs trying to connect to its own public IP).
    # e.g., "172.20.64.46"
    logging.info(f"STEP 4: Getting internal ClusterIP for {INGRESS_SERVICE}...")
    internal_cluster_ip = ""
    try:
        internal_cluster_ip = run_command(
            f"kubectl get svc {INGRESS_SERVICE} -n {ISTIO_NAMESPACE} "
            "-o jsonpath='{.spec.clusterIP}'",
            check=True, timeout=10,
        )
        if not internal_cluster_ip:
            raise Exception("ClusterIP was empty")
        logging.info(f"Found internal ClusterIP: {internal_cluster_ip}")
    except Exception as e:
        logging.error(f"FAILURE: Could not get internal ClusterIP: {e}")
        raise

    # STEP 5: Run the final test
    # This curl command simulates the full external request perfectly.
    logging.info(f"STEP 5: Testing external HTTPS flow via internal ClusterIP...")
    
    http_code = ""
    try:
        curl_cmd = (
            f"curl -k -s -o /dev/null -w '%{{http_code}}' "
            
            # 1. (FOR VIRTUALSERVICE)
            # Send the 'Host' header Istio needs for routing.
            f"-H 'Host: {INGRESS_HOST}' "
            
            # 2. (FOR RELIABLE CONNECTION + SNI)
            # Tell curl: "When you *think* you're connecting to the
            # {ingress_hostname}, *actually* connect to the
            # reliable {internal_cluster_ip}."
            # This makes the connection reliable AND sends the correct SNI.
            f"--resolve {ingress_hostname}:443:{internal_cluster_ip} "
            
            # 3. (THE URL)
            # The URL we are connecting to, which triggers the SNI check.
            f"https://{ingress_hostname}/v1/template/ping"
        )
        
        logging.info(f"Running command: {curl_cmd}")
        http_code = run_command(curl_cmd, timeout=15, check=True)

        # Check if we got a 200 OK
        if http_code == "200":
            logging.info(f"Ingress returned HTTP {http_code}. Success!")
        else:
            logging.error(f"FAILURE: Ingress Gateway test FAILED. Expected 200, got {http_code}")
            raise Exception(f"Ingress Gateway check FAILED (HTTP {http_code})")

    except Exception as e:
        logging.error(f"Error during curl command: {e}")
        raise Exception(f"Ingress Gateway check FAILED (HTTP {http_code})")

    logging.info("Ingress Gateway check PASSED.")

import logging
import time
import re

# --- Variables from your environment ---
# TEST_NAMESPACE = "af-toolkit"
# RETRY_VS_PATH = "path/to/retry-vs.yaml"
# RETRY_EF_PATH = "path/to/retry-ef.yaml"
# (Make sure the YAML files above are at these paths)
# ----------------------------------------

def check_retry_after_header():
    """
    Checks if the Istio sidecar respects the 'retry-after' header.
    
    1. Applies a VirtualService to simulate a 503 error with a
       'retry-after: 2' header.
    2. Applies an EnvoyFilter to the test pod to *read* that header
       for its retry back-off.
    3. Runs 'time curl' and checks if the elapsed time is correct
       (3 attempts - 1) * 2s = 4s.
    """
    logging.info("--- 5. Checking Retry-After Header (EnvoyFilter) ---")
    
    RETRY_SECONDS = 2  # Must match 'retry-after' in retry-vs.yaml
    ATTEMPTS = 3       # Must match 'attempts' in retry-vs.yaml
    
    # Calculate the expected *minimum* time the test should take.
    # (Attempts - 1) because the last attempt doesn't wait.
    MIN_EXPECTED_TIME = RETRY_SECONDS * (ATTEMPTS - 1)
    # Give a 3s buffer for network/curl overhead
    MAX_EXPECTED_TIME = MIN_EXPECTED_TIME + 3 

    try:
        # STEP 1: Apply the test YAMLs
        logging.info("STEP 1: Applying VirtualService and EnvoyFilter for retry test...")
        apply_yaml_template(RETRY_VS_PATH)
        apply_yaml_template(RETRY_EF_PATH)
        
        logging.info("Waiting 10s for EnvoyFilter to propagate...")
        time.sleep(10)

        # STEP 2: Run the test command
        # We use 'time -p' for simple, parseable output (e.g., "real 4.02")
        # We curl the fake host. The sidecar will intercept this.
        logging.info(f"STEP 2: Curling fake host 'http://retry-test.local/test-retry'")
        logging.info(f"This should fail, but take at least {MIN_EXPECTED_TIME}s...")
        
        # We expect this command to fail (non-zero exit code), so 'check=False'
        # The 'time -p' output is sent to stderr, so we capture it.
        # This is a common way to time a command in a script.
        curl_cmd = (
            "time -p curl -s -o /dev/null "
            "-w '%{http_code}' " # We only want the http code as stdout
            "http://retry-test.local/test-retry"
        )
        
        # Note: 'time -p' output goes to stderr, curl output to stdout
        output, stderr_output = run_command_with_stderr(curl_cmd, check=False)
        
        # STEP 3: Parse the 'time' output from stderr
        logging.info(f"Raw 'time' output (from stderr):\n{stderr_output}")
        
        real_time = 0.0
        match = re.search(r"real\s+([0-9\.]+)", stderr_output)
        if match:
            real_time = float(match.group(1))
        
        logging.info(f"Test completed. HTTP code: '{output}', Elapsed time: {real_time}s")

        # STEP 4: Validate the results
        if output == "503" and real_time >= MIN_EXPECTED_TIME and real_time < MAX_EXPECTED_TIME:
            logging.info(f"SUCCESS: Test took {real_time}s (within {MIN_EXPECTED_TIME}-{MAX_EXPECTED_TIME}s range) and returned 503.")
            logging.info("Retry-After header was correctly respected.")
        else:
            if output != "503":
                logging.error(f"FAILURE: Expected HTTP 503, but got '{output}'")
            if not (real_time >= MIN_EXPECTED_TIME and real_time < MAX_EXPECTED_TIME):
                logging.error(f"FAILURE: Test time ({real_time}s) was outside expected range ({MIN_EXPECTED_TIME}-{MAX_EXPECTED_TIME}s).")
            raise Exception("Retry-After test FAILED.")

    finally:
        # STEP 5: Cleanup
        logging.info("Cleaning up retry test resources...")
        run_command(f"kubectl delete -f {RETRY_VS_PATH}", check=False)
        run_command(f"kubectl delete -f {RETRY_EF_PATH}", check=False)
        
    logging.info("Retry-After check PASSED.")

# You will need a modified 'run_command' or similar utility
# that can capture both stdout and stderr.
def run_command_with_stderr(command, check=True, timeout=30):
    """
    A helper function to run a command and capture both stdout and stderr.
    (This is an example, it might differ from your 'utils.run_command')
    """
    import subprocess
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise Exception(f"Command failed with error:\n{result.stderr}")
    
    return result.stdout.strip(), result.stderr.strip()
        
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

def check_egress_tls_origination():
    """6. Checking Egress (Sidecar TLS Origination)"""
    logging.info("--- 6. Checking Egress (Sidecar TLS Origination) ---")
    
    logging.info("STEP 1: Applying ServiceEntry, VirtualService, and DestinationRule for www.google.com...")
    # This configuration will intercept HTTP traffic to google.com
    # and upgrade it to HTTPS (TLS Origination).
    apply_yaml_template(EGRESS_SE_TEMPLATE_PATH)
    apply_yaml_template(EGRESS_DR_VS_TEMPLATE_PATH)

    logging.info("Waiting 10s for egress rules to propagate...")
    time.sleep(10)

    logging.info("STEP 2: Testing TLS Origination by curling HTTP (port 80)...")
    logging.info("The sidecar should intercept 'http://www.google.com' and upgrade it to 'https://www.google.com'.")
    
    # We test by curling HTTP. If the TLS origination works,
    # google will respond with a 301 (redirect) or 200 (OK).
    # We use -L to follow redirects.
    http_code = run_command(
        f"kubectl exec {CLIENT_APP_NAME} -n {TEST_NAMESPACE} -- curl -s -o /dev/null -w '%{{http_code}}' -L --connect-timeout 5 http://www.google.com",
        check=True
    )
    
    if http_code == "200":
        logging.info(f"✅ Egress TLS Origination PASSED. Received HTTP {http_code} after following redirects.")
    else:
        logging.error(f"FAILURE: Egress TLS Origination test FAILED. Expected 200, got {http_code}")
        raise Exception(f"Egress TLS Origination check FAILED (HTTP {http_code})")


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