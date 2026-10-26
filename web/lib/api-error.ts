/** Keep HTTP failures distinguishable from a service that is still starting. */
export class ApiError extends Error {
  constructor(message: string, public readonly status?: number, public readonly code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function responseError(res: Response, fallback: string): Promise<ApiError> {
  const body = await res.json().catch(() => ({}));
  return new ApiError(typeof body?.detail === "string" ? body.detail : fallback, res.status,
    typeof body?.code === "string" ? body.code : undefined);
}
