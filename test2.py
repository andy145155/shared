def detect_external_dns_config(core_api, namespace, label_selector, expected_version=None) -> VerificationConfig:
    """
    Inspects the running external-dns Pod to extract Version, Mode, Sources, and Zone Type.
    """
    logger.info(f"🕵️ Inspecting external-dns in {namespace}...")
    
    # Defaults
    mode = "sync"
    sources = set()
    is_private = False
    detected_version = "unknown"

    try:
        pods = core_api.list_namespaced_pod(namespace, label_selector=label_selector)
        if not pods.items:
            logger.warning("   - No Pods found. Using defaults.")
            return VerificationConfig("sync", {"service"}, False, "unknown")
        
        pod = pods.items[0]
        container = next((c for c in pod.spec.containers if c.name == "external-dns"), pod.spec.containers[0])
        
        # --- 1. Version Check ---
        image_str = container.image
        detected_version = image_str.split(":")[-1]
        logger.info(f"   - Detected Version: {detected_version}")

        if expected_version:
            # Normalize (remove 'v' prefix if present)
            clean_detected = detected_version.lstrip("v")
            clean_expected = expected_version.lstrip("v")
            
            if clean_detected != clean_expected:
                raise RuntimeError(
                    f"❌ VERSION MISMATCH: Expected '{expected_version}' but found '{detected_version}'"
                )
            logger.info("   - ✅ Version verification passed.")

        # --- 2. Configuration Check ---
        args = container.args or []
        for arg in args:
            if "--policy=upsert-only" in arg:
                mode = "upsert-only"
            if "--source=" in arg:
                sources.add(arg.split("=", 1)[1])
            if "--aws-zone-type=private" in arg:
                logger.info("   - Detected Zone Type: PRIVATE")
                is_private = True

        if not sources:
            sources.add("service")

        logger.info(f"   - Config: Mode={mode.upper()} | Sources={sources} | PrivateZone={is_private}")
        return VerificationConfig(mode, sources, is_private, detected_version)

    except Exception as e:
        logger.error(f"   - Detection failed: {e}")
        # If strict version checking was requested and failed, re-raise the error
        if expected_version:
            raise
        return VerificationConfig("sync", {"service"}, False, "unknown")