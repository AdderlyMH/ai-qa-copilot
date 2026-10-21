// Guest demo viewer (ADR-019 Decisions 3, 5, 6 and 11).
//
// Fetches snapshot.json from its own directory, checks its SHA-256 against the
// directory name, and only then renders it. Every string from the snapshot is
// untrusted: it is written with textContent into elements this script creates,
// never parsed as markup. On any failure the page shows an error and renders
// nothing from the data.
"use strict";

(function (global) {
  const SNAPSHOT_FILE = "snapshot.json";
  const SNAPSHOT_SCHEMA = "guest-demo-snapshot/v1";
  const CONTENT_CLASS = "demo-content-not-evaluation-evidence";
  const HASH_PATTERN = /^[0-9a-f]{64}$/;

  const PROVENANCE_ROWS = [
    ["statement", "Statement"],
    ["findings", "Findings"],
    ["analyzer_version", "Analyzer version"],
    ["citations", "Citations"],
    ["test_proposals", "Test proposals"],
    ["test_generator_version", "Test generator version"],
    ["execution", "Execution"],
    ["failure_analysis", "Failure analysis"],
    ["publication", "Publication"],
  ];
  const SUMMARY_ROWS = [
    ["source_document_version_count", "Source documents"],
    ["requirement_analysis_run_count", "Analysis runs"],
    ["finding_count", "Findings"],
    ["generated_test_case_count", "Test proposals"],
    ["execution_count", "Test executions"],
    ["succeeded_execution_count", "Executions that passed"],
    ["failed_execution_count", "Executions that failed"],
    ["cancelled_execution_count", "Executions cancelled"],
    ["failure_analysis_count", "Failure analyses"],
  ];
  const SECTION_LABELS = {
    scope: "Scope",
    source_inventory: "Source inventory",
    findings: "Findings",
    generated_tests: "Generated tests",
    reviewed_tests: "Reviewed tests",
    traceability: "Traceability",
    execution_evidence: "Execution evidence",
    failure_analysis: "Failure analysis",
    metrics: "Metrics",
    provenance: "Provenance",
    limitations: "Limitations",
  };

  // Badge classes come from these fixed tables, never from the data itself.
  const SEVERITY_BADGES = {
    critical: "badge badge-high",
    high: "badge badge-high",
    medium: "badge badge-medium",
    low: "badge badge-low",
    info: "badge badge-low",
  };
  const STATE_BADGES = {
    complete: "badge badge-ok",
    failed: "badge badge-high",
    not_run: "badge badge-neutral",
    not_available: "badge badge-neutral",
    not_applicable: "badge badge-neutral",
    unsupported: "badge badge-neutral",
  };
  const THEMES = { light: "Switch to dark theme", dark: "Switch to light theme" };

  class ViewerError extends Error {}

  // The expected hash is the name of the directory the page is served from.
  function expectedHashFromPath(pathname) {
    if (typeof pathname !== "string") {
      return null;
    }
    if (!pathname.endsWith("/") && !pathname.endsWith("/index.html")) {
      return null;
    }
    const parts = pathname.split("/").filter((part) => part.length > 0);
    if (parts.length > 0 && parts[parts.length - 1] === "index.html") {
      parts.pop();
    }
    const name = parts.length > 0 ? parts[parts.length - 1] : "";
    return HASH_PATTERN.test(name) ? name : null;
  }

  async function sha256Hex(cryptoApi, bytes) {
    const digest = await cryptoApi.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
  }

  function text(value) {
    if (typeof value === "string") {
      return value;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
    throw new ViewerError("The report file has an unexpected value.");
  }

  function list(value) {
    if (!Array.isArray(value)) {
      throw new ViewerError("The report file has an unexpected shape.");
    }
    return value;
  }

  function object(value) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw new ViewerError("The report file has an unexpected shape.");
    }
    return value;
  }

  // A known value gets its fixed badge class; anything else is plain text.
  function badge(label, classes, key) {
    const lookup = key === undefined ? label : key;
    return Object.prototype.hasOwnProperty.call(classes, lookup)
      ? { text: label, className: classes[lookup] }
      : label;
  }

  function make(doc, tag, content, className) {
    const element = doc.createElement(tag);
    if (content !== undefined && content !== null) {
      element.textContent = content;
    }
    if (className) {
      element.className = className;
    }
    return element;
  }

  function heading(doc, level, content, id) {
    const element = make(doc, `h${level}`, content);
    if (id) {
      element.id = id;
    }
    return element;
  }

  function section(doc, title, id) {
    const element = make(doc, "section");
    element.setAttribute("aria-labelledby", id);
    element.appendChild(heading(doc, 2, title, id));
    return element;
  }

  function table(doc, caption, headers, rows) {
    const wrapper = make(doc, "div", null, "table-wrap");
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", caption);
    wrapper.setAttribute("tabindex", "0");
    const element = make(doc, "table");
    element.appendChild(make(doc, "caption", caption));
    const head = make(doc, "thead");
    const headRow = make(doc, "tr");
    for (const header of headers) {
      const cell = make(doc, "th", header);
      cell.setAttribute("scope", "col");
      headRow.appendChild(cell);
    }
    head.appendChild(headRow);
    element.appendChild(head);
    const body = make(doc, "tbody");
    for (const row of rows) {
      const tableRow = make(doc, "tr");
      row.forEach((value, index) => {
        const cell = make(doc, index === 0 ? "th" : "td");
        if (value !== null && typeof value === "object") {
          // A badge: the visible text is the data, the class is a fixed one.
          cell.appendChild(make(doc, "span", value.text, value.className));
        } else {
          cell.textContent = value;
        }
        if (index === 0) {
          cell.setAttribute("scope", "row");
        }
        tableRow.appendChild(cell);
      });
      body.appendChild(tableRow);
    }
    element.appendChild(body);
    wrapper.appendChild(element);
    return wrapper;
  }

  function validate(snapshot) {
    object(snapshot);
    if (snapshot.schema_version !== SNAPSHOT_SCHEMA) {
      throw new ViewerError("The report file has an unsupported version.");
    }
    if (snapshot.content_class !== CONTENT_CLASS) {
      throw new ViewerError("The report file is not marked as demo content.");
    }
    if (object(snapshot.provenance).not_a_model_result !== true) {
      throw new ViewerError("The report file lacks its provenance statement.");
    }
  }

  function buildReport(doc, snapshot, contentHash) {
    const provenance = object(snapshot.provenance);
    const summary = object(snapshot.summary);
    const sections = list(snapshot.sections).map(object);
    const traceability = object(snapshot.traceability);
    const excerpts = list(snapshot.excerpts)
      .map(object)
      .slice()
      .sort((a, b) => a.line_start - b.line_start);

    const excerptOrder = new Map();
    excerpts.forEach((excerpt, index) => {
      excerptOrder.set(text(excerpt.public_id), index);
    });
    const findingSection = sections.find((item) => item.name === "findings");
    const findingStatement = new Map();
    for (const claim of list(findingSection ? findingSection.claims : [])) {
      findingStatement.set(text(claim.public_id), text(claim.statement));
    }
    const rows = list(traceability.rows).map((row) => {
      const cited = list(row.citation_excerpts)
        .map((id) => excerptOrder.get(text(id)))
        .filter((index) => index !== undefined)
        .sort((a, b) => a - b);
      return {
        statement: findingStatement.get(text(row.finding)) || "",
        excerpts: cited,
        tests: list(row.test_proposals).length,
      };
    });
    rows.sort(
      (a, b) =>
        (a.excerpts[0] ?? Infinity) - (b.excerpts[0] ?? Infinity) ||
        a.statement.localeCompare(b.statement),
    );

    const report = doc.createDocumentFragment();
    const requirementLabel = (index) =>
      `Requirement ${index + 1} (line ${text(excerpts[index].line_start)})`;

    // How this was produced (Decision 11), verbatim from the data.
    const produced = section(doc, "How this was produced", "produced-heading");
    produced.appendChild(
      make(doc, "p", text(provenance.statement), "statement"),
    );
    produced.appendChild(
      table(
        doc,
        "Provenance of this report",
        ["Part", "How it was produced"],
        PROVENANCE_ROWS.map(([key, label]) => [label, text(provenance[key])]),
      ),
    );
    report.appendChild(produced);

    const integrity = section(doc, "Report file check", "integrity-heading");
    integrity.appendChild(
      make(
        doc,
        "p",
        "Your browser computed the SHA-256 of the report file and it matches the name of this page's directory, so the file is the one that was published.",
      ),
    );
    integrity.appendChild(make(doc, "p", contentHash, "hash"));
    report.appendChild(integrity);

    const counts = section(doc, "Summary", "summary-heading");
    counts.appendChild(
      table(
        doc,
        "Counts in this report",
        ["Item", "Count"],
        SUMMARY_ROWS.map(([key, label]) => [label, text(summary[key])]),
      ),
    );
    counts.appendChild(
      table(
        doc,
        "Findings by severity and category",
        ["Severity", "Category", "Count"],
        list(summary.finding_counts)
          .map(object)
          .map((item) => [
            badge(text(item.severity), SEVERITY_BADGES),
            text(item.category),
            text(item.count),
          ]),
      ),
    );
    report.appendChild(counts);

    const byRequirement = section(
      doc,
      "Findings by requirement",
      "requirements-heading",
    );
    byRequirement.appendChild(
      make(
        doc,
        "p",
        "Each requirement as published (redacted where needed), followed by the findings that cite it.",
      ),
    );
    excerpts.forEach((excerpt, index) => {
      const article = make(doc, "article", null, "requirement");
      article.appendChild(heading(doc, 3, requirementLabel(index)));
      article.appendChild(make(doc, "blockquote", text(excerpt.text)));
      const cited = rows.filter((row) => row.excerpts.includes(index));
      if (cited.length === 0) {
        article.appendChild(
          make(doc, "p", "No finding was recorded for this requirement.", "muted"),
        );
      } else {
        const items = make(doc, "ul");
        for (const row of cited) {
          const others = row.excerpts
            .filter((other) => other !== index)
            .map((other) => `line ${text(excerpts[other].line_start)}`);
          const suffix = others.length ? ` Also cites ${others.join(", ")}.` : "";
          items.appendChild(make(doc, "li", `${row.statement}${suffix}`));
        }
        article.appendChild(items);
      }
      byRequirement.appendChild(article);
    });
    report.appendChild(byRequirement);

    const derived = section(doc, "Traceability (derived)", "traceability-heading");
    derived.appendChild(make(doc, "p", text(traceability.label)));
    derived.appendChild(
      make(doc, "p", text(traceability.report_section_note), "muted"),
    );
    derived.appendChild(
      table(
        doc,
        "Findings, the requirements they cite and the test proposals linked to them (derived)",
        ["Finding", "Requirements", "Test proposals"],
        rows.map((row) => [
          row.statement,
          row.excerpts
            .map((index) => `${index + 1} (line ${text(excerpts[index].line_start)})`)
            .join(", "),
          String(row.tests),
        ]),
      ),
    );
    report.appendChild(derived);

    const sectionStates = section(doc, "Report sections", "sections-heading");
    sectionStates.appendChild(
      table(
        doc,
        "State of each report section",
        ["Section", "State", "Notes"],
        sections.map((item) => {
          const name = text(item.name);
          const claims = list(item.claims).map(object);
          let note = item.state_reason === null ? "" : text(item.state_reason);
          if (!note && (name === "findings" || name === "generated_tests")) {
            note = `${claims.length} entries, shown above.`;
          } else if (!note && claims.length > 0) {
            const seen = new Map();
            for (const claim of claims) {
              const statement = text(claim.statement);
              seen.set(statement, (seen.get(statement) || 0) + 1);
            }
            note = Array.from(seen, ([statement, count]) =>
              count > 1 ? `${statement} (×${count})` : statement,
            ).join(" ");
          }
          const state = text(item.state);
          return [
            SECTION_LABELS[name] || name,
            badge(state.replace(/_/g, " "), STATE_BADGES, state),
            note,
          ];
        }),
      ),
    );
    report.appendChild(sectionStates);
    return report;
  }

  function clear(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function showStatus(doc, message, isError) {
    const status = doc.getElementById("status");
    if (status) {
      status.textContent = message;
      status.className = isError ? "status status-error" : "status";
    }
  }

  async function start(env) {
    const doc = env.document;
    const target = doc.getElementById("report");
    if (!target) {
      return false;
    }
    clear(target);
    try {
      const expected = expectedHashFromPath(env.location.pathname);
      if (!expected) {
        throw new ViewerError(
          "This page must be opened from its publication directory, whose name is the report's SHA-256.",
        );
      }
      const response = await env.fetch(SNAPSHOT_FILE, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
      if (!response.ok) {
        throw new ViewerError("The report file could not be loaded.");
      }
      const bytes = new Uint8Array(await response.arrayBuffer());
      const actual = await sha256Hex(env.crypto, bytes);
      if (actual !== expected) {
        throw new ViewerError(
          "The report file does not match this page's directory name, so it is not shown.",
        );
      }
      const snapshot = JSON.parse(
        new env.TextDecoder("utf-8", { fatal: true }).decode(bytes),
      );
      validate(snapshot);
      const report = buildReport(doc, snapshot, actual);
      target.appendChild(report);
      showStatus(doc, "Report file checked: its SHA-256 matches.", false);
      return true;
    } catch (error) {
      clear(target);
      const message =
        error instanceof ViewerError
          ? error.message
          : "The report file could not be read, so it is not shown.";
      showStatus(doc, message, true);
      return false;
    }
  }

  // Theme toggle for this visit only: it sets data-theme on the root element
  // and stores nothing, so a reload follows prefers-color-scheme again.
  function setupThemeToggle(env) {
    const doc = env.document;
    const button = doc.getElementById("theme-toggle");
    const root = doc.documentElement;
    if (!button || !root) {
      return false;
    }
    const query =
      typeof env.matchMedia === "function"
        ? env.matchMedia("(prefers-color-scheme: dark)")
        : null;
    const current = () => {
      const chosen = root.getAttribute("data-theme");
      if (chosen === "light" || chosen === "dark") {
        return chosen;
      }
      return query && query.matches ? "dark" : "light";
    };
    const label = () => {
      button.textContent = THEMES[current()];
    };
    button.addEventListener("click", () => {
      root.setAttribute("data-theme", current() === "dark" ? "light" : "dark");
      label();
    });
    // Until the visitor chooses, the label follows a system theme change.
    if (query && typeof query.addEventListener === "function") {
      query.addEventListener("change", label);
    }
    label();
    button.hidden = false;
    return true;
  }

  function browserEnvironment() {
    return {
      document: global.document,
      location: global.location,
      fetch: global.fetch.bind(global),
      crypto: global.crypto,
      TextDecoder: global.TextDecoder,
      matchMedia: global.matchMedia.bind(global),
    };
  }

  global.GuestDemoViewer = { start, expectedHashFromPath, setupThemeToggle };

  if (global.document && !global.GUEST_DEMO_VIEWER_NO_AUTOSTART) {
    const boot = () => {
      const env = browserEnvironment();
      setupThemeToggle(env);
      start(env);
    };
    if (global.document.readyState === "loading") {
      global.document.addEventListener("DOMContentLoaded", boot);
    } else {
      boot();
    }
  }
})(globalThis);
