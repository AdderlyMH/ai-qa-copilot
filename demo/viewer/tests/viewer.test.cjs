// DOM-level tests for the guest demo viewer, with Node's built-in test runner
// and a minimal DOM stub (no dependency). Run by
// apps/api/tests/test_guest_demo_viewer.py, which builds the snapshot and
// passes its path in GUEST_DEMO_SNAPSHOT.
"use strict";

const assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const VIEWER_SOURCE = fs.readFileSync(
  path.join(__dirname, "..", "viewer.js"),
  "utf8",
);
const HOSTILE = JSON.parse(
  fs.readFileSync(path.join(__dirname, "hostile-strings.json"), "utf8"),
);
const SNAPSHOT_PATH = process.env.GUEST_DEMO_SNAPSHOT;

const ALLOWED_TAGS = new Set([
  "ARTICLE",
  "BLOCKQUOTE",
  "CAPTION",
  "DIV",
  "H2",
  "H3",
  "LI",
  "P",
  "SECTION",
  "SPAN",
  "TABLE",
  "TBODY",
  "TD",
  "TH",
  "THEAD",
  "TR",
  "UL",
]);
const ALLOWED_ATTRIBUTES = new Set([
  "aria-label",
  "aria-labelledby",
  "role",
  "scope",
  "tabindex",
]);

class TextNode {
  constructor(data) {
    this.data = data;
    this.childNodes = [];
  }
  get textContent() {
    return this.data;
  }
}

class ParentNode {
  constructor() {
    this.childNodes = [];
  }
  get firstChild() {
    return this.childNodes[0] || null;
  }
  get textContent() {
    return this.childNodes.map((node) => node.textContent).join("");
  }
  set textContent(value) {
    this.childNodes = [];
    const content = String(value);
    if (content !== "") {
      this.childNodes.push(new TextNode(content));
    }
  }
  appendChild(child) {
    if (child instanceof Fragment) {
      for (const node of child.childNodes.splice(0)) {
        this.appendChild(node);
      }
      return child;
    }
    assert.ok(child instanceof Element, "only stub elements may be appended");
    this.childNodes.push(child);
    return child;
  }
  removeChild(child) {
    const index = this.childNodes.indexOf(child);
    assert.notEqual(index, -1);
    this.childNodes.splice(index, 1);
    return child;
  }
}

class Fragment extends ParentNode {}

class Element extends ParentNode {
  constructor(tagName) {
    super();
    this.tagName = tagName;
    this.attributes = new Map();
    this.className = "";
    this.id = "";
  }
  setAttribute(name, value) {
    assert.ok(ALLOWED_ATTRIBUTES.has(name), `unexpected attribute ${name}`);
    this.attributes.set(name, String(value));
  }
  get childElementCount() {
    return this.childNodes.filter((node) => node instanceof Element).length;
  }
}
for (const sink of ["innerHTML", "outerHTML"]) {
  Object.defineProperty(Element.prototype, sink, {
    get() {
      throw new Error(`${sink} was read`);
    },
    set() {
      throw new Error(`${sink} was written`);
    },
  });
}
Element.prototype.insertAdjacentHTML = () => {
  throw new Error("insertAdjacentHTML was called");
};

function makeDocument() {
  const status = new Element("DIV");
  const report = new Element("DIV");
  const listeners = [];
  const toggle = new Element("BUTTON");
  toggle.hidden = true;
  toggle.addEventListener = (type, listener) => {
    assert.equal(type, "click");
    listeners.push(listener);
  };
  toggle.click = () => listeners.forEach((listener) => listener());
  const rootAttributes = new Map();
  const documentElement = {
    attributes: rootAttributes,
    getAttribute(name) {
      return rootAttributes.has(name) ? rootAttributes.get(name) : null;
    },
    setAttribute(name, value) {
      assert.equal(name, "data-theme", "only data-theme may be set on <html>");
      rootAttributes.set(name, String(value));
    },
  };
  const doc = {
    status,
    report,
    toggle,
    documentElement,
    createElement(tag) {
      const name = String(tag).toUpperCase();
      assert.ok(ALLOWED_TAGS.has(name), `unexpected element ${name}`);
      return new Element(name);
    },
    createDocumentFragment() {
      return new Fragment();
    },
    getElementById(id) {
      return { status, report, "theme-toggle": toggle }[id] || null;
    },
    write() {
      throw new Error("document.write was called");
    },
  };
  Object.defineProperty(doc, "cookie", {
    get() {
      throw new Error("document.cookie was read");
    },
    set() {
      throw new Error("document.cookie was written");
    },
  });
  return doc;
}

// Fails the test if the viewer touches any browser storage API.
function trapStorage() {
  const names = ["localStorage", "sessionStorage", "indexedDB"];
  const saved = names.map((name) => [
    name,
    Object.getOwnPropertyDescriptor(globalThis, name),
  ]);
  const touched = [];
  for (const name of names) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      get() {
        touched.push(name);
        throw new Error(`${name} was touched`);
      },
    });
  }
  return {
    touched,
    restore() {
      for (const [name, descriptor] of saved) {
        if (descriptor) {
          Object.defineProperty(globalThis, name, descriptor);
        } else {
          delete globalThis[name];
        }
      }
    },
  };
}

function prefersDark(dark) {
  const listeners = [];
  const media = {
    matches: dark,
    addEventListener(type, listener) {
      assert.equal(type, "change");
      listeners.push(listener);
    },
    change(nowDark) {
      media.matches = nowDark;
      listeners.forEach((listener) => listener());
    },
  };
  const matchMedia = (query) => {
    assert.equal(query, "(prefers-color-scheme: dark)");
    return media;
  };
  matchMedia.media = media;
  return matchMedia;
}

function loadViewer() {
  globalThis.GUEST_DEMO_VIEWER_NO_AUTOSTART = true;
  vm.runInThisContext(VIEWER_SOURCE, { filename: "viewer.js" });
  return globalThis.GuestDemoViewer;
}

const viewer = loadViewer();

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function environment(doc, bytes, pathname, options = {}) {
  const requests = [];
  return {
    requests,
    env: {
      document: doc,
      location: { pathname },
      crypto: webcrypto,
      TextDecoder,
      async fetch(url, init) {
        requests.push({ url, init });
        if (options.fetchError) {
          throw new Error("network down");
        }
        return {
          ok: options.ok !== false,
          async arrayBuffer() {
            return bytes.buffer.slice(
              bytes.byteOffset,
              bytes.byteOffset + bytes.byteLength,
            );
          },
        };
      },
    },
  };
}

function walk(node, visit) {
  visit(node);
  for (const child of node.childNodes) {
    walk(child, visit);
  }
}

function textNodes(root) {
  const found = [];
  walk(root, (node) => {
    if (node instanceof TextNode) {
      found.push(node.data);
    }
  });
  return found;
}

function realSnapshotBytes() {
  assert.ok(SNAPSHOT_PATH, "GUEST_DEMO_SNAPSHOT must name a built snapshot");
  return new Uint8Array(fs.readFileSync(SNAPSHOT_PATH));
}

function hostileSnapshot() {
  const snapshot = JSON.parse(Buffer.from(realSnapshotBytes()).toString("utf8"));
  const strings = [
    ...HOSTILE.strings,
    "L".repeat(HOSTILE.long_string_length),
  ];
  let next = 0;
  const pick = () => strings[next++ % strings.length];
  const used = new Set();
  const take = () => {
    const value = pick();
    used.add(value);
    return value;
  };

  for (const key of Object.keys(snapshot.provenance)) {
    if (key !== "not_a_model_result") {
      snapshot.provenance[key] = take();
    }
  }
  for (const excerpt of snapshot.excerpts) {
    excerpt.text = take();
  }
  for (const section of snapshot.sections) {
    if (section.state_reason !== null) {
      section.state_reason = take();
    }
    for (const claim of section.claims) {
      claim.statement = take();
    }
  }
  snapshot.traceability.label = take();
  snapshot.traceability.report_section_note = take();
  for (const item of snapshot.summary.finding_counts) {
    item.severity = take();
    item.category = take();
  }
  return {
    bytes: new Uint8Array(Buffer.from(JSON.stringify(snapshot), "utf8")),
    used,
  };
}

test("the published snapshot renders after its hash is verified", async () => {
  const bytes = realSnapshotBytes();
  const doc = makeDocument();
  const { env, requests } = environment(doc, bytes, `/${sha256(bytes)}/`);
  assert.equal(await viewer.start(env), true);

  assert.deepEqual(
    requests.map((request) => [request.url, request.init.method]),
    [["snapshot.json", "GET"]],
  );
  assert.equal(requests[0].init.credentials, "omit");
  const rendered = doc.report.textContent;
  assert.ok(rendered.includes("This is not a model result."));
  assert.ok(rendered.includes("requirement-quality-rules/v1"));
  assert.ok(rendered.includes("Traceability (derived)"));
  assert.ok(
    rendered.includes("The report's own traceability section is not available in v1."),
  );
  assert.ok(rendered.indexOf("Requirement 1 (line 8)") < rendered.indexOf("Requirement 8 (line 15)"));
  assert.ok(!/pub-[0-9a-f]{16}/.test(rendered), "public IDs are not printed");
  assert.match(doc.status.textContent, /SHA-256 matches/);
});

test("hostile strings in the data render only as inert text", async () => {
  const { bytes, used } = hostileSnapshot();
  const doc = makeDocument();
  const { env } = environment(doc, bytes, `/${sha256(bytes)}/index.html`);
  assert.equal(await viewer.start(env), true);

  const texts = textNodes(doc.report);
  for (const value of used) {
    assert.ok(
      texts.some((textValue) => textValue.includes(value)),
      `hostile string missing from text: ${value.slice(0, 40)}`,
    );
  }
  walk(doc.report, (node) => {
    if (node instanceof Element) {
      assert.ok(ALLOWED_TAGS.has(node.tagName));
      for (const value of node.attributes.values()) {
        for (const hostile of used) {
          assert.ok(!value.includes(hostile), "data reached an attribute");
        }
      }
      for (const hostile of used) {
        assert.notEqual(node.className, hostile);
        assert.notEqual(node.id, hostile);
      }
    }
  });
});

test("a hash mismatch renders nothing from the data", async () => {
  const bytes = realSnapshotBytes();
  const doc = makeDocument();
  const wrong = sha256(Buffer.from("not the snapshot"));
  const { env } = environment(doc, bytes, `/${wrong}/`);
  assert.equal(await viewer.start(env), false);
  assert.equal(doc.report.childNodes.length, 0);
  assert.match(doc.status.textContent, /does not match/);
  assert.ok(!doc.status.textContent.includes("shipped order"));
});

test("a page outside a hash-named directory refuses to load data", async () => {
  const bytes = realSnapshotBytes();
  for (const pathname of ["/", "/index.html", "/demo/", `/${sha256(bytes)}`]) {
    const doc = makeDocument();
    const { env, requests } = environment(doc, bytes, pathname);
    assert.equal(await viewer.start(env), false, pathname);
    assert.equal(requests.length, 0, pathname);
    assert.equal(doc.report.childNodes.length, 0);
  }
});

test("fetch, HTTP, parse and schema failures render nothing", async () => {
  const good = realSnapshotBytes();
  const notJson = new Uint8Array(Buffer.from("{not json", "utf8"));
  const wrongClass = new Uint8Array(
    Buffer.from(
      JSON.stringify({
        ...JSON.parse(Buffer.from(good).toString("utf8")),
        content_class: "evaluation",
      }),
      "utf8",
    ),
  );
  const cases = [
    [good, { fetchError: true }],
    [good, { ok: false }],
    [notJson, {}],
    [wrongClass, {}],
  ];
  for (const [bytes, options] of cases) {
    const doc = makeDocument();
    const { env } = environment(doc, bytes, `/${sha256(bytes)}/`, options);
    assert.equal(await viewer.start(env), false);
    assert.equal(doc.report.childNodes.length, 0);
    assert.match(doc.status.className, /status-error/);
  }
});

test("the theme toggle follows the system theme, then flips data-theme only", async () => {
  const storage = trapStorage();
  try {
    for (const [systemDark, first, second] of [
      [false, "dark", "light"],
      [true, "light", "dark"],
    ]) {
      const bytes = realSnapshotBytes();
      const doc = makeDocument();
      const { env } = environment(doc, bytes, `/${sha256(bytes)}/`);
      env.matchMedia = prefersDark(systemDark);
      assert.equal(await viewer.start(env), true);
      const reportBefore = doc.report.textContent;
      const statusBefore = doc.status.textContent;

      assert.equal(viewer.setupThemeToggle(env), true);
      assert.equal(doc.toggle.hidden, false);
      assert.equal(
        doc.toggle.textContent,
        systemDark ? "Switch to light theme" : "Switch to dark theme",
      );
      assert.equal(doc.documentElement.getAttribute("data-theme"), null);

      doc.toggle.click();
      assert.equal(doc.documentElement.getAttribute("data-theme"), first);
      assert.equal(
        doc.toggle.textContent,
        first === "dark" ? "Switch to light theme" : "Switch to dark theme",
      );
      doc.toggle.click();
      assert.equal(doc.documentElement.getAttribute("data-theme"), second);

      assert.deepEqual([...doc.documentElement.attributes.keys()], ["data-theme"]);
      assert.equal(doc.report.textContent, reportBefore, "report unchanged");
      assert.equal(doc.status.textContent, statusBefore, "status unchanged");
    }
    assert.deepEqual(storage.touched, []);
  } finally {
    storage.restore();
  }
});

test("the theme toggle works on the error page too and without matchMedia", async () => {
  const storage = trapStorage();
  try {
    const doc = makeDocument();
    const { env } = environment(doc, realSnapshotBytes(), "/");
    assert.equal(await viewer.start(env), false);
    assert.equal(viewer.setupThemeToggle(env), true);
    assert.equal(doc.toggle.textContent, "Switch to dark theme");
    doc.toggle.click();
    assert.equal(doc.documentElement.getAttribute("data-theme"), "dark");
    assert.equal(doc.report.childNodes.length, 0);
    assert.deepEqual(storage.touched, []);
  } finally {
    storage.restore();
  }
});

test("severity and state badges take their class from a fixed table", async () => {
  const bytes = realSnapshotBytes();
  const doc = makeDocument();
  const { env } = environment(doc, bytes, `/${sha256(bytes)}/`);
  assert.equal(await viewer.start(env), true);
  const classes = new Set();
  walk(doc.report, (node) => {
    if (node instanceof Element && node.tagName === "SPAN") {
      classes.add(node.className);
    }
  });
  assert.deepEqual(
    [...classes].sort(),
    [
      "badge badge-high",
      "badge badge-medium",
      "badge badge-neutral",
      "badge badge-ok",
    ],
  );
});

test("the toggle label follows a system theme change until the visitor chooses", () => {
  const doc = makeDocument();
  const matchMedia = prefersDark(false);
  const env = { document: doc, matchMedia };
  assert.equal(viewer.setupThemeToggle(env), true);
  assert.equal(doc.toggle.textContent, "Switch to dark theme");
  matchMedia.media.change(true);
  assert.equal(doc.toggle.textContent, "Switch to light theme");
  assert.equal(doc.documentElement.getAttribute("data-theme"), null);
  doc.toggle.click();
  assert.equal(doc.documentElement.getAttribute("data-theme"), "light");
  matchMedia.media.change(false);
  assert.equal(doc.toggle.textContent, "Switch to dark theme");
  assert.equal(doc.documentElement.getAttribute("data-theme"), "light");
});
