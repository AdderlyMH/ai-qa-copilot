"use client";

import { FormEvent, useState } from "react";

import { SourcePassageViewer } from "./source-passage-viewer";
import { FindingFeedbackPanel } from "./finding-feedback-panel";

type Project = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  archived_at: string | null;
};

type AnalysisRun = {
  id: string;
  project_id: string;
  synthetic_text: string;
  output_json: Record<string, unknown>;
  provider_response_id: string;
  model_id: string;
  configuration_version: string;
  prompt_version: string;
  schema_name: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  created_at: string;
};

async function responseError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => undefined);
  if (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string"
  ) {
    const correlationId = response.headers.get("X-Correlation-ID");
    return correlationId
      ? `${body.detail} (correlation ID: ${correlationId})`
      : body.detail;
  }
  return `Request failed (${response.status})`;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [syntheticText, setSyntheticText] = useState("");
  const [analysisRuns, setAnalysisRuns] = useState<AnalysisRun[]>([]);
  const [message, setMessage] = useState(
    "Create a project or load the active project list.",
  );
  const [busy, setBusy] = useState(false);

  async function loadProjects() {
    setBusy(true);
    try {
      const response = await fetch("/api/projects");
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const loaded = (await response.json()) as Project[];
      setProjects(loaded);
      setMessage(`${loaded.length} active project(s) loaded.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to load projects.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: description || null }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const project = (await response.json()) as Project;
      setProjects((current) => [project, ...current]);
      setSelectedProject(project);
      setAnalysisRuns([]);
      setName("");
      setDescription("");
      setMessage(`Created ${project.name}.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to create project.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function viewProject(projectId: string) {
    setBusy(true);
    try {
      const response = await fetch(`/api/projects/${projectId}`);
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const project = (await response.json()) as Project;
      const runsResponse = await fetch(
        `/api/projects/${projectId}/analysis-runs`,
      );
      if (!runsResponse.ok) {
        throw new Error(await responseError(runsResponse));
      }
      const runs = (await runsResponse.json()) as AnalysisRun[];
      setSelectedProject(project);
      setAnalysisRuns(runs);
      setMessage(`Viewing ${project.name}.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to view project.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createAnalysisRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) {
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(
        `/api/projects/${selectedProject.id}/analysis-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ synthetic_text: syntheticText }),
        },
      );
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const analysisRun = (await response.json()) as AnalysisRun;
      setAnalysisRuns((current) => [analysisRun, ...current]);
      setSyntheticText("");
      setMessage(`Saved synthetic analysis for ${selectedProject.name}.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to run analysis.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function archiveProject(projectId: string) {
    setBusy(true);
    try {
      const response = await fetch(`/api/projects/${projectId}/archive`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const project = (await response.json()) as Project;
      setProjects((current) =>
        current.filter((item) => item.id !== project.id),
      );
      setSelectedProject(project);
      setMessage(`Archived ${project.name}.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to archive project.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        margin: "3rem auto",
        maxWidth: 760,
      }}
    >
      <h1>AI Quality Engineering Copilot</h1>
      <p>Project workspace - SKEL-003</p>

      <form
        onSubmit={createProject}
        style={{ display: "grid", gap: "0.75rem" }}
      >
        <label>
          Project name
          <input
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
            style={{ display: "block", width: "100%" }}
          />
        </label>
        <label>
          Description (optional)
          <textarea
            maxLength={2000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            style={{ display: "block", width: "100%" }}
          />
        </label>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button disabled={busy} type="submit">
            Create project
          </button>
          <button disabled={busy} onClick={loadProjects} type="button">
            Load projects
          </button>
        </div>
      </form>

      <p aria-live="polite">{message}</p>

      <section aria-labelledby="active-projects">
        <h2 id="active-projects">Active projects</h2>
        {projects.length === 0 ? (
          <p>No active projects loaded.</p>
        ) : (
          <ul>
            {projects.map((project) => (
              <li key={project.id} style={{ marginBottom: "0.75rem" }}>
                <strong>{project.name}</strong>{" "}
                <button
                  disabled={busy}
                  onClick={() => viewProject(project.id)}
                  type="button"
                >
                  View
                </button>{" "}
                <button
                  disabled={busy}
                  onClick={() => archiveProject(project.id)}
                  type="button"
                >
                  Archive
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selectedProject ? (
        <section aria-labelledby="project-detail">
          <h2 id="project-detail">Project detail</h2>
          <p>
            <strong>{selectedProject.name}</strong>
          </p>
          <p>{selectedProject.description || "No description."}</p>
          <p>{selectedProject.archived_at ? "Archived" : "Active"}</p>

          <SourcePassageViewer projectId={selectedProject.id} />
          <FindingFeedbackPanel projectId={selectedProject.id} />

          {selectedProject.archived_at ? null : (
            <form
              onSubmit={createAnalysisRun}
              style={{ display: "grid", gap: "0.75rem" }}
            >
              <h3>Synthetic analysis</h3>
              <label>
                Synthetic text only
                <textarea
                  required
                  maxLength={4000}
                  value={syntheticText}
                  onChange={(event) => setSyntheticText(event.target.value)}
                  style={{ display: "block", width: "100%" }}
                />
              </label>
              <button disabled={busy} type="submit">
                Run and save analysis
              </button>
            </form>
          )}

          <section aria-labelledby="analysis-runs">
            <h3 id="analysis-runs">Saved analysis runs</h3>
            {analysisRuns.length === 0 ? (
              <p>No analysis runs loaded for this project.</p>
            ) : (
              <ol>
                {analysisRuns.map((analysisRun) => (
                  <li key={analysisRun.id} style={{ marginBottom: "1rem" }}>
                    <p>{analysisRun.synthetic_text}</p>
                    <pre>
                      {JSON.stringify(analysisRun.output_json, null, 2)}
                    </pre>
                    <p>
                      {analysisRun.model_id} ·{" "}
                      {analysisRun.configuration_version} ·{" "}
                      {analysisRun.total_tokens} tokens
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </section>
      ) : null}
    </main>
  );
}
