export type ApiFailureKind =
  | "timeout"
  | "network"
  | "http"
  | "empty_body"
  | "invalid_json"
  | "malformed_response";

export class ApiFailure extends Error {
  constructor(
    message: string,
    public readonly kind: ApiFailureKind,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiFailure";
  }

  get isRetryable(): boolean {
    return (
      this.kind === "timeout" ||
      this.kind === "network" ||
      (this.kind === "http" && this.status !== undefined && this.status >= 500)
    );
  }
}
