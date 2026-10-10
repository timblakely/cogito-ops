---
name: oidc-integration-debugging
description: Debug OIDC login failures across apps and providers.
version: 0.1.0
author: Tim Blakely, Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [oidc, oauth, kubernetes, debugging, identity]
    related_skills: [systematic-debugging]
---

# OIDC Integration Debugging

Use this skill for OAuth/OIDC failures spanning an application, an identity provider, Kubernetes Secrets, and possibly an operator or controller. It isolates user authentication from client authentication, proves the failing protocol boundary, and repairs the declarative source rather than masking drift.

## When to Use

- A login page reports a generic password or email error during an OIDC flow.
- The authorization page works but the callback or token exchange fails.
- A Kubernetes-managed OIDC client, Secret, or operator appears healthy while authentication fails.
- An app and identity provider disagree about client mode, secret, callback, or identifier.

Do not use this for a purely local username/password failure with no federated flow.

## Procedure

1. Capture the exact user-visible error and the application log around one attempt. Identify whether the failure occurs at authorization, callback, token exchange, userinfo, or session creation. Completion: the failing protocol stage and upstream HTTP error are named.

2. Prove the user's side independently. Check the identity provider audit trail or authorization response for successful sign-in and authorization-code issuance. Completion: user authentication is either confirmed or ruled out before changing credentials.

3. Build a tight probe for the failing boundary. For a token exchange, use the live issuer token endpoint and the live client ID/secret without printing secret values; assert the exact status and OAuth error. Completion: the probe reproduces the failure and can later prove the repair.

4. Compare the client across layers without exposing secrets:
   - application effective environment/config,
   - Kubernetes Secret keys and decoded value metadata,
   - identity-provider persisted client record,
   - declarative CR or operator resource and status.
   Compare presence, length, hash/prefix metadata, public/confidential mode, client ID, callback URLs, and scopes; never log secret contents. Completion: the first layer where state diverges is identified.

5. Compare the broken client with a working client of the same type. Read the CRD/schema and operator docs or manifests to distinguish supported settings such as `isPublic`, PKCE, secret generation, key names, and callback handling. Completion: a falsifiable root-cause hypothesis explains the difference.

6. Repair the declarative owner, not the provider database. Prefer a supported operator reconciliation or client re-registration path. Preserve identifiers only when the controller/provider supports it; otherwise plan for one-time reauthorization and dependent rollout. Completion: the manifest or controlled resource change is applied and reconciled.

7. Re-run the same probe, then exercise the complete browser/application flow. Verify the operator status, generated Secret, workload rollout, callback, token exchange, and user session. Completion: both the narrow protocol probe and the end-to-end login pass.

## Pitfalls

- Treat a generic "wrong password" banner as a user credential diagnosis only after checking the token exchange; applications often reuse it for every OAuth callback error.
- Do not conclude that a Kubernetes Secret matches the provider because the application reads it successfully; operators can write a Secret while the provider record is empty, stale, or mismatched.
- Do not trust `Ready` or `in sync` alone; controller health can describe reconciliation state while runtime authentication still fails.
- Do not hand-edit the identity-provider database when a controller owns the client; direct edits are commonly overwritten and bypass generated-secret/key conventions.
- Compare public versus confidential mode explicitly; a public PKCE client and a confidential client have different valid secret behavior.
- Redact values while comparing credentials. Use lengths, hashes, prefixes, or equality checks in command output, never the secret itself.
- Inspect a working sibling client before inventing a repair. It exposes provider-specific conventions faster than generic OAuth documentation.

## Verification

A diagnosis is complete only when all are true:

- The user's authorization result and the application's failing OAuth stage are separately evidenced.
- The same red-capable probe fails before repair and passes afterward.
- The declarative resource, provider record, Kubernetes Secret, and workload configuration agree on non-secret metadata and credential identity.
- A full login reaches the application session, not merely the provider login page.
- Any new client ID, reauthorization requirement, rollout, or remaining controller warning is reported explicitly.
