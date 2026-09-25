import "server-only";

import { HostedApiClient } from "./api-client";
import { webConfig } from "./config";
import { CognitoOidcProvider } from "./oidc";
import { SessionService } from "./session-service";
import { PostgresSessionStore } from "./session-store";

let runtimeValue:
  | {
      sessions: SessionService;
      api: HostedApiClient;
      provider: CognitoOidcProvider;
    }
  | undefined;

export function runtime() {
  if (runtimeValue) return runtimeValue;
  const config = webConfig();
  const api = new HostedApiClient(config.apiBaseUrl, config.apiTimeoutMs);
  const provider = new CognitoOidcProvider(config);
  runtimeValue = {
    api,
    provider,
    sessions: new SessionService(
      config,
      new PostgresSessionStore(),
      provider,
      api,
    ),
  };
  return runtimeValue;
}
