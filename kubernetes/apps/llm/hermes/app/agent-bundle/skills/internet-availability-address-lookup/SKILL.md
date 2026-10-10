---
name: internet-availability-address-lookup
description: Use when asked what ISPs or fiber serve a US address.
---

# Address-level ISP/fiber availability (US)

Provider availability checkers (FCC map, CenturyLink/Quantum, AT&T, BroadbandNow) are bot-walled or city-level. The reliable path is the FCC Broadband Data Collection hexagon data republished as open ArcGIS FeatureServices (state broadband offices).

## Steps
1. Geocode the address. Nominatim often misses suburban streets; ArcGIS works nearly always:
   `https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine=<addr>`
2. Find a state broadband office hex layer (search ArcGIS Online):
   `https://www.arcgis.com/sharing/rest/search?q=broadband%20availability%20FCC%20<state>&f=json`
   Colorado known-good: `https://services3.arcgis.com/DgjqnJA1rgO92Soi/arcgis/rest/services/CO Coverage Hex (Public)/FeatureServer/0` (fields: brand_name, cov_type, serve_status, max_advertised_download, max_advertised_upload; check layer name for vintage).
3. Point-in-polygon query (curl, no auth):
   `.../FeatureServer/0/query?geometry={"x":LON,"y":LAT,"spatialReference":{"wkid":4326}}&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false&f=pjson`
   Each returned feature = one provider reporting service at that point. `cov_type=Fiber` + `serve_status=Served` = FTTH-eligible per FCC filings.
4. Cross-check with 1-2 provider exact-address flows where they work (Xfinity plan-builder works headless with Windows UA — see xfinity-availability-check skill). Treat provider "negative" answers as weaker than the hex data; they are address-parcel granular.

## Pitfalls
- FCC hosts (broadbandmap.fcc.gov, hosted.fcc.gov, geocoder.geohub.geoconnects.ai) were NXDOMAIN or Akamai-denied from this workstation — don't burn time there; the state-office ArcGIS mirror has the same BDC data.
- ispmap.org uses Nominatim only — fails silently on unlisted streets.
- Report the layer vintage (e.g. `v4_20240627`) when citing results.
- Generic ZIP aggregators (internetproviders.ai, broadbandnow, allconnect) contradict each other; never cite them for an exact address.
