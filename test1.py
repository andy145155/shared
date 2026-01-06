import os
import time
import logging
import yaml
import boto3
from string import Template  # <--- Added for templating
from pathlib import Path
from typing import Dict, Tuple, Any, List, Optional

from kubernetes import client, config
from botocore.exceptions import ClientError, BotoCoreError

# --- Configuration ---
AWS_REGION = os.getenv("AWS_REGION", "ap-east-1")
HOSTED_ZONE_NAME = os.getenv("HOSTED_ZONE_NAME", "dmz.ap-east-1.dev-mox.com.")
MANIFEST_PATH = os.getenv("MANIFEST_PATH", "service-test.yaml")
POLL_TIMEOUT_SECONDS = int(os.getenv("POLL_TIMEOUT_SECONDS", 300))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 10))

# --- Dynamic Variables ---
# These are the variables we expect to find in the YAML
TEST_NAMESPACE = os.getenv("TEST_NAMESPACE", "verification-external-dns")
TEST_HOSTNAME = os.getenv("TEST_HOSTNAME", "external-dns-test.api.kong.dmz.ap-east-1.dev-mox.com")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def load_and_render_manifests(file_path: str) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    Reads a YAML template, substitutes env vars, and parses it.
    
    Returns:
        - List of resource dicts
        - The Namespace used (resolved)
        - The DNS Hostname used (resolved)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {file_path}")

    # 1. Read file as plain text
    with path.open("r") as f:
        template_content = f.read()

    # 2. Substitute Variables
    # We create a dictionary of values we want to inject
    context = {
        "TEST_NAMESPACE": TEST_NAMESPACE,
        "TEST_HOSTNAME": TEST_HOSTNAME
    }
    
    try:
        # safe_substitute replaces ${VAR} if found, leaves it alone if not (prevents crashes)
        rendered_content = Template(template_content).safe_substitute(context)
        logger.info(f"Rendered Manifest with Namespace='{TEST_NAMESPACE}' and Hostname='{TEST_HOSTNAME}'")
    except Exception as e:
        raise ValueError(f"Template substitution failed: {e}")

    # 3. Parse YAML
    try:
        docs = list(yaml.safe_load_all(rendered_content))
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse rendered YAML: {e}")

    if not docs:
        raise ValueError("YAML file resulted in empty content.")

    resources = [doc for doc in docs if doc]
    
    return resources, TEST_NAMESPACE, TEST_HOSTNAME


def initialize_k8s_clients() -> Tuple[client.CoreV1Api, client.AppsV1Api]:
    """Initializes K8s clients."""
    try:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig.")
    except config.ConfigException:
        logger.info("Loading in-cluster config.")
        config.load_incluster_config()
    
    return client.CoreV1Api(), client.AppsV1Api()


def apply_resource(core_api, apps_api, resource, namespace):
    kind = resource.get("kind")
    metadata = resource.get("metadata", {})
    name = metadata.get("name")
    
    # Ensure the resource uses the correct namespace (double check)
    if metadata.get("namespace") != namespace:
        logger.warning(f"Resource {kind}/{name} has namespace '{metadata.get('namespace')}' but expected '{namespace}'. Overriding.")
        metadata["namespace"] = namespace

    logger.info(f"Applying {kind}: {name} in {namespace}...")

    try:
        if kind == "Service":
            core_api.create_namespaced_service(namespace=namespace, body=resource)
        elif kind == "Deployment":
            apps_api.create_namespaced_deployment(namespace=namespace, body=resource)
        else:
            logger.warning(f"Unsupported Kind '{kind}'. Skipping.")
            return

        logger.info(f"✅ Created {kind}/{name}")

    except client.exceptions.ApiException as e:
        if e.status == 409:
            logger.warning(f"⚠️  {kind}/{name} already exists. Proceeding.")
        else:
            raise


def cleanup_resources(core_api, apps_api, resources, namespace):
    logger.info("--- Starting K8s Resource Cleanup ---")
    for res in resources:
        kind = res.get("kind")
        name = res.get("metadata", {}).get("name")
        
        try:
            if kind == "Service":
                core_api.delete_namespaced_service(name=name, namespace=namespace)
            elif kind == "Deployment":
                apps_api.delete_namespaced_deployment(name=name, namespace=namespace)
            logger.info(f"Deleted {kind}: {name}")
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.info(f"{kind}/{name} already gone.")
            else:
                logger.error(f"Failed to delete {kind}/{name}: {e}")

def wait_for_dns_propagation(route53_client, zone_id, record_name):
    # Ensure trailing dot
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    logger.info(f"Polling Route53 for: {target_dns}")
    
    start_time = time.time()
    while time.time() - start_time < POLL_TIMEOUT_SECONDS:
        try:
            response = route53_client.list_resource_record_sets(
                HostedZoneId=zone_id, StartRecordName=target_dns, MaxItems="1"
            )
            records = response.get("ResourceRecordSets", [])
            # Check for exact match
            if records and records[0]["Name"] == target_dns:
                logger.info(f"✅ DNS Record found: {target_dns}")
                return True
            
            time.sleep(POLL_INTERVAL_SECONDS)
        except (ClientError, BotoCoreError) as e:
            logger.warning(f"Polling error: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.error("❌ Timeout waiting for DNS.")
    return False

def cleanup_route53(route53_client, zone_id, dns_name):
    target_dns = dns_name if dns_name.endswith(".") else f"{dns_name}."
    try:
        response = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id, StartRecordName=target_dns, MaxItems="1"
        )
        changes = []
        for r in response.get("ResourceRecordSets", []):
            if r["Name"] == target_dns and r["Type"] in ["A", "TXT"]:
                changes.append({"Action": "DELETE", "ResourceRecordSet": r})
        
        if changes:
            logger.info(f"Cleaning {len(changes)} Route53 records...")
            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id, ChangeBatch={"Changes": changes}
            )
    except Exception as e:
        logger.error(f"Route53 Cleanup failed: {e}")


def main():
    try:
        # 1. Load and Render Config
        resources, namespace, dns_name = load_and_render_manifests(MANIFEST_PATH)

        # 2. Init Clients
        core_api, apps_api = initialize_k8s_clients()
        r53 = boto3.client("route53", region_name=AWS_REGION)

        # 3. Get Zone ID
        zones = r53.list_hosted_zones_by_name(DNSName=HOSTED_ZONE_NAME)
        zone_id = next((z["Id"].split("/")[-1] for z in zones.get("HostedZones", [])
                        if z["Name"] in [HOSTED_ZONE_NAME, HOSTED_ZONE_NAME + "."]), None)
        
        if not zone_id:
            logger.critical(f"Hosted Zone {HOSTED_ZONE_NAME} not found.")
            return

        try:
            # 4. Deploy
            for res in resources:
                apply_resource(core_api, apps_api, res, namespace)

            # 5. Verify
            if wait_for_dns_propagation(r53, zone_id, dns_name):
                logger.info("🎉 VERIFICATION SUCCESSFUL")
            else:
                raise RuntimeError("Verification Failed: DNS not found.")

        finally:
            # 6. Cleanup
            cleanup_resources(core_api, apps_api, resources, namespace)
            cleanup_route53(r53, zone_id, dns_name)

    except Exception as e:
        logger.critical(f"Script failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()