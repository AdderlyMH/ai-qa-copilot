// Timing and browser access are injected so this logic can run under fake timers.

export const POLL_INTERVAL_MS = 3_000;
export const POLL_MAX_BACKOFF_MS = 30_000;
export const POLL_CAP_MS = 180_000;

// DocumentStatus in apps/api/src/ai_qa_copilot_api/document_status.py.
export const NON_TERMINAL_STATUSES: readonly string[] = [
  "quarantined",
  "parser_queued",
  "parsing",
];
export const TERMINAL_STATUSES: readonly string[] = [
  "rejected",
  "parsed",
  "parse_failed",
];

export type PollResult<T extends { status: string }> =
  | { kind: "ok"; documents: T[] }
  // 429, 5xx and network errors: worth retrying, more slowly.
  | { kind: "retry" }
  | { kind: "unauthorized" }
  // Any other status: a retry would not change the answer.
  | { kind: "failed" };

export type PollStopReason =
  "settled" | "capped" | "unauthorized" | "signed-out" | "failed";

export type PollerDeps<T extends { status: string }, Timer> = {
  fetchList: (signal: AbortSignal) => Promise<PollResult<T>>;
  canPoll: () => boolean;
  isHidden: () => boolean;
  now: () => number;
  setTimer: (callback: () => void, delayMs: number) => Timer;
  clearTimer: (timer: Timer) => void;
  onDocuments: (documents: T[]) => void;
  onRetrying: () => void;
  onStop: (reason: PollStopReason) => void;
};

export type Poller = {
  // Polls now, restarts the cap, and never overlaps a request in flight.
  start: () => void;
  // Call when the page becomes visible again.
  resume: () => void;
  // Ends polling silently: clears the timer and aborts a request in flight.
  stop: () => void;
};

export function createDocumentPoller<T extends { status: string }, Timer>(
  deps: PollerDeps<T, Timer>,
): Poller {
  let running = false;
  let parked = false;
  let rerun = false;
  let inFlight: AbortController | null = null;
  let timer: { handle: Timer } | null = null;
  let delayMs = POLL_INTERVAL_MS;
  let deadline = 0;

  function clearScheduled(): void {
    if (timer) {
      deps.clearTimer(timer.handle);
      timer = null;
    }
    parked = false;
  }

  function finish(reason: PollStopReason): void {
    running = false;
    rerun = false;
    clearScheduled();
    deps.onStop(reason);
  }

  function schedule(waitMs: number): void {
    const untilCap = Math.max(deadline - deps.now(), 0);
    timer = {
      handle: deps.setTimer(
        () => {
          timer = null;
          void tick();
        },
        Math.min(waitMs, untilCap),
      ),
    };
  }

  async function tick(): Promise<void> {
    if (!running) {
      return;
    }
    if (inFlight) {
      rerun = true;
      return;
    }
    if (!deps.canPoll()) {
      finish("signed-out");
      return;
    }
    if (deps.now() >= deadline) {
      finish("capped");
      return;
    }
    if (deps.isHidden()) {
      parked = true;
      return;
    }

    const controller = new AbortController();
    inFlight = controller;
    let result: PollResult<T>;
    try {
      result = await deps.fetchList(controller.signal);
    } catch {
      result = { kind: "retry" };
    }
    if (controller.signal.aborted) {
      return;
    }
    inFlight = null;
    handle(result);
  }

  function handle(result: PollResult<T>): void {
    if (result.kind === "unauthorized" || result.kind === "failed") {
      finish(result.kind);
      return;
    }
    if (result.kind === "retry") {
      rerun = false;
      delayMs = Math.min(delayMs * 2, POLL_MAX_BACKOFF_MS);
      deps.onRetrying();
      schedule(delayMs);
      return;
    }

    delayMs = POLL_INTERVAL_MS;
    deps.onDocuments(result.documents);
    if (rerun) {
      rerun = false;
      void tick();
    } else if (
      result.documents.some((document) =>
        NON_TERMINAL_STATUSES.includes(document.status),
      )
    ) {
      schedule(POLL_INTERVAL_MS);
    } else {
      finish("settled");
    }
  }

  return {
    start() {
      running = true;
      delayMs = POLL_INTERVAL_MS;
      deadline = deps.now() + POLL_CAP_MS;
      clearScheduled();
      void tick();
    },
    resume() {
      if (running && parked) {
        parked = false;
        void tick();
      }
    },
    stop() {
      running = false;
      rerun = false;
      clearScheduled();
      inFlight?.abort();
      inFlight = null;
    },
  };
}
