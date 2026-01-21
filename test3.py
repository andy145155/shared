import logging
import time
from contextlib import contextmanager
from typing import Tuple
from kubernetes import client, config as k8s_config, utils
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

Clients = Tuple[client.ApiClient, client.CoreV1Api]

def wait_for_namespace_termination(core_api: client.CoreV1Api, namespace: str, timeout: int = 120):
    """
    Reusable blocking function.
    Waits until the namespace returns 404 (Gone).
    """
    logger.info(f"Waiting for namespace '{namespace}' to terminate...")
    start_time = time.time()
    
    while True:
        try:
            core_api.read_namespace(name=namespace)
            
            # Still exists? Check timeout.
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Namespace {namespace} stuck in Terminating state for > {timeout}s")
            
            time.sleep(2)
            
        except ApiException as e:
            if e.status == 404:
                logger.info(f"Namespace '{namespace}' is fully terminated.")
                return # Success
            raise # Unexpected API error

def recreate_namespace(core_api: client.CoreV1Api, namespace: str):
    """
    Nuke and Pave strategy.
    """
    logger.warning(f"Recreating namespace '{namespace}' for a clean state...")

    # 1. Trigger Deletion
    try:
        core_api.delete_namespace(name=namespace)
    except ApiException as e:
        if e.status != 404: 
            raise

    # 2. Re-use the wait logic
    wait_for_namespace_termination(core_api, namespace)

    # 3. Create Fresh
    logger.info(f"Creating fresh namespace: {namespace}")
    core_api.create_namespace(
        body=client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
    )

@contextmanager
def infrastructure_manager(clients: Clients, namespace: str, cleanup: bool = True):
    """
    Context Manager.
    Setup: Ensures Fresh Namespace.
    Teardown: Deletes AND Waits (so the CI job doesn't leave 'Terminating' junk).
    """
    _, core_api = clients
    
    # --- SETUP ---
    try:
        core_api.create_namespace(
            body=client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        logger.info(f"Created namespace: {namespace}")
    except ApiException as e:
        if e.status == 409:
            recreate_namespace(core_api, namespace)
        else:
            raise

    try:
        yield
    finally:
        # --- TEARDOWN ---
        if cleanup:
            logger.info(f"[Cleanup] Deleting namespace '{namespace}'...")
            try:
                core_api.delete_namespace(name=namespace)
                
                # OPTIONAL: Now we reuse the logic to ensure a clean exit
                # This guarantees the next job won't hit a "Terminating" conflict
                wait_for_namespace_termination(core_api, namespace, timeout=60)
                
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"[Cleanup] Failed to delete/wait: {e}")