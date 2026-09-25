# ntfy

ntfy is the private Android notification transport and Matrix UnifiedPush
gateway. It is available at `https://ntfy.${DOMAIN_NAME}` through the internal
Envoy gateway, so the Android distributor needs LAN or WireGuard connectivity.

The server denies access by default. Anonymous callers may only write random
`up*` UnifiedPush topics, as required by the protocol; the authenticated `tim`
distributor account may read them. The Android ntfy app must use that account
when serving as a distributor for a Matrix client. Sable's built-in distributor
currently opens an unauthenticated subscription, so it cannot replace the ntfy
Android app with these access rules. The two generated native accounts also
support direct agent alerts:

- `tim` can read UnifiedPush `up*` topics and read/write `tim-agent-*` topics.
- `agent` can only write `tim-agent-*` topics.

The passwords live in the `ntfy` item in the 1Password `Kubernetes` vault as
`NTFY_TIM_PASSWORD` and `NTFY_AGENT_PASSWORD`. External Secrets syncs them into
the `ntfy-credentials` Secret and derives ntfy's bcrypt user configuration. They
remain separate from Pocket ID because ntfy does not support native OIDC.
Retrieve a password when configuring a client without printing it into shared
logs:

```shell
KUBECONFIG=/home/tim/git/cogito/kubeconfig kubectl get secret \
  -n observability ntfy-credentials -o jsonpath='{.data.tim_password}' \
  | base64 -d
```

Messages are cached on the backed-up PVC for seven days. That permits replay
after a phone or WireGuard outage; it is not the durable state of an agent
workflow.

ntfy also serves Matrix gateway discovery and delivery at
`https://ntfy.${DOMAIN_NAME}/_matrix/push/v1/notify`. A Matrix client such as
Sable can discover this gateway from the endpoint returned by the ntfy Android
distributor. The client's custom gateway URL field is an override; leave it
empty when discovery selects this ntfy host. The Android app's default server
field takes the base URL, `https://ntfy.${DOMAIN_NAME}`.
See [Matrix Android push setup](../../home-infra/matrix/README.md#android-push-setup-and-acceptance)
for the current client steps.

For a direct smoke test, subscribe the Android ntfy app to
`tim-agent-smoke`, then publish with the `agent` credentials:

```shell
curl --user agent:REDACTED \
  --header 'Title: Cogito agent smoke test' \
  --header 'Priority: high' \
  --data 'Direct notification delivery is working.' \
  https://ntfy.${DOMAIN_NAME}/tim-agent-smoke
```
