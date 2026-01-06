import os
import time
import logging
import yaml
import boto3
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List

from kubernetes import client, config
from botocore.exceptions import ClientError, BotoCoreError

# --- Configuration via Environment Variables ---
# Best Practice: Use defaults for local dev, but allow overrides for CI/CD
AWS_REGION = os.getenv("AWS_REGION", "ap-east-1")
HOSTED_ZONE_NAME = os.getenv("HOSTED_ZONE_NAME", "dmz.ap-east-1.dev-mox.com.")
MANIFEST_PATH = os.getenv("MANIFEST_PATH", "service-test.yaml")
POLL_TIMEOUT_SECONDS = int(os.getenv("POLL_TIMEOUT_SECONDS", 300))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 10))

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def load_service_manifest(file_path: str) -> Tuple[Dict[str, Any], str, str, str]:
    """
    Parses the Kubernetes Service YAML to extract metadata and annotations.

    Args:
        file_path: Path to the YAML file.

    Returns:
        Tuple containing:
            - The full manifest dict
            - Namespace
            - Service Name
            - Target DNS Hostname (from annotation)

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If essential annotations are missing.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {file_path}")

    with path.open("r") as f:
        try:
            manifest = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML: {e}")

    metadata = manifest.get("metadata", {})
    namespace = metadata.get("namespace", "default")
    service_name = metadata.get("name")
    annotations = metadata.get("annotations", {})

    # Extract the critical ExternalDNS annotation
    dns_hostname = annotations.get("external-dns.alpha.kubernetes.io/hostname")

    if not service_name:
        raise ValueError("YAML metadata is missing the 'name' field.")
    if not dns_hostname:
        raise ValueError(
            "YAML is missing the 'external-dns.alpha.kubernetes.io/hostname' annotation."
        )

    return manifest, namespace, service_name, dns_hostname


def initialize_k8s_client() -> client.CoreV1Api:
    """Initializes the Kubernetes CoreV1Api client."""
    try:
        config.load_kube_config()  # Local kubeconfig
        logger.info("Loaded local kubeconfig.")
    except config.ConfigException:
        logger.info("Loading in-cluster config.")
        config.load_incluster_config()  # In-cluster (Pod) config
    
    return client.CoreV1Api()


def get_route53_zone_id(route53_client: Any, zone_name: str) -> Optional[str]:
    """Fetches the Hosted Zone ID for a given domain name."""
    try:
        response = route53_client.list_hosted_zones_by_name(DNSName=zone_name)
        for zone in response.get("HostedZones", []):
            # AWS API may return zones that are lexicographically after the name,
            # so we must check for an exact match.
            if zone["Name"] in [zone_name, f"{zone_name}."]:
                # Zone ID format is usually '/hostedzone/Z12345'
                return zone["Id"].split("/")[-1]
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to list hosted zones: {e}")
    
    return None


def wait_for_dns_propagation(
    route53_client: Any, 
    zone_id: str, 
    record_name: str, 
    timeout: int = POLL_TIMEOUT_SECONDS
) -> bool:
    """
    Polls AWS Route53 until the record appears or timeout is reached.
    
    Args:
        route53_client: Boto3 Route53 client.
        zone_id: The ID of the hosted zone.
        record_name: The DNS record to verify.
        timeout: Max seconds to wait.

    Returns:
        True if found, False otherwise.
    """
    # Ensure standard AWS format (trailing dot)
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    
    logger.info(f"Polling Route53 for record: {target_dns} (Timeout: {timeout}s)...")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = route53_client.list_resource_record_sets(
                HostedZoneId=zone_id,
                StartRecordName=target_dns,
                MaxItems="1"
            )
            
            records = response.get("ResourceRecordSets", [])
            if records:
                found_name = records[0]["Name"]
                if found_name == target_dns:
                    logger.info(f"✅ Record found: {found_name}")
                    return True
            
            logger.debug("Record not found yet. Retrying...")
            time.sleep(POLL_INTERVAL_SECONDS)

        except (ClientError, BotoCoreError) as e:
            logger.warning(f"Error during polling: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.error("❌ Timeout waiting for DNS record creation.")
    return False


def cleanup_test_fixtures(
    core_v1_api: client.CoreV1Api,
    route53_client: Any,
    zone_id: str,
    namespace: str,
    service_name: str,
    dns_name: str
) -> None:
    """
    Performs cleanup of Kubernetes resources and Route53 records.
    Designed to run inside a 'finally' block to guarantee execution.
    """
    logger.info("--- Starting Cleanup Phase ---")

    # 1. Delete Kubernetes Service
    try:
        logger.info(f"Deleting Kubernetes Service: {service_name}...")
        core_v1_api.delete_namespaced_service(name=service_name, namespace=namespace)
        logger.info("Service deletion request sent.")
    except client.exceptions.ApiException as e:
        if e.status == 404:
            logger.info("Service already deleted or not found.")
        else:
            logger.error(f"Failed to delete service: {e}")

    # 2. Delete Route53 Record (Self-Cleaning)
    target_dns = dns_name if dns_name.endswith(".") else f"{dns_name}."
    
    try:
        # We must fetch the record first to get the exact details for deletion
        response = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id,
            StartRecordName=target_dns,
            MaxItems="1"
        )
        
        changes: List[Dict[str, Any]] = []
        for record in response.get("ResourceRecordSets", []):
            if record["Name"] == target_dns and record["Type"] in ["A", "TXT"]:
                changes.append({
                    "Action": "DELETE",
                    "ResourceRecordSet": record
                })
        
        if changes:
            logger.info(f"Deleting {len(changes)} stale records from Route53...")
            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={"Changes": changes}
            )
            logger.info("Route53 cleanup complete.")
        else:
            logger.info("No stale Route53 records found to clean.")

    except (ClientError, BotoCoreError) as e:
        logger.error(f"Failed to clean up Route53: {e}")


def main():
    """Main execution flow."""
    try:
        # 1. Parse Configuration
        manifest, namespace, service_name, dns_name = load_service_manifest(MANIFEST_PATH)
        logger.info(f"Config Loaded | Service: {service_name} | Namespace: {namespace}")
        logger.info(f"Target DNS: {dns_name}")

        # 2. Initialize Clients
        core_v1_api = initialize_k8s_client()
        route53_client = boto3.client("route53", region_name=AWS_REGION)

        # 3. Validate AWS Zone
        zone_id = get_route53_zone_id(route53_client, HOSTED_ZONE_NAME)
        if not zone_id:
            logger.critical(f"Hosted Zone '{HOSTED_ZONE_NAME}' not found in region {AWS_REGION}.")
            return

        try:
            # 4. Deploy Test Service
            logger.info(f"Applying manifest from {MANIFEST_PATH}...")
            try:
                core_v1_api.create_namespaced_service(namespace=namespace, body=manifest)
                logger.info("Service created successfully.")
            except client.exceptions.ApiException as e:
                if e.status == 409:
                    logger.warning("Service already exists. Proceeding to verification.")
                else:
                    raise

            # 5. Verify Propagation
            is_verified = wait_for_dns_propagation(route53_client, zone_id, dns_name)
            
            if not is_verified:
                raise RuntimeError("Verification failed: DNS record did not propagate in time.")
            
            logger.info("🎉 Verification PASSED.")

        except Exception as e:
            logger.error(f"Workflow failed: {e}")
            raise

        finally:
            # 6. Guaranteed Cleanup
            cleanup_test_fixtures(
                core_v1_api, 
                route53_client, 
                zone_id, 
                namespace, 
                service_name, 
                dns_name
            )

    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        exit(1)


if __name__ == "__main__":
    main()