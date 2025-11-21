import logging
import sys
import time
import subprocess
from string import Template

# ==========================================
# LOGGING SETUP
# ==========================================
# Standard library logging
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
    """Cleanup function."""
    logger.info("🧹 Cleaning up resources...")
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
        logger.info("Resources deleted.")
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")

def is_valid_ip(ip):
    return len(ip.split('.')) == 4

# ==========================================
# CORE LOGIC (Pure Python / No Tenacity)
# ==========================================

def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway", timeout=60):
    """
    Loops manually to wait for ClusterIP.
    """
    logger.info(f"Looking up Service {service_name} in {namespace} (Timeout: {timeout}s)")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            cmd = f"kubectl get svc {service_name} -n {namespace} -o jsonpath='{{.spec.clusterIP}}'"
            cluster_ip, _ = run_command(cmd, check=False)
            
            # Clean output
            cluster_ip = cluster_ip.strip().strip("'").strip('"')

            if cluster_ip and is_valid_ip(cluster_ip):
                logger.info(f"Found Internal Gateway IP: {cluster_ip}")
                return cluster_ip
            
        except Exception as e:
            # Ignore transient errors during lookup
            pass

        logger.info("Waiting for ClusterIP allocation...")
        time.sleep(5) # Fixed wait

    raise Exception(f"Timed out waiting for {service_name} ClusterIP")


def verify_connectivity(url, resolve_host, resolve_ip, expect_status="200", extra_headers="", timeout=45):
    """
    Verifies connectivity using manual exponential backoff loop.
    """
    start_time = time.time()
    wait_seconds = 2 # Start waiting 2s, then double it
    
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--connect-timeout 5 --max-time 10 "
        f"{extra_headers} "
        f"--resolve {resolve_host}:443:{resolve_ip} "
        f"{url}"
    )
    
    logger.info(f"Checking: {url} -> Expecting {expect_status}")

    attempt = 1
    while time.time() - start_time < timeout:
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == str(expect_status):
            logger.info(f"✅ SUCCESS: Got status {status_code}")
            return True
        
        logger.warning(f"Attempt {attempt}: Got {status_code}, expected {expect_status}. Retrying in {wait_seconds}s...")
        
        time.sleep(wait_seconds)
        
        # Exponential Backoff Logic:
        # 2 -> 4 -> 8 -> 10 -> 10 ...
        wait_seconds = min(wait_seconds * 2, 10)
        attempt += 1

    logger.error(f"❌ FAILED: Did not receive {expect_status} after {timeout} seconds.")
    return False

# ==========================================
# MAIN EXECUTION
# ==========================================

def run_ingress_tests():
    logger.info("🚀 --- Starting Istio Ingress Verification (Pure Python) ---")
    
    try:
        # Step 1: Get Gateway IP
        ingress_ip = get_ingress_info()

        # Step 2: Apply Config
        apply_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )
        
        # Wait a moment for Envoy to load the new config
        time.sleep(3)

        # Step 3: Positive Connectivity
        logger.info("--- Test A: Positive Connectivity ---")
        target_url = f"https://{INGRESS_HOST}/v1/template/ping"
        
        if not verify_connectivity(target_url, INGRESS_HOST, ingress_ip, expect_status="200"):
             raise Exception("Positive Connectivity Test Failed")

        # Step 4: Negative Isolation Test (Host Header Injection)
        logger.info("--- Test B: Negative Security Isolation ---")
        fake_host = "unauthorized-domain.com"
        
        if not verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="404", 
            extra_headers=f'-H "Host: {fake_host}"' 
        ):
             raise Exception("Security Isolation Test Failed (Traffic was not blocked)")
        
        # Step 5: Access Control (Optional - from previous discussion)
        # If you want to add the RBAC test here, reuse verify_connectivity with expect_status="403"
        
        logger.info("🎉 SUITE PASSED: Application is correctly routed and isolated.")

    except Exception as e:
        logger.error(f"❌ TEST SUITE FAILED: {e}")
        sys.exit(1)

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
    # Configure logging since we are running this file directly
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    run_ingress_tests()import logging
import sys
import time
import subprocess
from string import Template

# ==========================================
# LOGGING SETUP
# ==========================================
# Standard library logging
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
    """Cleanup function."""
    logger.info("🧹 Cleaning up resources...")
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
        logger.info("Resources deleted.")
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")

def is_valid_ip(ip):
    return len(ip.split('.')) == 4

# ==========================================
# CORE LOGIC (Pure Python / No Tenacity)
# ==========================================

def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway", timeout=60):
    """
    Loops manually to wait for ClusterIP.
    """
    logger.info(f"Looking up Service {service_name} in {namespace} (Timeout: {timeout}s)")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            cmd = f"kubectl get svc {service_name} -n {namespace} -o jsonpath='{{.spec.clusterIP}}'"
            cluster_ip, _ = run_command(cmd, check=False)
            
            # Clean output
            cluster_ip = cluster_ip.strip().strip("'").strip('"')

            if cluster_ip and is_valid_ip(cluster_ip):
                logger.info(f"Found Internal Gateway IP: {cluster_ip}")
                return cluster_ip
            
        except Exception as e:
            # Ignore transient errors during lookup
            pass

        logger.info("Waiting for ClusterIP allocation...")
        time.sleep(5) # Fixed wait

    raise Exception(f"Timed out waiting for {service_name} ClusterIP")


def verify_connectivity(url, resolve_host, resolve_ip, expect_status="200", extra_headers="", timeout=45):
    """
    Verifies connectivity using manual exponential backoff loop.
    """
    start_time = time.time()
    wait_seconds = 2 # Start waiting 2s, then double it
    
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--connect-timeout 5 --max-time 10 "
        f"{extra_headers} "
        f"--resolve {resolve_host}:443:{resolve_ip} "
        f"{url}"
    )
    
    logger.info(f"Checking: {url} -> Expecting {expect_status}")

    attempt = 1
    while time.time() - start_time < timeout:
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == str(expect_status):
            logger.info(f"✅ SUCCESS: Got status {status_code}")
            return True
        
        logger.warning(f"Attempt {attempt}: Got {status_code}, expected {expect_status}. Retrying in {wait_seconds}s...")
        
        time.sleep(wait_seconds)
        
        # Exponential Backoff Logic:
        # 2 -> 4 -> 8 -> 10 -> 10 ...
        wait_seconds = min(wait_seconds * 2, 10)
        attempt += 1

    logger.error(f"❌ FAILED: Did not receive {expect_status} after {timeout} seconds.")
    return False

# ==========================================
# MAIN EXECUTION
# ==========================================

def run_ingress_tests():
    logger.info("🚀 --- Starting Istio Ingress Verification (Pure Python) ---")
    
    try:
        # Step 1: Get Gateway IP
        ingress_ip = get_ingress_info()

        # Step 2: Apply Config
        apply_yaml_template(
            template_path=INGRESS_TEMPLATE_PATH,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            INGRESS_HOST=INGRESS_HOST,
            TARGET_APP_NAME=TARGET_APP_NAME
        )
        
        # Wait a moment for Envoy to load the new config
        time.sleep(3)

        # Step 3: Positive Connectivity
        logger.info("--- Test A: Positive Connectivity ---")
        target_url = f"https://{INGRESS_HOST}/v1/template/ping"
        
        if not verify_connectivity(target_url, INGRESS_HOST, ingress_ip, expect_status="200"):
             raise Exception("Positive Connectivity Test Failed")

        # Step 4: Negative Isolation Test (Host Header Injection)
        logger.info("--- Test B: Negative Security Isolation ---")
        fake_host = "unauthorized-domain.com"
        
        if not verify_connectivity(
            url=target_url, 
            resolve_host=INGRESS_HOST, 
            resolve_ip=ingress_ip, 
            expect_status="404", 
            extra_headers=f'-H "Host: {fake_host}"' 
        ):
             raise Exception("Security Isolation Test Failed (Traffic was not blocked)")
        
        # Step 5: Access Control (Optional - from previous discussion)
        # If you want to add the RBAC test here, reuse verify_connectivity with expect_status="403"
        
        logger.info("🎉 SUITE PASSED: Application is correctly routed and isolated.")

    except Exception as e:
        logger.error(f"❌ TEST SUITE FAILED: {e}")
        sys.exit(1)

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
    # Configure logging since we are running this file directly
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    run_ingress_tests()