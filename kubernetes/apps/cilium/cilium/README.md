# Cilium

Two things live under here: the Helm release (`app/` — values, Hubble block,
plus a hand-maintained Grafana dashboard) and the L2/BGP networking stack
(`networking/`), which is rendered from the SOPS-backed schemas rather than
edited directly.

## UniFi BGP

Cilium peers with the UniFi gateway: local ASN **64514**, peer **192.168.1.1**
(ASN **64513**), ipv4 unicast, defined by `CiliumBGPClusterConfig
l3-bgp-cluster-config` in `networking/networking.yaml`. LoadBalancer addresses
are allocated from the `pool` CiliumLoadBalancerIPPool, `192.168.69.0/24`.

The gateway must accept a session from **every** node. The peer list is built at
render time from `schemas/node_schema.json`, so adding a node means editing that
schema (`name` + `address`) — never `networking.yaml` by hand. `bgp.conf` next to
this file is the UniFi-controller-side mirror of the same list and is the file to
read for current peers: as of 2026-10-23 it carries seven neighbors,
`192.168.42.10`–`.16`, matching `nuc-1/2/3`, `iggy`, `kristeva`, `amnesia`,
`deleuze`. It also sets `no bgp ebgp-requires-policy`, which lets the gateway
accept advertised prefixes it has no export policy for.

Check the session from inside the cluster:

```sh
kubectl -n cilium exec ds/cilium -- cilium bgp peers
```

A healthy session reads `established` with non-zero Received/Advertised counts.
`Received 0` on an established session points at the gateway's policy, not at
Cilium.

## Observability

Hubble has a block in `app/helm/values.yaml`. The Grafana dashboard in
`app/grafanadashboard.yaml` is hand-maintained — there is no generator for it,
but `scripts/validate-grafana-dashboard.py` checks it, so run that before
pushing a dashboard edit.
