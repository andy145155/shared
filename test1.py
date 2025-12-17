def get_pod_name(namespace, app_label):
    """
    Dynamically fetches the name of a running pod that matches the given app label.
    Example: app_label="verify-target" -> returns "verify-target-6fc958c5d7-mvsp6"
    """
    cmd = (
        "kubectl get pods -n %s -l app=%s "
        "-o jsonpath='{.items[0].metadata.name}'"
    ) % (namespace, app_label)

    # We check=False because if no pods exist yet, we might want to retry
    stdout, stderr = run_command(cmd, check=False)
    
    pod_name = stdout.strip()
    if not pod_name:
        raise RuntimeError("No pods found with label 'app=%s' in namespace '%s'" % (app_label, namespace))
        
    return pod_name
    

def wait_for_config_propagation(namespace, app_label, grep_cmd_arg, timeout=30):
    """
    1. Resolves the app label to a real Pod Name.
    2. Polls that specific Pod's Envoy Admin API for the config.
    """
    # Step 1: Resolve Label -> Pod Name
    # We might need to retry this loop in case the pod is still creating
    start_time = time.time()
    pod_name = None
    
    while time.time() - start_time < timeout:
        try:
            pod_name = get_pod_name(namespace, app_label)
            break
        except Exception:
            time.sleep(1)
    
    if not pod_name:
        raise RuntimeError("Timeout: Could not find any pod for app '%s'" % app_label)

    logging.info(
        "Checking config on Pod '%s' (Label: %s) for keyword '%s'..." % 
        (pod_name, app_label, grep_cmd_arg)
    )
    
    # Step 2: Poll Envoy Config
    # Reuse the remaining time for the config check
    remaining_time = timeout - (time.time() - start_time)
    
    while time.time() - start_time < timeout:
        cmd = (
            "kubectl exec -n %s %s -c istio-proxy -- "
            "/bin/sh -c \"curl -s http://localhost:15000/config_dump | "
            "grep '%s'\""
        ) % (namespace, pod_name, grep_cmd_arg)
        
        try:
            run_command(cmd, check=True)
            logging.info("Confirmed: Config found on '%s'!" % pod_name)
            return True
        except Exception:
            time.sleep(1)
            
    raise RuntimeError("Timeout: Config '%s' never appeared on '%s'" % (grep_cmd_arg, pod_name))