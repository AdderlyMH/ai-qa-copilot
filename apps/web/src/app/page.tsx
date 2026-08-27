"use client";

import { FormEvent, useState } from "react";

type Project = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  archived_at: string | null;
};

async function responseError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => undefined);
  if (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string"
  ) {
    return body.detail;
  }
  return `Request failed (${response.status})`;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
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
      setMessage(error instanceof Error ? error.message : "Unable to load projects.");
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
      setName("");
      setDescription("");
      setMessage(`Created ${project.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create project.");
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
      setSelectedProject(project);
      setMessage(`Viewing ${project.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to view project.");
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
      setProjects((current) => current.filter((item) => item.id !== project.id));
      setSelectedProject(project);
      setMessage(`Archived ${project.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to archive project.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", margin: "3rem auto", maxWidth: 760 }}>
      <h1>AI Quality Engineering Copilot</h1>
      <p>Project workspace - SKEL-003</p>

      <form onSubmit={createProject} style={{ display: "grid", gap: "0.75rem" }}>
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
          <button disabled={busy} type="submit">Create project</button>
          <button disabled={busy} onClick={loadProjects} type="button">Load projects</button>
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
                <button disabled={busy} onClick={() => viewProject(project.id)} type="button">View</button>{" "}
                <button disabled={busy} onClick={() => archiveProject(project.id)} type="button">Archive</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selectedProject ? (
        <section aria-labelledby="project-detail">
          <h2 id="project-detail">Project detail</h2>
          <p><strong>{selectedProject.name}</strong></p>
          <p>{selectedProject.description || "No description."}</p>
          <p>{selectedProject.archived_at ? "Archived" : "Active"}</p>
        </section>
      ) : null}
    </main>
  );
}
