"use client";

import { FormEvent, useState } from "react";

import { apiFetch } from "../lib/api-fetch";
import {
  ACCEPTED_FILE_TYPES,
  checkUpload,
  rejectionCode,
  uploadErrorMessage,
} from "../lib/upload-policy";

export function UploadPanel({
  projectId,
  onUploaded,
}: {
  projectId: string;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setMessage("Choose a file first.");
      return;
    }
    const check = checkUpload(file.name, file.size);
    if (!check.ok) {
      setMessage(check.message);
      return;
    }

    setBusy(true);
    try {
      const response = await apiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/documents`,
        {
          method: "POST",
          headers: {
            "Content-Type": check.contentType,
            "X-Upload-Filename": file.name,
          },
          body: file,
        },
      );
      if (response.status === 202) {
        setMessage("Upload accepted. Checking its status.");
        setFile(null);
        setInputKey((key) => key + 1);
        onUploaded();
        return;
      }
      const body: unknown = await response.json().catch(() => undefined);
      const code = rejectionCode(body);
      setMessage(uploadErrorMessage(response.status, code));
      // The server records a rejected upload, so the list has a new row.
      if (code !== null) {
        onUploaded();
      }
    } catch {
      setMessage("The upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="upload-document">
      <h3 id="upload-document">Upload a document</h3>
      <form onSubmit={upload} style={{ display: "grid", gap: "0.75rem" }}>
        <label>
          Markdown or text file
          <input
            key={inputKey}
            accept={ACCEPTED_FILE_TYPES}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setMessage("");
            }}
            style={{ display: "block" }}
            type="file"
          />
        </label>
        <button disabled={busy} type="submit">
          Upload
        </button>
      </form>
      <p aria-live="polite">{message}</p>
    </section>
  );
}
