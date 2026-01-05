import yaml

# 1. The Discovery Script (Lua)
discovery_lua = """
actions = {}
if obj.metadata.labels and obj.metadata.labels["argocd.custom-action/retryable"] == "true" then
  actions["retry"] = {
    name = "Retry Verification",
    title = "Retry Verification",
    disabled = false
  }
end
return actions
"""

# 2. The Action Script (Lua)
action_lua = """
local os = require("os")
local newJob = {}
newJob.apiVersion = "batch/v1"
newJob.kind = "Job"
newJob.metadata = {}
newJob.metadata.name = obj.metadata.name .. "-retry-" .. os.time()
newJob.metadata.namespace = obj.metadata.namespace

-- Deep Copy Labels manually to avoid reference issues
newJob.metadata.labels = {}
if obj.metadata.labels then
  for k,v in pairs(obj.metadata.labels) do
    newJob.metadata.labels[k] = v
  end
end

-- Clean up system labels
newJob.metadata.labels["controller-uid"] = nil
newJob.metadata.labels["job-name"] = nil

-- Copy Spec
newJob.spec = obj.spec
newJob.spec.selector = nil
newJob.spec.template.metadata.labels["controller-uid"] = nil
newJob.spec.template.metadata.labels["job-name"] = nil

return {
  k8s = {
    version = "batch/v1",
    kind = "Job",
    operation = "create",
    resource = newJob
  }
}
"""

# 3. Construct the YAML structure
# We build the inner object first, then dump it to a string
customization_block = {
    "discovery.lua": discovery_lua.strip(),
    "definitions": [
        {
            "name": "retry",
            "action.lua": action_lua.strip()
        }
    ]
}

# Dump the inner block to a YAML string
inner_yaml_string = yaml.dump(customization_block, default_flow_style=False, sort_keys=False)

# 4. Create the final Kubernetes Resource
k8s_resource = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "argocd-cm",
        "namespace": "argocd"
    },
    "data": {
        "resource.customizations.actions.batch_Job": inner_yaml_string
    }
}

# 5. Write to file
with open("argocd-fix-final.yaml", "w") as f:
    yaml.dump(k8s_resource, f, default_flow_style=False, sort_keys=False)

print("✅ Success! Created 'argocd-fix-final.yaml'.")