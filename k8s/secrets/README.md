# K8s Secrets

Secrets are NOT stored in Git. Use one of:

1. **kustomize secretGenerator** (default):
   ```bash
   cp hermes-agent-secret.env.example hermes-agent-secret.env
   cp auth-secret.env.example auth-secret.env
   # Fill in real values, then: kubectl apply -k k8s/
   ```

2. **SealedSecrets / External Secrets Operator** (recommended for production):
   Replace the `secretGenerator` block in `kustomization.yaml` with your sealed secret manifests.

3. **Manual creation**:
   ```bash
   kubectl create secret generic hermes-agent-secret \
     --from-env-file=hermes-agent-secret.env -n hermes-platform
   kubectl create secret generic auth-secret \
     --from-env-file=auth-secret.env -n hermes-platform
   ```

The `.env` files are gitignored. Never commit real secret values.
