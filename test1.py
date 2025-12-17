def wait_for_config_propagation(namespace, pod_name, search_keyword, timeout=30):
    """
    Polls the Envoy Admin API inside the target pod to confirm that a specific 
    configuration string (e.g., a route name) has been loaded.
    """
    logging.info("Waiting for config propagation... (looking for '%s')" % search_keyword)
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # Command: curl config_dump and grep for the keyword inside the pod
        # We use /bin/sh to enable the pipe (|) operator
        cmd = (
            "kubectl exec -n %s %s -c istio-proxy -- "
            "/bin/sh -c \"curl -s http://localhost:15000/config_dump | grep '%s'\""
        ) % (namespace, pod_name, search_keyword)
        
        # We don't need the output, just the exit code. 
        # Grep returns 0 if found, 1 if not found.
        try:
            # check=True will raise CalledProcessError if grep fails (not found)
            run_command(cmd, check=True)
            logging.info("Configuration '%s' detected in Envoy!" % search_keyword)
            return True
        except Exception:
            # Grep returned 1 (not found), wait and retry
            time.sleep(1)
            
    raise RuntimeError("Timeout waiting for Envoy config propagation: '%s'" % search_keyword)