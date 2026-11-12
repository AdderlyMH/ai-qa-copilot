"use client";

import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../lib/api-fetch";
import { currentAccessToken, getAuthStatus } from "../lib/auth/session";
import {
  createDocumentPoller,
  type PollResult,
  type PollStopReason,
} from "../lib/document-polling";

export type DocumentStatusItem = {
  id: string;
  filename: string;
  byte_size: number;
  status: string;
  parser_stage: string | null;
  rejection_code: string | null;
  created_at: string;
};

export type PollingPhase = "polling" | "retrying" | PollStopReason;

function isDocumentStatusItem(value: unknown): value is DocumentStatusItem {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const item = value as Record<string, unknown>;
  return (
    typeof item.id === "string" &&
    typeof item.filename === "string" &&
    typeof item.byte_size === "number" &&
    typeof item.status === "string" &&
    (item.parser_stage === null || typeof item.parser_stage === "string") &&
    (item.rejection_code === null || typeof item.rejection_code === "string") &&
    typeof item.created_at === "string"
  );
}

async function fetchDocuments(
  projectId: string,
  signal: AbortSignal,
): Promise<PollResult<DocumentStatusItem>> {
  const response = await apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/documents`,
    { signal },
  );
  if (response.status === 401) {
    return { kind: "unauthorized" };
  }
  if (response.status === 429 || response.status >= 500) {
    return { kind: "retry" };
  }
  if (!response.ok) {
    return { kind: "failed" };
  }
  const body: unknown = await response.json().catch(() => undefined);
  return Array.isArray(body) && body.every(isDocumentStatusItem)
    ? { kind: "ok", documents: body }
    : { kind: "failed" };
}

function currentTime(): number {
  return Date.now();
}

function canPoll(): boolean {
  const status = getAuthStatus();
  return (
    status === "disabled" ||
    (status === "signed-in" && currentAccessToken() !== null)
  );
}

export function useDocumentPolling(projectId: string) {
  const [documents, setDocuments] = useState<DocumentStatusItem[]>([]);
  const [phase, setPhase] = useState<PollingPhase>("polling");

  const poller = useMemo(
    () =>
      createDocumentPoller<DocumentStatusItem, number>({
        fetchList: (signal) => fetchDocuments(projectId, signal),
        canPoll,
        isHidden: () => document.hidden,
        now: currentTime,
        setTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
        clearTimer: (timer) => window.clearTimeout(timer),
        onDocuments: (loaded) => {
          setDocuments(loaded);
          setPhase("polling");
        },
        onRetrying: () => setPhase("retrying"),
        onStop: setPhase,
      }),
    [projectId],
  );

  useEffect(() => {
    const onVisibilityChange = () => {
      if (!document.hidden) {
        poller.resume();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    poller.start();
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      poller.stop();
    };
  }, [poller]);

  return { documents, phase, restart: poller.start };
}
