import logging
import sys
import time
import subprocess
from string import Template

# ==========================================
# LOGGING & CONFIG
# ==========================================
logger = logging.getLogger(__name__)

INGRESS_TEMPLATE_PATH = "ingress.yaml"
TEST_NAMESPACE = "release-verification-istio"
TEST_GATEWAY_NAME = "ingress-test-gateway"
TARGET_APP_NAME = "httpbin"
INGRESS_HOST = "ingress-test.example.com"

# ==========================================
# UTILITIES
# ==========================================

def run_command(command, check=True):
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
        if check: raise e
        return "", e.returncode

def apply_yaml_template(template_path, **kwargs):
    logger.info(f"Applying template {template_path}...")
    with open(template_path, 'r') as f:
        src = Template(f.read())
        rendered_yaml = src.safe_substitute(kwargs)

    try:
        subprocess.run(["kubectl", "apply", "-f", "-"], input=rendered_yaml, text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("✅ Resources applied.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to apply YAML: {e.stderr}")
        raise

def delete_yaml_template(template_path, **kwargs):
    logger.info("🧹 Cleaning up resources...")
    with open(template_path, 'r') as f:
        src = Template(f.read())
        rendered_yaml = src.safe_substitute(kwargs)

    try:
        subprocess.run(["kubectl", "delete", "-f", "-", "--ignore-not-found=true"], input=rendered_yaml, text=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("Resources deleted.")
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")

# ==========================================
# CORE LOGIC (Parametrized Retries)
# ==========================================

def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway", retries=12, delay=5):
    """
    Tries to find the ClusterIP.
    Defaults: 12 retries * 5s delay = 60 seconds total wait.
    """
    logger.info(f"Looking up Service {service_name} (Max wait: {retries * delay}s)...")
    
    for attempt in range(1, retries + 1):
        try:
            cmd = f"kubectl get svc {service_name} -n {namespace} -o jsonpath='{{.spec.clusterIP}}'"
            cluster_ip, _ = run_command(cmd, check=False)
            cluster_ip = cluster_ip.strip().strip("'").strip('"')

            if cluster_ip and len(cluster_ip.split('.')) == 4:
                logger.info(f"Found Internal Gateway IP: {cluster_ip}")
                return cluster_ip
        except:
            pass 

        if attempt < retries:
            logger.info(f"Waiting for IP... (Attempt {attempt}/{retries})")
            time.sleep(delay)

    raise Exception(f"Timed out waiting for {service_name} ClusterIP after {retries} attempts")


def verify_connectivity(url, resolve_host, resolve_ip, expect_status="200", extra_headers="", retries=15, delay=3):
    """
    Verifies connectivity.
    Defaults: 15 retries * 3s delay = 45 seconds total wait.
    """
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--connect-timeout 5 --max-time 10 "
        f"{extra_headers} "
        f"--resolve {resolve_host}:443:{resolve_ip} "
        f"{url}"
    )
    
    logger.info(f"Checking: {url} -> Expecting {expect_status}")

    for attempt in range(1, retries + 1):
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == str(expect_status):
            logger.info(f"✅ SUCCESS: Got status {status_code}")
            return True
        
        if attempt < retries:
            logger.warning(f"Attempt {attempt}/{retries}: Got {status_code}, expected {expect_status}. Retrying in {delay}s...")
            time.sleep(delay)

    logger.error(f"❌ FAILED: Did not receive {expect_status} after {retries} attempts.")
    return False

# ==========================================
# MAIN
# ==========================================

def run_ingress_tests():
    logger.info("🚀 --- Starting Istio Ingress Verification ---")
    
    try:
        # 1. Get IP (Wait up to 60s)
        ingress_ip = get_ingress_info(retries=12, delay=5)

        # 2. Apply Config
        apply_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )
        
        # Quick nap for Envoy sync (param is clearer here too)
        time.sleep(3) 

        # 3. Positive Test (Wait up to 45s)
        logger.info("--- Test A: Positive Connectivity ---")
        target_url = f"https://{INGRESS_HOST}/v1/template/ping"
        
        if not verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="200",
            retries=15, # Explicitly stating how hard to try
            delay=3
        ):
             raise Exception("Positive Connectivity Test Failed")

        # 4. Negative Test (Wait up to 15s - Fail fast!)
        # We don't need to wait 45s for a negative test. If it works, it works instantly.
        logger.info("--- Test B: Negative Security Isolation ---")
        fake_host = "unauthorized-domain.com"
        
        if not verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="404", 
            extra_headers=f'-H "Host: {fake_host}"',
            retries=5,  # Fewer retries for negative tests
            delay=3
        ):
             raise Exception("Security Isolation Test Failed")
        
        logger.info("🎉 SUITE PASSED")

    except Exception as e:
        logger.error(f"❌ TEST SUITE FAILED: {e}")
        sys.exit(1)

    finally:
        # 5. Cleanup
        delete_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    run_ingress_tests()