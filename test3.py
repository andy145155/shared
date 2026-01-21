def recreate_namespace(core_api: client.CoreV1Api, namespace: str, timeout: int = 120):
    """
    Forcefully recreates a namespace.
    1. Deletes the existing namespace.
    2. Blocks until it is fully terminated (404).
    3. Creates a fresh namespace.
    """
    logger.warning(f"Recreating namespace '{namespace}' for a clean state...")

    # 1. Trigger Deletion
    try:
        core_api.delete_namespace(name=namespace)
        logger.info(f"Deletion triggered for {namespace}...")
    except ApiException as e:
        if e.status != 404: # Ignore if already gone
            raise

    # 2. Wait for Termination (Blocking)
    start_time = time.time()
    while True:
        try:
            core_api.read_namespace(name=namespace)
            
            # Check Timeout
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Namespace {namespace} stuck in Terminating state for > {timeout}s")
            
            time.sleep(2)
            
        except ApiException as e:
            if e.status == 404:
                # Gone! Break the loop.
                break
            raise # Unexpected API error

    # 3. Create Fresh
    logger.info(f"Old namespace terminated. Creating fresh: {namespace}")
    core_api.create_namespace(
        body=client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
    )