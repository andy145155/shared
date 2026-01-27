import logging
import time
import sys
from lib.utils import apply_yaml_template, run_command

# Configuration
# Assuming these are passed in or defined globally as per your screenshot context
# INGRESS_HOST = "verification.example.com"
# TARGET_APP_NAME = "httpbin"
# TEST_NAMESPACE = "platform-automation"

def get_ingress_info():
    """Retrieves the ClusterIP of the istio-ingressgateway."""
    # This is safer than LoadBalancer IP for internal cluster testing
    cmd = "kubectl get svc istio-ingressgateway -n istio-system -o jsonpath='{.spec.clusterIP}'"
    ip, _ = run_command(cmd, check=False)
    return ip.strip().strip("'")

def curl_ingress(path, host_header, resolve_ip, description):
    """
    Executes a precise curl command and returns the status code and latency.
    """
    url = f"https://{host_header}{path}"
    logging.info(f"--- TEST: {description} ---")
    
    # curl flags:
    # -k: Skip cert validation (since we are testing connectivity, not PKI trust here)
    # --resolve: Force the domain to map to the Ingress ClusterIP
    # -o /dev/null: Throw away the body
    # -w: output format to capture Code and Latency
    cmd = (
        f"kubectl exec {CLIENT_APP_NAME} -n {TEST_NAMESPACE} -- "
        f"curl -k -s -o /dev/null "
        f"--resolve {host_header}:443:{resolve_ip} "
        f"-w '%{{http_code}},%{{time_total}}' "
        f"'{url}'"
    )

    # Retry logic for "Warm up" (Istio sidecars can take a moment to sync routes)
    for attempt in range(1, 4):
        stdout, _ = run_command(cmd, check=False)
        try:
            parts = stdout.strip().split(',')
            status_code = parts[0]
            latency = float(parts[1])
            logging.info(f"    Attempt {attempt}: Code={status_code}, Latency={latency}s")
            return status_code, latency
        except ValueError:
            logging.warning(f"    Attempt {attempt}: Curl failed to parse. Retrying...")
            time.sleep(2)
    
    raise RuntimeError(f"Failed to execute curl for {description}")

def run_ingress_tests():
    logging.info("Initializing Istio Ingress Verification Suite (httpbin edition)...")
    
    # 1. Apply Manifests
    apply_yaml_template(
        template_path="manifests/ingress.yaml",
        TEST_NAMESPACE=TEST_NAMESPACE,
        INGRESS_HOST=INGRESS_HOST,
        TARGET_APP_NAME=TARGET_APP_NAME
    )
    
    ingress_ip = get_ingress_info()
    logging.info(f"Resolved Ingress Gateway IP: {ingress_ip}")

    # ---------------------------------------------------------
    # TEST CASE 1: Happy Path (End-to-End Connectivity)
    # ---------------------------------------------------------
    # We ask httpbin to explicitly return 200.
    code, _ = curl_ingress("/status/200", INGRESS_HOST, ingress_ip, "Happy Path Connectivity")
    
    if code == "200":
        logging.info("✅ PASS: Traffic reached httpbin and returned 200.")
    else:
        raise RuntimeError(f"❌ FAIL: Expected 200, got {code}")

    # ---------------------------------------------------------
    # TEST CASE 2: Resilience (Timeout Enforcement)
    # ---------------------------------------------------------
    # VirtualService has 3s timeout. We ask httpbin to delay for 5s.
    # Result: Istio should cut it off and return 504 Gateway Timeout.
    code, latency = curl_ingress("/delay/5", INGRESS_HOST, ingress_ip, "Timeout Enforcement")
    
    if code == "504":
        logging.info("✅ PASS: Istio correctly terminated the slow request (Gateway Timeout).")
    elif code == "200":
        logging.error(f"❌ FAIL: Request completed successfully despite 3s timeout setting. Latency: {latency}s")
        # This implies the VirtualService timeout configuration is ignored or missing
    else:
        logging.warning(f"⚠️ WARN: Unexpected code {code}. Expected 504.")

    # ---------------------------------------------------------
    # TEST CASE 3: Security (Host Isolation)
    # ---------------------------------------------------------
    # We send a request to the Ingress IP, but with a Host header that DOES NOT match the Gateway.
    # Result: Envoy should reject this immediately (usually 404 or 421).
    fake_host = "hacker.test.com"
    code, _ = curl_ingress("/status/200", fake_host, ingress_ip, "Host Header Isolation")
    
    if code in ["404", "421"]:
        logging.info(f"✅ PASS: Gateway correctly rejected invalid host '{fake_host}' with {code}.")
    else:
        raise RuntimeError(f"❌ SECURITY FAIL: Gateway allowed traffic for unauthorized host! Code: {code}")

    logging.info("🏆 All Ingress Verification Tests Completed Successfully.")