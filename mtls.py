import logging
import sys
import subprocess
import time
import json
import shlex
from string import Template

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants (Can be moved to config file)
ISTIO_NAMESPACE = "istio-system"
INGRESS_SVC_NAME = "istio-ingressgateway"
TEST_NAMESPACE = "test-automation-ns"
TEST_GATEWAY_NAME = "test-gateway"
TARGET_APP_NAME = "test-app" # Assumes this app is already deployed

# --- Helper Functions ---

def run_command(command, check=True, timeout=30, stdin_data=None):
    """
    Executes a shell command and returns stdout/stderr.
    Handles stdin for piping YAML directly to kubectl.
    """
    try:
        result = subprocess.run(
            shlex.split(command),
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_data
        )
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {command}")
        if e.stderr: logging.error(f"STDERR: {e.stderr}")
        if check: raise
        return e.stdout, e.stderr
    except Exception as e:
        logging.error(f"Execution error: {e}")
        if check: raise
        return "", str(e)

def get_ingress_info_cli(namespace, service_name, timeout=60):
    """
    Fetches External Hostname and Internal ClusterIP using kubectl JSON output.
    Retries until the LoadBalancer hostname is assigned by the Cloud Provider.
    """
    logging.info(f"🔍 Querying {service_name} in {namespace} (CLI JSON mode)...")
    
    cmd = f"kubectl get svc {service_name} -n {namespace} -o json"
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            stdout, _ = run_command(cmd, check=False)
            if not stdout:
                time.sleep(2)
                continue

            # Parse JSON (Safer than text parsing)
            svc_data = json.loads(stdout)
            
            # 1. Get ClusterIP
            cluster_ip = svc_data.get('spec', {}).get('clusterIP')

            # 2. Get Hostname
            status = svc_data.get('status', {}).get('loadBalancer', {}).get('ingress', [])
            
            if status and 'hostname' in status[0]:
                hostname = status[0]['hostname']
                logging.info(f"✅ Found Infrastructure - Host: {hostname}, IP: {cluster_ip}")
                return hostname, cluster_ip
            
            logging.info("Waiting for Cloud LoadBalancer assignment...")
            
        except json.JSONDecodeError:
            logging.warning("Failed to parse kubectl output.")
        except Exception as e:
            logging.warning(f"Retry: {e}")

        time.sleep(5)

    raise Exception(f"Timed out waiting for {service_name} LoadBalancer.")

def apply_yaml_template(template_path, **vars):
    """
    Reads YAML, substitutes $VARs, and applies via kubectl stdin.
    Atomic: No temp files created.
    """
    logging.info(f"📄 Rendering and Applying {template_path}...")
    
    try:
        with open(template_path, "r") as f:
            content = f.read()
        
        # Substitute variables
        rendered_yaml = Template(content).substitute(vars)
        
        # Apply directly via pipe
        run_command("kubectl apply -f -", stdin_data=rendered_yaml)
        logging.info("Gateway resources applied successfully.")
        
    except KeyError as e:
        logging.error(f"Template Error: Missing variable ${e.args[0]}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to apply YAML: {e}")
        sys.exit(1)

def verify_connectivity(ingress_host, cluster_ip):
    """
    Verifies ingress flow using curl --resolve.
    Maps the External Hostname to the Internal ClusterIP to bypass Hairpin NAT.
    """
    target_url = f"https://{ingress_host}/v1/template/ping"
    
    # --resolve forces curl to send the correct SNI/Host header but connect to the internal IP
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--resolve {ingress_host}:443:{cluster_ip} "
        f"{target_url}"
    )

    logging.info(f"🌍 Starting Connectivity Check: {target_url}")
    logging.info(f"Resolution override: {ingress_host} -> {cluster_ip}")

    # Polling Loop (Replaces time.sleep(15))
    for attempt in range(1, 11):
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == "200":
            logging.info(f"✅ SUCCESS: Endpoint returned 200 OK on attempt {attempt}")
            return True
        
        logging.warning(f"Attempt {attempt}: Got status '{status_code}'. Retrying in 3s...")
        time.sleep(3)

    logging.error("❌ Connectivity check failed after all retries.")
    return False

# --- Main Execution ---

def check_ingress_gateway():
    logging.info("--- 5. Checking Ingress Gateway (Best Practice) ---")

    try:
        # STEP 1: Get Infrastructure Info FIRST
        # We do this before applying YAML so we can inject the hostname directly.
        real_ingress_host, internal_ip = get_ingress_info_cli(
            ISTIO_NAMESPACE, INGRESS_SVC_NAME
        )

        # STEP 2: Apply Fully Configured YAML
        # No patching required. The Gateway is created correctly from the start.
        apply_yaml_template(
            "ingress.yaml",
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            TEST_NAMESPACE=TEST_NAMESPACE,
            INGRESS_HOST=real_ingress_host,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

        # STEP 3: Verify Connectivity
        # We poll immediately. Istio is usually fast.
        success = verify_connectivity(real_ingress_host, internal_ip)
        
        if not success:
            logging.error("Ingress Gateway Verification FAILED.")
            sys.exit(1)
            
        logging.info("🎉 Ingress Gateway Verification PASSED.")

    except Exception as e:
        logging.error(f"Fatal Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_ingress_gateway()