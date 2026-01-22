import boto3

def get_instances_with_double_lookup(replication_group_id, region_name='us-east-1'):
    client = boto3.client('elasticache', region_name=region_name)

    # 1. Get the Replication Group Topology
    print(f"Fetching topology for: {replication_group_id}...")
    rg_response = client.describe_replication_groups(
        ReplicationGroupId=replication_group_id
    )
    
    # We assume usually 1 replication group matches the ID
    rep_group = rg_response['ReplicationGroups'][0]
    node_groups = rep_group.get('NodeGroups', [])

    for shard in node_groups:
        shard_id = shard.get('NodeGroupId')
        print(f"\n--- Processing Shard: {shard_id} ---")
        
        # In Cluster Mode Enabled, the "PrimaryEndpoint" *should* be here at the Shard level.
        # If it is missing (as you found), we must resolve the members manually.
        
        for member in shard.get('NodeGroupMembers', []):
            # The member has the ID but often no Endpoint info
            cache_cluster_id = member.get('CacheClusterId')
            member_role = member.get('CurrentRole', 'unknown') # Often missing in Cluster Mode Enabled
            
            if cache_cluster_id:
                # 2. THE DOUBLE LOOKUP: Resolve the ID to an Endpoint
                try:
                    cluster_response = client.describe_cache_clusters(
                        CacheClusterId=cache_cluster_id,
                        ShowCacheNodeInfo=True # Crucial flag to get endpoints
                    )
                    
                    # There is usually only 1 cluster in the list when querying by ID
                    # And usually 1 node per cluster in this context
                    cluster_info = cluster_response['CacheClusters'][0]
                    cache_nodes = cluster_info.get('CacheNodes', [])
                    
                    if cache_nodes:
                        endpoint = cache_nodes[0].get('Endpoint', {})
                        addr = endpoint.get('Address')
                        port = endpoint.get('Port')
                        
                        print(f"Node: {cache_cluster_id}")
                        print(f"  > Address: {addr}:{port}")
                        print(f"  > Role (API hint): {member_role}")
                        
                        # Note: If API Role is unknown, you must ask Redis directly (see below)
                        
                except Exception as e:
                    print(f"  > Could not resolve details for {cache_cluster_id}: {e}")

# Usage
get_instances_with_double_lookup('my-cluster-id')