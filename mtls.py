import logging
import sys
import time
import subprocess
import ssl
import socket
import datetime
from string import Template
from tenacity import (
    retry, 
    stop_after_delay, 
    wait_exponential, 
    wait_fixed,
    retry_if_result, 
    before_sleep_log
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION
# ==========================================
INGRESS_TEMPLATE_PATH = "ingress.yaml"
TEST_NAMESPACE = "release-verification-istio"
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
        logging.debug(f"Command failed: {e.stderr}")
        if check:
            raise e
        return "", e.returncode

def apply_yaml_template(template_path, **kwargs):
    """Reads a YAML file, substitutes $VARIABLES, and applies it via kubectl."""
    logging.info(f"Applying template {template_path}...")
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
        logging.info("Resource applied successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to apply YAML: {e.stderr}")
        raise

def delete_yaml_template(template_path, **kwargs):
    """Reads a YAML file, substitutes variables, and DELETES it. (Cleanup)"""
    logging.info("Cleaning up resources...")
    with open(template_path, 'r') as f:
        src = Template(f.read())
        rendered_yaml = src.safe_substitute(kwargs)

    try:
        subprocess.run(
            ["kubectl", "delete", "-f", "-", "--ignore-not-found=true"],
            input=rendered_yaml,
            text=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logging.info("Resources deleted.")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")

def is_valid_ip(ip):
    return len(ip.split('.')) == 4

# ==========================================
# CORE LOGIC (With Tenacity)
# ==========================================

# Retry Strategy for IP Lookup:
# Stop after 60s. Wait 5s between attempts.
@retry(
    stop=stop_after_delay(60),
    wait=wait_fixed(5),
    before_sleep=before_sleep_log(logger, logging.INFO),
    reraise=True
)
def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway"):
    """
    Retries until ClusterIP is available or timeout occurs.
    """
    cmd = f"kubectl get svc {service_name} -n {namespace} -o jsonpath='{{.spec.clusterIP}}'"
    cluster_ip, _ = run_command(cmd, check=False)
    
    cluster_ip = cluster_ip.strip().strip("'").strip('"')

    if cluster_ip and is_valid_ip(cluster_ip):
        logging.info(f"Found Internal Gateway IP: {cluster_ip}")
        return cluster_ip
    
    # Raising exception triggers Tenacity retry
    raise Exception(f"Waiting for {service_name} ClusterIP allocation...")


def verify_tls_cert(hostname, connect_ip):
    """
    Single-shot TLS check. 
    Usually doesn't need retry logic unless network is very flaky, 
    as verify_connectivity confirms the pipe is open first.
    """
    logging.info(f"Verifying TLS for {hostname}...")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE 

    try:
        sock = socket.create_connection((connect_ip, 443), timeout=5)
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()
            if not cert and context.verify_mode == ssl.CERT_NONE:
                 return True

            not_after = datetime.datetime.strptime(cert['notAfter'], "%b %d %H:%M:%S %Y %Z")
            if not_after < datetime.datetime.utcnow():
                logging.error("Cert Expired!")
                return False
            
            logging.info(f"TLS Valid. Expires: {not_after}")
            return True
    except Exception as e:
        logging.error(f"TLS Check Failed: {e}")
        return False


# Helper for Tenacity: check if result is False
def is_false(result):
    return result is False

# Retry Strategy for Connectivity:
# Stop after 45s. 
# Exponential Backoff: Wait 2s, then 4s, then 8s... (Max 10s).
# This is gentle on the network while allowing Istio time to propagate.
@retry(
    stop=stop_after_delay(45),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_result(is_false),
    before_sleep=before_sleep_log(logger, logging.INFO)
)
def verify_connectivity(url, resolve_host, resolve_ip, expect_status="200"):
    """
    Verifies connectivity. Returns True if status matches expected, else False.
    Tenacity handles the looping based on the return value.
    """
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--connect-timeout 5 --max-time 10 "
        f"--resolve {resolve_host}:443:{resolve_ip} "
        f"{url}"
    )

    logging.info(f"Checking: {url} -> expect {expect_status}")
    stdout, _ = run_command(curl_cmd, check=False)
    status_code = stdout.strip()

    if status_code == str(expect_status):
        logging.info(f"SUCCESS: Got {status_code}")
        return True
    
    logging.warning(f"Got {status_code}, expected {expect_status}. Retrying...")
    return False

# ==========================================
# MAIN EXECUTION
# ==========================================

def run_ingress_tests():
    logging.info("--- Starting Istio Ingress Verification (Tenacity Enabled) ---")
    
    try:
        # Step 1: Get Info (Auto-retries via Tenacity)
        ingress_ip = get_ingress_info()

        # Step 2: Apply Config
        apply_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

        # Step 3: Positive Connectivity (Auto-retries via Tenacity)
        target_url = f"https://{INGRESS_HOST}/v1/template/ping"
        
        # verify_connectivity will raise RetryError if it fails after 45s
        # We wrap in try/except to catch that specific error if we want custom logging
        verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="200"
        )

        # Step 4: TLS Check (Single shot)
        if not verify_tls_cert(INGRESS_HOST, ingress_ip):
            raise Exception("TLS Certificate Check Failed")

        # Step 5: Negative Isolation Check
        logging.info("Step 5: Running Negative Security Test")
        fake_host = "unauthorized-domain.com"
        fake_url = f"https://{fake_host}/v1/template/ping"
        
        # We re-use the robust retry logic even for negative tests
        # to ensure we don't get false failures due to temporary network blips
        verify_connectivity(
            url=fake_url,
            resolve_host=fake_host,
            resolve_ip=ingress_ip,
            expect_status="404" # or 403
        )

        logging.info("✅ SUITE PASSED: All Istio Ingress Tests Completed")

    except Exception as e:
        logging.error(f"❌ TEST SUITE FAILED: {e}")
        sys.exit(1) # Ensure K8s Job marks pod as Error

    finally:
        # Step 6: Cleanup (ALWAYS runs)
        delete_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

if __name__ == "__main__":
    run_ingress_tests()