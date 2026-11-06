// The server decides; these checks only save a pointless upload.
//
// Per-type limit for .md and .txt in _FILE_TYPES,
// apps/api/src/ai_qa_copilot_api/ingestion.py. It is lower than the server's
// MAX_RAW_UPLOAD_BYTES, so it is the limit that applies to these types.
export const MAX_TEXT_UPLOAD_BYTES = 2 * 1024 * 1024;
export const MAX_FILENAME_LENGTH = 255;

const CONTENT_TYPE_BY_EXTENSION: Readonly<Record<string, string>> = {
  ".md": "text/markdown",
  ".txt": "text/plain",
};

export const ACCEPTED_FILE_TYPES = ".md,.txt,text/markdown,text/plain";

// Printable ASCII only, because the name travels in a request header.
const ASCII_SAFE_FILENAME = /^[\x20-\x7E]+$/;

export type UploadCheck =
  { ok: true; contentType: string } | { ok: false; message: string };

export function checkUpload(filename: string, byteSize: number): UploadCheck {
  const dot = filename.lastIndexOf(".");
  const extension = dot > 0 ? filename.slice(dot).toLowerCase() : "";
  const contentType = Object.hasOwn(CONTENT_TYPE_BY_EXTENSION, extension)
    ? CONTENT_TYPE_BY_EXTENSION[extension]
    : undefined;
  if (!contentType) {
    return {
      ok: false,
      message: "Choose a Markdown (.md) or text (.txt) file.",
    };
  }
  if (byteSize > MAX_TEXT_UPLOAD_BYTES) {
    return { ok: false, message: "This file is larger than the 2 MiB limit." };
  }
  if (
    filename.length > MAX_FILENAME_LENGTH ||
    !ASCII_SAFE_FILENAME.test(filename) ||
    filename !== filename.trim() ||
    /[/\\]/.test(filename)
  ) {
    return {
      ok: false,
      message: "Rename the file using plain letters and numbers, then retry.",
    };
  }
  return { ok: true, contentType };
}

// Every code is from main.py and ingestion.py. Unknown codes fall back to the
// status, so server text never reaches the page.
const REJECTION_MESSAGES: Readonly<Record<string, string>> = {
  UPLOAD_SIZE_LIMIT: "This file is too large.",
  UPLOAD_PROJECT_SIZE_LIMIT: "This project has reached its storage limit.",
  UPLOAD_FILE_COUNT_LIMIT: "This project has reached its file limit.",
  UPLOAD_TYPE_UNSUPPORTED: "This file type is not supported.",
  UPLOAD_TYPE_MISMATCH: "This file's type does not match its extension.",
  UPLOAD_CONTENT_ENCODING_UNSUPPORTED: "This file's encoding is not supported.",
  UPLOAD_FILENAME_INVALID: "This filename is not accepted.",
  UPLOAD_CONTENT_TYPE_REQUIRED: "This file's type could not be determined.",
  UPLOAD_CONTENT_LENGTH_INVALID: "This upload could not be read.",
  UPLOAD_TEXT_ENCODING_INVALID: "This file is not valid UTF-8 text.",
  UPLOAD_SIGNATURE_MISMATCH: "This file's contents do not match its type.",
};

export function rejectionCode(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return null;
  }
  const detail = body.detail;
  if (typeof detail !== "object" || detail === null || !("code" in detail)) {
    return null;
  }
  return typeof detail.code === "string" ? detail.code : null;
}

export function uploadErrorMessage(
  status: number,
  code: string | null,
): string {
  if (code !== null && Object.hasOwn(REJECTION_MESSAGES, code)) {
    return REJECTION_MESSAGES[code];
  }
  switch (status) {
    case 400:
      return "This upload was rejected.";
    case 401:
      return "Sign in to upload.";
    case 403:
      return "You do not have access to this project.";
    case 404:
      return "This project was not found.";
    case 413:
      return "This file is too large.";
    case 415:
      return "This file type is not supported.";
    case 429:
      return "Too many requests. Try again shortly.";
    case 503:
      return "Uploads are temporarily unavailable. Try again later.";
    default:
      return "The upload failed. Try again.";
  }
}
