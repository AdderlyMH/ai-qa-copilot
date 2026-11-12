"use client";

import { DocumentStatusPanel } from "./document-status-panel";
import { UploadPanel } from "./upload-panel";
import { useDocumentPolling } from "./use-document-polling";

export function DocumentIntakeSection({ projectId }: { projectId: string }) {
  const { documents, phase, restart } = useDocumentPolling(projectId);

  return (
    <>
      <UploadPanel projectId={projectId} onUploaded={restart} />
      <DocumentStatusPanel documents={documents} phase={phase} />
    </>
  );
}
