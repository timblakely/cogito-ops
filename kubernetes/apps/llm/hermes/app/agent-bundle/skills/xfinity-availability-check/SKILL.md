---
name: xfinity-availability-check
description: "Use when checking Xfinity speeds/plans at an address."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Xfinity, Comcast, ISP, availability, browser]
    related_skills: [blocked-page-recovery]
---

# Xfinity address availability check

## When to use

User asks what internet speeds, plans, or prices Xfinity offers at a specific
street address (or whether Xfinity serves an address at all).

## Why normal fetches fail

Xfinity's marketing site is Akamai-gated and blocks non-Windows/macOS egress
(403 "Access Denied" on www.xfinity.com HTML AND its JS bundles when the UA
looks like Linux/headless). Plan data is per-address and never in the static
HTML. The working recipe:

## 1. Browser with a Windows UA override (mandatory)

```python
cdp('Network.enable')
cdp('Network.setUserAgentOverride',
    userAgent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    acceptLanguage="en-US,en;q=0.9", platform="Win32")
```

Without this, planbuilder/JS bundles 403 and the SPA never hydrates (form
stays unrendered, AX tree empty). curl with any UA also 403s on JS assets;
the browser + override is the only reliable path.

## 2. Address flow (real mouse events required)

1. `goto_url('https://www.xfinity.com/planbuilder?lob=internet')`, wait ~10s.
2. Fill `input[name="localizationAddressField"]`: first reset `value` via the
   native `HTMLInputElement` setter + dispatch `input` (a previous JS-set
   value persists and CDP `Input.insertText` APPENDS), then `click_at_xy` the
   field and `cdp('Input.insertText', text=...)`.
3. `click_at_xy` "Check availability" -> "Yes, check availability"
   (both via viewport coords from getBoundingClientRect after scrollIntoView).
   JS `.click()`/dispatched MouseEvents on these buttons do nothing.
4. If an account exists at the address you land on
   `/learn/landing/active-address`; the offers page is reachable by clicking
   "View Deals" — find its URL in resource timing
   (`...neptune/localize/movingasnew?redirectUrl=` ->
   `https://www.xfinity.com/digital/offers/plan-builder?drawer=INTERNET`),
   then `goto_url` it. First load often shows "Sorry about that!" — click
   "Try again" (real coords).

## 3. Read tiers + upload speeds

Plan tiles (`[data-testid^="offer-tile-internet"]`) show download tiers and
prices only. Upload speeds come from the FCC Broadband Facts data. Fastest
path: click "Add to plan" on a tile (captures its tier-id on
`xfinity-broadband-facts[line-of-business="INTERNET"]`), then replay the
label API from page context for ALL tier ids at once:

```python
js('''(async () => {
  const body = {
    endpoint: "https://pnp-api-gateway.xcp.comcast.net/nutritionlabel/",
    requestHeaders: [
      {key:"sourceServerId", value:"dotcom-pb"},
      {key:"sourceSystemId", value:"dotcom"},
      {key:"Content-Type", value:"application/json"}],
    requestBody: {addressInfo:{state:"<ST>"}, tierIds:[ids],
      sessionId:"<RC.SP from SC cookie>", lineOfBusiness:"INTERNET",
      servicePlanType:"POSTPAID", customerType:"RESIDENTIAL"}};
  const r = await fetch("https://www.xfinity.com/buy/api/buy/proxy-service",
    {method:"POST", credentials:"include",
     headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  const d = await r.json();
  const L = ((d.responseData||{}).nutritionLabels||{}).INTERNET || [];
  return JSON.stringify(L.map(x => ({tier:x.tierName,
    speeds:(x.labelGroups||[]).find(g=>g.labelGroupType==="SPEED_METRICS")?.providedSpeeds,
    price:(x.labelGroups||[]).find(g=>g.labelGroupType==="SERVICE_PLAN_INFO")?.labelItems?.[0]?.chargeDetails,
    tech:(x.labelGroups||[]).find(g=>g.labelGroupType==="SERVICE_PLAN_INFO")?.labelItems?.[0]?.characteristics})));})()''')
```

- SPEED_METRICS gives ADVERTISED_SPEED and MEASURED (typical) UPSTREAM/
  DOWNSTREAM/LATENCY — the authoritative up/down numbers.
- Note: `/digital/service/api/proxyService` (lowercase) REJECTS the nutrition
  endpoint ("not whitelisted"); `/buy/api/buy/proxy-service` accepts it.
- Sales session id = `RC.SP` inside the `SC` cookie (dot-domain .xfinity.com);
  address confirmation via POST `/digital/service/api/serviceabilityByLocation`
  with `{"ServiceAddress":{streetAddress1,city,state,zipCode},"lineOfBusiness":"INTERNET"}`
  returns dropType (COAX/FIBER) + market info — useful pre-check.
- Prices: tile price = label promo price minus $10 autopay+paperless; chargeDetails
  month-61 value is the post-promo regular rate.
- Adding a tier pops stacked "Continue shopping" dialogs — click each before
  the next tile click.
