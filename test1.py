from contextlib import contextmanager

@contextmanager
def k8s_resource_manager(core_api, apps_api, custom_api, config, test_namespace):
    """
    Context manager that loads resources, yields them for use, 
    and guarantees cleanup happens afterwards.
    """
    resources = None
    try:
        # Setup: Load resources
        resources, loaded_file = load_manifests(config)
        logger.info(f"Loaded {len(resources)} resources from {loaded_file}")
        
        # Yield control back to the main function
        yield resources
        
    finally:
        # Teardown: Cleanup
        if resources:
            logger.info("Cleaning up Kubernetes resources...")
            cleanup_k8s_resources(core_api, apps_api, custom_api, resources, test_namespace)

def main():
    # ... init clients (core_api, etc.) ...
    
    try:
        # Check version, etc.
        # ...

        # The 'with' block handles the cleanup automatically
        with k8s_resource_manager(core_api, apps_api, custom_api, config, TEST_NAMESPACE) as resources:
            
            # 5. Deploy
            for res in resources:
                apply_resource(core_api, apps_api, custom_api, res, TEST_NAMESPACE)

            # 6. Verify
            if not wait_for_dns_propagation(...):
                 raise RuntimeError("DNS Propagation Failed")
                 
            # Note: You don't need to manually call cleanup_k8s_resources here anymore!
            # It happens automatically when this block exits, even if an error occurs.

    except Exception as e:
        logger.exception(f"Error: {e}")
        sys.exit(1)