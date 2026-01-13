# lib/test_runner.py
from lib import k8s, route53

def run_test_suite(source_name: str, manifest_path: str, clients: K8sClients, route53_client, config):
    core, apps, net, custom = clients
    unique_hostname = f"{source_name}-test.{config.base_domain}"
    
    logger.info(f"🔹 TESTING SOURCE: {source_name}")

    try:
        # --- 1. K8s Lifecycle (Context Manager) ---
        # When this block exits, K8s resources are deleted automatically.
        with k8s.k8s_resource_manager(core, apps, net, custom, manifest_path, "test-ns", unique_hostname) as resources:
            
            # Deploy
            for res in resources:
                k8s.apply_resource(core, apps, net, custom, res, "test-ns")

            # Verify Creation
            if not route53.wait_for_propagation(route53_client, config.zone_id, unique_hostname):
                 raise RuntimeError(f"Creation Verification failed for {source_name}")

        # --- 2. Verify Deletion (ExternalDNS Logic) ---
        # K8s resources are gone. Now we check if ExternalDNS did its job.
        if config.policy == "sync":
            if not route53.wait_for_deletion(route53_client, config.zone_id, unique_hostname):
                raise RuntimeError(f"Deletion Verification failed for {source_name}")

    except Exception:
        logger.exception(f"❌ Test Failed for {source_name}")
        raise # Re-raise so main.py knows it failed

    finally:
        # --- 3. THE SAFETY NET ---
        # Always force cleanup the Route53 record.
        # This saves money and prevents conflicts if ExternalDNS failed.
        logger.info(f"🧹 Finalizing cleanup for {unique_hostname}...")
        route53.cleanup_record(route53_client, config.zone_id, unique_hostname)

# lib/route53.py
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

def cleanup_record(route53_client, zone_id, hostname):
    """
    Force deletes a TXT and A record if they exist.
    Suppresses errors if the record is already gone.
    """
    # We typically need to clean both the A record and the TXT owner record
    for record_type in ["A", "TXT"]:
        try:
            # 1. We must GET the record first to know its current 'TTL' and 'Value'
            # Route53 DELETE requires the exact state of the record to match.
            response = route53_client.list_resource_record_sets(
                HostedZoneId=zone_id,
                StartRecordName=hostname,
                StartRecordType=record_type,
                MaxItems="1"
            )
            
            sets = response.get('ResourceRecordSets', [])
            
            # Check if we actually found the exact record we are looking for
            if not sets or sets[0]['Name'].rstrip('.') != hostname.rstrip('.') or sets[0]['Type'] != record_type:
                logger.debug(f"Record {hostname} ({record_type}) already deleted.")
                continue

            # 2. Issue the Delete
            change_batch = {
                'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': sets[0]
                }]
            }
            
            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch=change_batch
            )
            logger.info(f"Force deleted orphan record: {hostname} ({record_type})")

        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidChangeBatch':
                logger.warning(f"Could not delete {hostname}: Record might have changed or does not exist.")
            else:
                logger.warning(f"Route53 Cleanup Error: {e}")