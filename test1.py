import json

def verify_sidecar_mtls_config(client_pod, target_svc, namespace):
    """
    Verifies that the Client Sidecar is explicitly configured to use mTLS 
    when talking to the Target Service.
    """
    logging.info(f"Verifying Envoy Cluster config for {client_pod} -> {target_svc}...")
    
    # We filter by the FQDN of the target service to find the specific Envoy Cluster config
    target_fqdn = f"{target_svc}.{namespace}.svc.cluster.local"
    
    # Command: istioctl proxy-config clusters <pod> -n <ns> --fqdn <url> -o json
    cmd = (
        f"istioctl proxy-config cluster {client_pod} -n {namespace} "
        f"--fqdn {target_fqdn} -o json"
    )
    
    try:
        result = run_command(cmd, check=True)
        clusters_config = json.loads(result.stdout)
        
        if not clusters_config:
            raise Exception(f"No Envoy cluster configuration found for {target_fqdn}")

        # Logic: Parse the JSON to find TLS settings
        # Usually located in transportSocket -> typedConfig -> ...
        # We look for keywords indicating Istio mTLS like "istio.alts" or "CommonTlsContext"
        
        cluster_dump = json.dumps(clusters_config)
        
        # Check for standard Istio mTLS transport socket definition
        is_mtls_configured = "transportSocket" in cluster_dump and \
                             ("tlsCertificateSdsSecretConfigs" in cluster_dump or \
                              "istio.alts" in cluster_dump)

        if is_mtls_configured:
            logging.info(f"✅ verified: Client sidecar is configured to use mTLS for {target_svc}.")
        else:
            logging.error(f"❌ configuration FAIL: Client sidecar is NOT using mTLS for {target_svc}!")
            logging.error(f"Dump: {cluster_dump}")
            raise Exception("mTLS Configuration Check Failed")

    except Exception as e:
        logging.error(f"Failed to verify sidecar config: {e}")
        raise

# --- Update your main test function ---

def check_mtls_and_routing():
    # ... (Your existing Step 1 code) ...
    
    # AFTER Step 1 (Successful connection), verify WHY it succeeded:
    verify_sidecar_mtls_config(SOURCE_SIDECAR, TARGET_SVC, NS)
    
    # ... (Proceed to Step 2 & 3) ...


import logging
from string import Template
import subprocess

def apply_yaml_template(template_path, is_delete=False, **template_vars):
    """
    Applies or Deletes a YAML file using string.Template ($VAR syntax).
    
    :param template_path: Path to the YAML file
    :param is_delete: If True, runs 'kubectl delete', else 'kubectl apply'
    :param **template_vars: Key=Value pairs to inject into the template ($VAR)
    """
    action = "delete" if is_delete else "apply"
    verb = "Deleting" if is_delete else "Applying"

    logging.info(f"{verb} from template: {template_path}")

    try:
        # Read the file
        with open(template_path, "r") as f:
            template_content = f.read()

        # Perform Substitution using string.Template
        # safe_substitute allows unused variables to remain $VAR without crashing, 
        # but 'substitute' (default) is better for catching missing vars early.
        src = Template(template_content)
        yaml_string = src.substitute(template_vars) 

        # Run Kubectl
        # We pass the rendered string via stdin ('-f -')
        cmd = f"kubectl {action} -f -"
        run_command(cmd, stdin_data=yaml_string)

    except KeyError as e:
        # This catches missing variables specifically for string.Template
        logging.error(f"TEMPLATE ERROR: {template_path} expects variable ${e.args[0]}, but it was not passed.")
        if not is_delete:
            raise
    except Exception as e:
        logging.error(f"Failed to {action} YAML from {template_path}: {e}")
        if not is_delete:
            raise


########################################################
# Kubernetes Ingress Gateway
########################################################
from kubernetes import client, config

# automatically picks up ~/.kube/config OR in-cluster config
try:
    config.load_kube_config()
except config.ConfigException:
    config.load_incluster_config()

v1 = client.CoreV1Api()



def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway"):
    """
    Robustly fetches the External Hostname and Internal ClusterIP 
    using the official K8s client. No text parsing required.
    """
    logging.info(f"Querying Service {service_name} in {namespace} via K8s API...")
    
    try:
        # Get the Service object
        svc = v1.read_namespaced_service(service_name, namespace)
        
        # 1. Get ClusterIP (Safe and easy)
        cluster_ip = svc.spec.cluster_ip
        
        # 2. Get External Hostname (Safe handling of empty lists)
        ingress_status = svc.status.load_balancer.ingress
        if not ingress_status:
             # It takes time for AWS/Cloud to assign the LB. 
             # You might want to add a retry loop here if it's fresh.
             raise Exception("LoadBalancer has no Ingress status yet. Is the ELB ready?")
             
        hostname = ingress_status[0].hostname
        
        return hostname, cluster_ip

    except Exception as e:
        logging.error(f"K8s API Error: {e}")
        raise


def check_ingress_gateway():
    logging.info("--- 5. Checking Ingress Gateway ---")

    # --- NEW: Use Library to get data reliably ---
    try:
        real_ingress_host, internal_ip = get_ingress_info()
        logging.info(f"Found Host: {real_ingress_host}, IP: {internal_ip}")
    except Exception as e:
        logging.error("Failed to get infrastructure info. Stopping test.")
        raise

    # --- OLD: Use your existing function to apply config ---
    # Since we have the real host now, we inject it immediately.
    # No patching needed!
    apply_yaml_template(
        template_path="ingress-gateway.yaml",
        use_safe_template=True, # Remember to use $VAR in your YAML
        TEST_GATEWAY_NAME="test-gateway",
        TEST_NAMESPACE="test-ns",
        INGRESS_HOST=real_ingress_host 
    )

    # --- Verify ---
    verify_url_connectivity(real_ingress_host, internal_ip)