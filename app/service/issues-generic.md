# Global Issues Knowledge Base – Generic Network & HTTP (Synthetic)

---

## Issue 1 — Intermittent HTTP 502 Bad Gateway

**Summary**  
Clients sometimes receive *HTTP 502 Bad Gateway* when calling an application endpoint through an API gateway or reverse proxy.

**How it appears**  
- Some requests succeed, some fail with 502
- Error visible in browser / client logs
- Gateway / proxy logs show upstream errors

**Possible causes**  
- Upstream service is overloaded, timing out, or restarting
- Health checks misconfigured; traffic sent to unhealthy instances
- Wrong upstream URL or port configured in gateway / proxy

**Recommended steps**  
- Check upstream service health (CPU, memory, restart count, error logs)
- Review gateway / proxy configuration for target URL, port, and health-check path
- Compare latency and error rates before and after recent changes or deployments

**Tags**  
`http-502`, `gateway`, `upstream`, `reverse-proxy`, `availability`

---

## Issue 2 — Consistent HTTP 504 Gateway Timeout

**Summary**  
Clients consistently receive *HTTP 504 Gateway Timeout* for a specific API or operation.

**How it appears**  
- Requests fail after a fixed timeout (for example, 30 seconds)
- Backend logs may show long-running operations or no request received at all
- Monitoring tools show spikes in latency for the affected endpoint

**Possible causes**  
- Backend operation takes longer than the configured timeout on gateway or load balancer
- Slow database queries or external API calls
- Excessive retries or cascading calls between internal services

**Recommended steps**  
- Measure actual end-to-end response time for the operation
- Optimize slow queries or external calls used by the endpoint
- Adjust timeout values on gateway / load balancer to match realistic service behavior
- Consider breaking very long operations into smaller asynchronous tasks

**Tags**  
`http-504`, `timeouts`, `latency`, `load-balancer`, `backend-performance`

---

## Issue 3 — Unexpected HTTP 401 Unauthorized

**Summary**  
Previously working API calls start returning *HTTP 401 Unauthorized* without intentional changes to credentials.

**How it appears**  
- 401 errors from protected endpoints
- Authentication or token validation errors in server logs
- Some clients still work, others fail

**Possible causes**  
- Expired or revoked access tokens or API keys
- Authorization headers missing, malformed, or overwritten by an intermediate proxy
- Clock skew between token issuer and verifier causing validation failures

**Recommended steps**  
- Confirm tokens or API keys are valid and not expired or revoked
- Capture and compare HTTP requests from working vs failing clients
- Ensure intermediate components (gateways, proxies) do not strip or rewrite auth headers
- Verify server clock and token validation logic (issuer, audience, signature)

**Tags**  
`http-401`, `authentication`, `authorization`, `tokens`, `api-security`

---

## Issue 4 — DNS Resolution Errors for Service Endpoints

**Summary**  
Applications intermittently fail to resolve hostnames for internal or external services.

**How it appears**  
- Errors like "host not found", "name or service not known", or DNS lookup failures
- Works when tested from some hosts or networks, fails from others
- Issues often appear after environment or network changes

**Possible causes**  
- Inconsistent DNS server configuration across subnets or environments
- Missing or outdated DNS records for service hostnames
- Short TTL values combined with caching and propagation delays

**Recommended steps**  
- Run DNS lookups from both working and failing environments and compare results
- Verify correct DNS records (A / CNAME) exist for the affected hostnames
- Confirm all relevant clients use the intended DNS servers
- Review recent changes to network, VPN, or DNS infrastructure

**Tags**  
`dns`, `name-resolution`, `infrastructure`, `networking`

---

## Issue 5 — TLS Handshake Failures After Certificate Changes

**Summary**  
Clients fail to establish secure connections after certificates or TLS settings were updated on a server, gateway, or proxy.

**How it appears**  
- Errors such as "TLS handshake failed", "certificate verify failed", or similar
- Some client platforms work while others fail
- Monitoring shows increases in connection failures or error rates

**Possible causes**  
- Clients do not trust the new certificate chain (missing root or intermediate CA)
- Hostname in the certificate does not match the requested server name
- TLS versions or cipher suites incompatible between client and server

**Recommended steps**  
- Inspect the served certificate chain using standard TLS inspection tools
- Verify the certificate subject / SAN contains the expected hostname
- Confirm client trust stores contain the required root and intermediate CAs
- Review TLS configuration for allowed versions and cipher suites

**Tags**  
`tls`, `ssl`, `certificates`, `security`, `connectivity`

---

## Issue 6 — Long-Lived Connections Being Dropped

**Summary**  
Long-lived connections (such as streaming APIs or WebSockets) close unexpectedly after some time, causing client errors or reconnect loops.

**How it appears**  
- Clients observe disconnects after a predictable duration
- Application logs may not show clear errors on the server side
- Network or proxy logs show sessions being closed by policy or timeout

**Possible causes**  
- Idle or absolute session timeouts enforced by load balancers, proxies, or firewalls
- Health checks or policy rules not tuned for long-lived connections
- Network interruptions on one side of the connection

**Recommended steps**  
- Identify expected lifetime and activity pattern of the connection type
- Review session timeout and idle timeout settings on intermediate components
- Ensure health checks and policies support persistent or streaming traffic
- Implement graceful reconnection logic on the client side if appropriate

**Tags**  
`timeouts`, `sessions`, `websocket`, `streaming`, `reliability`
