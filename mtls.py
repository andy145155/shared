import logging
import sys
import time
import subprocess
from string import Template
from tenacity import (
    retry, 
    stop_after_delay, 
    wait_exponential, 
    wait_fixed,
    retry_if_result, 
    before_sleep_log
)

# ==========================================
# LOGGING SETUP
# ==========================================
# We create a specific logger for this module.
# If running standalone, we configure basicConfig in __main__.
logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION
# ==========================================
# Ideally, read these from os.environ for CI/CD flexibility
INGRESS_TEMPLATE_PATH = "ingress.yaml"
TEST_NAMESPACE = "release-verification-istio" # Where the Client Job & Target App live
TEST_GATEWAY_NAME = "ingress-test-gateway"
TARGET_APP_NAME = "httpbin"
INGRESS_HOST = "ingress-test.example.com"

# ==========================================
# UTILITIES
# ==========================================

def run_command(command, check=True):
    """Executes a shell command and returns stdout."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip(), result.returncode
    except subprocess.CalledProcessError as e:
        logger.debug(f"Command failed: {e.stderr}")
        if check:
            raise e
        return "", e.returncode

def apply_yaml_template(template_path, **kwargs):
    """Reads a YAML file, substitutes variables, and applies it via kubectl."""
    logger.info(f"Applying template {template_path}...")
    with open(template_path, 'r') as f:
        src = Template(f.read())
        rendered_yaml = src.safe_substitute(kwargs)

    try:
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=rendered_yaml,
            text=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info("✅ Resources applied successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to apply YAML: {e.stderr}")
        raise

def delete_yaml_template(template_path, **kwargs):
    """Reads a YAML file, substitutes variables, and DELETES it (Cleanup)."""
    logger.info("🧹 Cleaning up resources...")
    with open(template_path, 'r') as f:
        src = Template(f.read())
        rendered_yaml = src.safe_substitute(kwargs)

    try:
        subprocess.run(
            ["kubectl", "delete", "-f", "-", "--ignore-not-found=true"],
            input=rendered_yaml,
            text=True,
            check=False, # Don't crash on cleanup
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info("Resources deleted.")
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")

def is_valid_ip(ip):
    """Simple validation to ensure we got a real IP."""
    return len(ip.split('.')) == 4

# ==========================================
# CORE LOGIC
# ==========================================

# Retry: Stop after 60s, Wait 5s between attempts
@retry(
    stop=stop_after_delay(60),
    wait=wait_fixed(5),
    before_sleep=before_sleep_log(logger, logging.INFO),
    reraise=True
)
def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway"):
    """
    Retries until the Ingress Gateway ClusterIP is available.
    """
    # We look for the ClusterIP because we are running inside the cluster
    cmd = f"kubectl get svc {service_name} -n {namespace} -o jsonpath='{{.spec.clusterIP}}'"
    cluster_ip, _ = run_command(cmd, check=False)
    
    cluster_ip = cluster_ip.strip().strip("'").strip('"')

    if cluster_ip and is_valid_ip(cluster_ip):
        logger.info(f"Found Internal Gateway IP: {cluster_ip}")
        return cluster_ip
    
    # Trigger Tenacity Retry
    raise Exception(f"Waiting for {service_name} ClusterIP allocation...")


# Helper for Tenacity
def is_false(result):
    return result is False

# Retry: Stop after 45s. Exponential Backoff (2s -> 4s -> 8s).
@retry(
    stop=stop_after_delay(45),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_result(is_false),
    before_sleep=before_sleep_log(logger, logging.INFO)
)
def verify_connectivity(url, resolve_host, resolve_ip, expect_status="200", extra_headers=""):
    """
    Verifies connectivity using curl with DNS spoofing (--resolve).
    
    Args:
        extra_headers: string, e.g. '-H "Host: bad.com"' (Used for negative testing)
    """
    # -k: Ignore Cert Validation (Testing Connectivity, not Auth)
    # --resolve: Force SNI 'resolve_host' to map to 'resolve_ip'
    # --connect-timeout 5: Fail fast if Envoy is down
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--connect-timeout 5 --max-time 10 "
        f"{extra_headers} "
        f"--resolve {resolve_host}:443:{resolve_ip} "
        f"{url}"
    )

    logger.info(f"Checking: {url} -> Expecting {expect_status}")
    
    stdout, _ = run_command(curl_cmd, check=False)
    status_code = stdout.strip()

    if status_code == str(expect_status):
        logger.info(f"✅ SUCCESS: Got status {status_code}")
        return True
    
    logger.warning(f"⏳ Got {status_code}, expected {expect_status}. Retrying...")
    return False

# ==========================================
# MAIN EXECUTION
# ==========================================

def run_ingress_tests():
    logger.info("🚀 --- Starting Istio Ingress Verification ---")
    
    try:
        # Step 1: Get Gateway IP (Auto-retries)
        ingress_ip = get_ingress_info()

        # Step 2: Apply Config (Gateway + VirtualService)
        apply_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

        # Step 3: Positive Connectivity Test
        # Tests if the VirtualService is wired correctly
        logger.info("--- Test A: Positive Connectivity ---")
        target_url = f"https://{INGRESS_HOST}/v1/template/ping"
        
        success = verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="200"
        )
        if not success:
             raise Exception("Positive Connectivity Test Failed")

        # Step 4: Negative Isolation Test (Host Header Injection)
        # Tests if we are accidentally routing traffic meant for other hosts
        logger.info("--- Test B: Negative Security Isolation ---")
        fake_host = "unauthorized-domain.com"
        
        # Note: We use the VALID INGRESS_HOST for the URL/resolve (SNI) to pass TLS.
        # We inject the BAD Host Header to fail Routing.
        success_neg = verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="404", # Expecting Not Found
            extra_headers=f'-H "Host: {fake_host}"' 
        )
        if not success_neg:
             # If we got 200 OK here, it means we are allowing unauthorized traffic!
             raise Exception("Security Isolation Test Failed (Traffic was not blocked)")

        logger.info("🎉 SUITE PASSED: Application is correctly routed and isolated.")

    except Exception as e:
        logger.error(f"❌ TEST SUITE FAILED: {e}")
        sys.exit(1) # Ensures K8s Job is marked as Failed

    finally:
        # Step 5: Cleanup (ALWAYS runs)
        delete_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

if __name__ == "__main__":
    # Only configure logging if running standalone
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    run_ingress_tests()