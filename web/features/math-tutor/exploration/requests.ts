export type ExplorationRequest = Readonly<{ controller: AbortController; signal: AbortSignal }>;

export class ExplorationRequests {
  private current: ExplorationRequest | null = null;

  get busy(): boolean { return this.current !== null; }

  begin(): ExplorationRequest {
    this.cancel();
    const controller = new AbortController();
    const request = Object.freeze({ controller, signal: controller.signal });
    this.current = request;
    return request;
  }

  accepts(request: ExplorationRequest): boolean {
    return this.current === request && !request.signal.aborted;
  }

  finish(request: ExplorationRequest): void {
    if (this.current === request) this.current = null;
  }

  cancel(): void {
    this.current?.controller.abort();
    this.current = null;
  }
}
