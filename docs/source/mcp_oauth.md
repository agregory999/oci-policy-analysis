# MCP OAuth with OCI Identity Domains

This guide describes OAuth protection for the remote MCP server using OCI IAM
Identity Domains. OAuth is optional. With no `MCP_OAUTH_*` settings, the MCP
server continues to run without bearer-token protection. OAuth is enabled only
when `MCP_OAUTH_ENABLED=true`.

There are three different roles to keep separate:

- **Resource server**: the MCP API. It owns the audience and scopes and
  validates access tokens.
- **Authorization server**: OCI IAM Identity Domains. It authenticates users,
  issues tokens, and manages grants.
- **OAuth client**: the application or MCP client that requests a token and
  calls the MCP API.

OCI supports configuring one confidential application as both a resource
server and an OAuth client. That is a valid option for this deployment. It
does not make the MCP server the authorization server: OCI IAM remains the
authorization server.

The recommended resource-server scope values are:

- `read` — required for every MCP tool call.
- `update` — required only for the `reload` operation.

Depending on the OCI IAM application configuration, the issued token may
contain either the configured scope value or a fully qualified scope (FQS).
The MCP server must validate the value actually present in the token. In this
deployment, the issued token contains the configured values directly:

- `read` — required for every MCP tool call.
- `update` — required only for the `reload` operation.

Set `MCP_OAUTH_REQUIRED_SCOPES` and `MCP_OAUTH_UPDATE_SCOPE` to the exact
values in the JWT `scope` claim.

The token request may still require the fully qualified scope. With primary
audience `oci-policy-analysis-mcp` and configured scope value `read`, request
`oci-policy-analysis-mcpread`; OCI IAM then issues a token whose `scope` claim
is `read`.

If a different application configuration emits a fully qualified scope, use
that exact value instead.

The MCP server validates the token signature, issuer, audience, and read
scope. OAuth identifies and authorizes the caller; the MCP server still reads
OCI using its configured profile, instance principal, resource principal, or
session token.

## 1. App Creation: resource server, OAuth client, and scopes

Create one **Confidential Application** in the target OCI IAM Identity Domain.
The same application may be configured in both sections below.

### Resource-server configuration

1. Open the Identity Domain and select **Integrated applications**.
2. Select **Add application → Confidential Application → Launch workflow**.
3. Give the application a name such as `OCI Policy Analysis MCP`.
4. In OAuth configuration, enable **Configure this application as a resource
   server now**.
5. Set the **Primary audience** to a stable value such as
   `oci-policy-analysis-mcp`. This becomes `MCP_OAUTH_AUDIENCE`; it is not
   necessarily the client ID.
6. Add these scopes:

   ```text
   read
   update
   ```

The resource-server application defines what access to MCP means. A client
must later be granted these scopes before OCI IAM will issue a token that
contains them.

### Granting access to a group of users

For Authorization Code access, assign the permitted Identity Domain group to
the OAuth client application. Users in that group can then authenticate
through the application and receive its allowed resource scope. The MCP
server validates the resulting token; it does not query Identity Domain group
membership during each request.

If the server must enforce a group independently of application assignment,
configure an OCI IAM custom token claim containing group membership and add
application-level authorization for that claim. Scope validation alone does
not distinguish one user group from another.

### Client configuration

If this same application will request tokens, also enable **Configure this
application as a client now** and select only the grant types needed by the
deployment:

- **Client Credentials** for a public/service-to-service integration.
- **Authorization Code** for a browser-based three-legged integration.
- **Refresh Token** if long-lived user sessions need token renewal.
- **Resource Owner** only for a tightly trusted integration that explicitly
  collects the user’s credentials. Authorization Code is preferred for
  interactive users because user credentials are not exposed to the client.

For a separate caller application, configure that application as a client and
grant it the MCP resource scopes instead. The resource-server app and caller
app do not have to be the same application.

For Authorization Code, register the caller’s exact HTTPS redirect URL in the
client application. The redirect URL belongs to the OAuth client handling the
browser flow, not to the MCP bearer-token validation endpoint.

Activate the application after saving the configuration. Record:

- Identity Domain issuer URL, matching the token `iss` claim exactly.
- Signing certificate JWKS URL, normally ending in
  `/admin/v1/SigningCert/jwk`.
- Resource-server primary audience.
- Authorization server URL.
- Client ID and client secret, if the application is configured as a
  confidential client.
- The two resource scopes.

See Oracle’s [Register the Application in OCI IAM](https://docs.oracle.com/en/database/oracle/oracle-database/26/ddscg/register-application-oci-iam.html)
and [Configuring OAuth](https://docs.oracle.com/en-us/iaas/Content/Identity/applications/to-configure-oauth.htm)
documentation.

### Start the MCP server

Set the OAuth resource-server settings on the container instance and start or
restart the existing MCP container:

```bash
export MCP_OAUTH_ENABLED="true"
export MCP_OAUTH_ISSUER="https://idcs-<id>.identity.oraclecloud.com/"
export MCP_OAUTH_JWKS_URI="https://idcs-<id>.identity.oraclecloud.com/admin/v1/SigningCert/jwk"
export MCP_OAUTH_AUDIENCE="oci-policy-analysis-mcp"
export MCP_OAUTH_REQUIRED_SCOPES="read"
export MCP_OAUTH_UPDATE_SCOPE="update"
export MCP_OAUTH_RESOURCE_SERVER_URL="https://<mcp-public-host>/mcp"
export MCP_OAUTH_AUTHORIZATION_SERVER_URL="https://idcs-<id>.identity.oraclecloud.com/"
export MCP_OAUTH_ALGORITHM="RS256"
```

The deployment script or container entrypoint then starts the server with the
configured transport, host, port, and OCI authentication mode. If
`MCP_OAUTH_ENABLED=true` and a required value is missing, startup fails before
loading tenancy data and prints a setup error.

`MCP_OAUTH_REQUIRED_SCOPES` is space- or comma-separated and applies to every
MCP tool. `MCP_OAUTH_UPDATE_SCOPE` is checked separately for `reload`.

## 2. Connecting with a Bearer Token

The MCP server is a protected resource. A caller presents an access token in
the HTTP request:

```bash
curl -i \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}' \
  https://<mcp-public-host>/mcp
```

The JWT should contain:

- `iss` equal to `MCP_OAUTH_ISSUER`.
- `aud` containing `MCP_OAUTH_AUDIENCE`.
- `scope` containing `read`.
- `update` only for callers allowed to reload.

Expected behavior:

- No bearer token: MCP access is rejected.
- Read scope: normal search and analysis tools work.
- Read without update scope: `reload` is rejected.
- Read plus update scope: `reload` is authorized, subject to the server’s OCI
  authentication mode and loaded-data requirements.

### Start the MCP server

Use the same environment block from **App Creation**, then restart the
container. No callback is required for this bearer-token connection: the
caller obtains the token, and the MCP server only validates it.

## 3. Two-legged service integration: Client Credentials

Client Credentials is the two-legged machine-to-machine flow. In this section,
“public” means an externally reachable service integration; it does not mean
an OAuth **public client**. Client Credentials requires the client to protect
its credentials. There is no
resource owner signing in through a browser and no callback. The OAuth client
authenticates to OCI IAM with its client ID and secret and requests the MCP
resource scope.

If using the same app as both resource server and client, grant that app its
own MCP scopes under its client **Resources** configuration. A separate client
application can be granted the same scopes instead.

Example token request:

```bash
export BASIC_AUTH="$(printf '%s:%s' "$CLIENT_ID" "$CLIENT_SECRET" | base64)"

curl -sS \
  -H "Authorization: Basic $BASIC_AUTH" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&scope=oci-policy-analysis-mcpread" \
  "https://idcs-<id>.identity.oraclecloud.com/oauth2/v1/token"
```

Request `oci-policy-analysis-mcpupdate` only for a service that is authorized
to invoke `reload`. Use the returned `access_token` as `$ACCESS_TOKEN` in the
Bearer Token example. The resulting JWT scope is still validated as `update`.

### Start the MCP server

Start the MCP server with the resource-server environment block from **App
Creation**. The server does not need the client ID or client secret; those
remain with the calling service. The server validates the resulting JWT
against the issuer, JWKS endpoint, audience, and scopes.

See Oracle’s [Client Credentials Grant Type](https://docs.oracle.com/en-us/iaas/Content/Identity/api-getstarted/ClientCredGT.htm)
documentation.

## 4. Three-legged integration: Authorization Code and callback

Authorization Code is the three-legged flow: OAuth client, resource owner, and
OCI IAM. The user authenticates at OCI IAM, grants access, and OCI IAM redirects
the browser back to the OAuth client with an authorization code. The client
exchanges that code for an access token and then calls MCP with the bearer
token.

The callback must be implemented by the component acting as the OAuth client.
It does not need to be implemented by the MCP resource server when an external
MCP client or gateway owns the login flow. In that common arrangement:

1. Register the external client’s exact HTTPS callback URL in OCI IAM.
2. The client redirects the browser to the Identity Domain authorization
   endpoint with `client_id`, `redirect_uri`, `response_type=code`, `scope`,
   `state`, and a PKCE challenge where supported.
3. OCI IAM redirects back to the client callback with `code` and `state`.
4. The client validates `state` and exchanges the code at the token endpoint.
5. The client sends the access token to MCP using the Bearer Token example.

If the MCP server itself is intended to be that OAuth client, then the server
needs additional application behavior that it does not currently provide:

- a login endpoint that creates and stores state and PKCE values;
- a registered callback route;
- code-to-token exchange with OCI IAM;
- secure storage and refresh of the resulting token; and
- a way to associate the authenticated user/token with MCP sessions.

`RemoteAuthProvider` currently configures MCP as a protected resource and
advertises the authorization server; it does not implement that client-side
callback flow. The simplest three-legged design is therefore to let the MCP
client or an OAuth gateway handle the callback and pass the resulting bearer
token to this server.

### Manual three-legged smoke test

For a temporary test, you can perform the browser step manually without a
callback server. Register a redirect URI that you can use for testing, such as
`http://127.0.0.1:8765/oauth/callback`. After login, the browser may show a
connection error because no callback route exists; copy the `code` and `state`
from the resulting URL.

Set the client and redirect values:

```bash
export IDCS_BASE_URL="https://idcs-<id>.identity.oraclecloud.com"
export IDCS_CLIENT_ID="<authorization-code-client-id>"
export IDCS_CLIENT_SECRET="<authorization-code-client-secret>"
export REDIRECT_URI="http://127.0.0.1:8765/oauth/callback"
```

Generate the authorization URL. The token request below uses the fully
qualified OCI scope `oci-policy-analysis-mcpread`; the issued JWT is expected
to contain `scope=read`.

```bash
python - <<'PY'
import os
import secrets
import urllib.parse

params = {
    "client_id": os.environ["IDCS_CLIENT_ID"],
    "response_type": "code",
    "redirect_uri": os.environ["REDIRECT_URI"],
    "scope": "oci-policy-analysis-mcpread",
    "state": secrets.token_urlsafe(24),
}
print(os.environ["IDCS_BASE_URL"] + "/oauth2/v1/authorize?" + urllib.parse.urlencode(params))
PY
```

Open the printed URL in a browser, sign in as an allowed user, and copy the
`code` and `state` query parameters from the redirect URL. Verify the returned
state matches the state printed in the authorization URL, then exchange the
one-time code:

```bash
read -r AUTH_CODE

export ACCESS_TOKEN="$(curl -sS \
  -u "$IDCS_CLIENT_ID:$IDCS_CLIENT_SECRET" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=$AUTH_CODE" \
  --data-urlencode "redirect_uri=$REDIRECT_URI" \
  "$IDCS_BASE_URL/oauth2/v1/token" | jq -r '.access_token')"
```

Initialize the MCP session and save its session ID:

```bash
export MCP_URL="http://127.0.0.1:8765/mcp"

curl -sS \
  -D /tmp/mcp-init.headers \
  -o /tmp/mcp-init.body \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}' \
  "$MCP_URL"

cat /tmp/mcp-init.body
export MCP_SESSION_ID="$(awk 'tolower($1)=="mcp-session-id:" {print $2}' /tmp/mcp-init.headers | tr -d '\r')"
```

Complete the MCP handshake:

```bash
curl -sS \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Mcp-Session-Id: $MCP_SESSION_ID" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  "$MCP_URL"
```

Invoke an MCP tool:

```bash
curl -i \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Mcp-Session-Id: $MCP_SESSION_ID" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"policy_search","arguments":{}}}' \
  "$MCP_URL"
```

At `MCP_LOG_LEVEL=WARNING`, the server should log the authenticated user
identity and scopes for the tool invocation. This manual flow is for testing;
production use should keep `state`, authorization codes, client secrets, and
access tokens inside a real callback/session service.

### Start the MCP server

Start the MCP server with the same resource-server environment block. If an
external client owns the callback, no additional MCP callback setting is
needed. If MCP is later expanded to own the callback, the callback URL must be
added to the client configuration and exposed through the MCP deployment’s
HTTPS ingress.

See Oracle’s [Authorization Code Grant Type](https://docs.oracle.com/en-us/iaas/Content/Identity/api-getstarted/AuthCodeGT.htm)
documentation.

## Diagnostics and troubleshooting

At `MCP_LOG_LEVEL=WARNING`, each MCP tool invocation logs the caller and granted
scopes without logging the bearer token or client secret:

```text
MCP OAuth invoke policy_search client_id=<caller> user_displayname=<user> ca_name=<account> scopes=<granted-scopes>
```

OCI IAM commonly supplies the human-readable fields as `user_displayname` and
`ca_name`; the fallback `client_id` is usually the token subject (`sub`). These
identity fields are useful for audit diagnostics but are still user data. Keep
the warning logs access-controlled and avoid enabling request-input logging at
`INFO` in production unless policy text and request filters are acceptable to
store in logs.

Common failures:

- **`iss` mismatch**: copy the exact `iss` value from the JWT into
  `MCP_OAUTH_ISSUER`.
- **`aud` mismatch**: use the resource server’s primary audience, not the
  client ID unless they are intentionally identical.
- **Missing scope**: grant the client access to the MCP resource scope and
  request the fully qualified scope from the token endpoint. Configure
  `MCP_OAUTH_REQUIRED_SCOPES` and `MCP_OAUTH_UPDATE_SCOPE` with the exact value
  present in the JWT `scope` claim.
- **JWKS failure**: verify that the JWKS endpoint is reachable anonymously by
  the container.
- **Reload denied**: ensure the token contains the configured
  `MCP_OAUTH_UPDATE_SCOPE` value.
- **Callback mismatch**: ensure the `redirect_uri` exactly matches the URL
  registered on the OAuth client, including scheme, host, path, and port.
