# Meeting 1 – Intermittent HTTP 502 & Long-Lived Connection Drops

**Date**: 2025-01-10  
**Attendees**: Samarth, Sahana, KK  

## Agenda
1. Review intermittent HTTP 502 errors on the main API.
2. Investigate dropped long-lived connections from the dashboard.

## Discussion Summary

- **HTTP 502 issue**
  - Samarth explained that some client requests to the main API return *HTTP 502 Bad Gateway* through the gateway, while others succeed.
  - KK confirmed that backend pods are occasionally restarting during higher load.
  - Sahana mentioned that health checks might still be targeting an old path that responds slowly when the service is warm.

- **Long-lived connections being dropped**
  - KK noted that WebSocket connections from the monitoring dashboard are closing after about 10 minutes.
  - Samarth said the server logs show no explicit errors when the disconnect happens.
  - Sahana suggested checking session timeout values on the load balancer and any intermediate proxies.

## Decisions
- Use current logs and metrics to separate **upstream errors** vs **gateway misconfiguration**.
- Treat the long-lived connection issue as a separate track but fix timeouts in the same change window.

## Action Items
- **Samarth**:  
  - Capture a small sample of failed 502 requests and correlate them with backend pod restarts.
- **Sahana**:  
  - Review gateway configuration for target URL and health-check path; propose corrected settings.
- **KK**:  
  - Check session and idle timeouts on the load balancer and update values to support WebSocket connections.

---

# Meeting 2 – HTTP 504 Gateway Timeout on Reporting API

**Date**: 2025-01-12  
**Attendees**: Samarth, Chiranth, Lavanya  

## Agenda
1. Understand consistent *HTTP 504 Gateway Timeout* on the reporting endpoint.
2. Identify quick mitigations and long-term fixes.

## Discussion Summary

- **Symptoms**
  - Lavanya reported that the reporting API consistently times out after ~30 seconds with *HTTP 504*.
  - Samarth confirmed that the client never receives a successful response when large reports are generated.

- **Root cause investigation**
  - Chiranth shared DB metrics showing a few slow queries taking 35–40 seconds during peak load.
  - Samarth tested the endpoint bypassing the gateway and saw responses returning slightly faster, but still close to 30 seconds.
  - The group agreed that the gateway timeout is too aggressive for the current implementation.

- **Mitigation options**
  - Short term: increase the gateway timeout for this specific route so existing reports can complete.
  - Longer term: break the reporting operation into smaller asynchronous jobs instead of a single long-running request.

## Decisions
- Raise the timeout for the reporting endpoint while keeping global defaults unchanged.
- Plan an asynchronous job-based design for heavy reports.

## Action Items
- **Chiranth**:  
  - Optimize the slowest DB queries used by the reporting endpoint and share before/after timings.
- **Lavanya**:  
  - Document the user-facing impact and update status once the timeout change is deployed.
- **Samarth**:  
  - Update gateway configuration for the reporting route to use a higher timeout value.

---

# Meeting 3 – DNS Resolution Errors & TLS Handshake Failures

**Date**: 2025-01-15  
**Attendees**: Sahana, Chiranth, KK, Lavanya  

## Agenda
1. Discuss intermittent DNS resolution failures to the analytics service.
2. Review recent TLS certificate changes causing handshake errors for some clients.

## Discussion Summary

- **DNS resolution issue**
  - Lavanya reported errors like "host not found" from one staging environment only.
  - KK confirmed that from another network segment the same hostname resolves correctly.
  - Sahana suspected inconsistent DNS server configuration between environments.

- **TLS handshake failures**
  - Chiranth noted that after rotating the TLS certificate on the edge proxy, older client libraries started failing with handshake errors.
  - KK checked and saw that the new certificate chain includes a different intermediate CA that some clients do not trust by default.
  - The team discussed validating the full certificate chain and documenting which root CAs are required.

## Decisions
- Standardize DNS servers for all staging subnets and verify that the analytics hostname has the correct A / CNAME records.
- Keep the new TLS certificate but provide guidance and updated trust chain to affected client teams.

## Action Items
- **Sahana**:  
  - Compare DNS configuration between working and failing environments and align them.
- **KK**:  
  - Validate the served certificate chain and share a short guide on required root/intermediate CAs.
- **Lavanya**:  
  - Re-test both DNS resolution and TLS connectivity after configuration changes and report results to the group.
