// Headless harness for prototype/shared/engine-check-view.js.
//
// The viewer is the only place where an engine result becomes something a human
// reads, so `node --check` (which every other prototype script settles for) is
// not enough here -- a syntax-valid renderer can still silently drop the
// authority triple or grow a button that looks like it makes a decision. This
// harness gives the viewer a minimal DOM, renders every committed fixture, and
// prints a JSON description of the resulting tree for check_engine_check_view.py
// to assert against.
//
// The shim is deliberately tiny and text-only: it implements exactly the DOM
// surface the viewer is allowed to use. If the viewer ever reaches for
// innerHTML, an event listener, or a network call, this harness throws rather
// than quietly passing.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..");
const VIEWER = join(REPO_ROOT, "prototype", "shared", "engine-check-view.js");
const FIXTURES = join(REPO_ROOT, "prototype", "shared", "engine-check-fixtures.js");

class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this._class = "";
    this._text = "";
    this.dataset = {};
    this.classList = {
      add: (...names) => {
        const seen = new Set(this._class.split(/\s+/).filter(Boolean));
        for (const name of names) seen.add(name);
        this._class = [...seen].join(" ");
      },
    };
  }
  set className(value) { this._class = String(value); }
  get className() { return this._class; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join(" ") : this._text; }
  set innerHTML(_value) { throw new Error("viewer assigned innerHTML; it must build nodes and set textContent"); }
  addEventListener() { throw new Error("viewer attached an event listener; it must stay read-only"); }
  append(...nodes) { for (const node of nodes) this.children.push(node); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  get firstElementChild() { return this.children[0] ?? null; }
}

const document = {
  createElement: (tag) => new Node(tag),
};

const forbid = (name) => () => { throw new Error(`viewer called ${name}; it must not touch the network or storage`); };
const SOURCE = readFileSync(VIEWER, "utf8");

/** Load a fresh copy of the viewer, optionally with the shared i18n runtime present. */
function loadViewer(i18n) {
  const sandboxWindow = {};
  const sandbox = {
    document,
    window: sandboxWindow,
    console,
    fetch: forbid("fetch"),
    localStorage: { getItem: forbid("localStorage"), setItem: forbid("localStorage") },
    sessionStorage: { getItem: forbid("sessionStorage"), setItem: forbid("sessionStorage") },
  };
  sandbox.globalThis = sandbox;
  if (i18n) sandbox.RC_I18N = i18n;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox, { filename: "engine-check-view.js" });
  const view = sandboxWindow.RC_ENGINE_CHECK_VIEW;
  if (!view) throw new Error("engine-check-view.js did not expose window.RC_ENGINE_CHECK_VIEW");
  return view;
}

// Without RC_I18N the component must still render (English fallback); with it,
// the demo default of zh-Hant must actually reach the screen. Both are real
// deployment states, so both are exercised.
const view = loadViewer(null);
const viewZh = loadViewer({ pick: (zh, _en) => zh });

const describe = (node) => ({
  tag: node.tagName.toLowerCase(),
  class: node.className,
  dataset: { ...node.dataset },
  text: node.children.length ? "" : node._text,
  children: node.children.map(describe),
});

// The fixtures ship as a browser-loadable global, so they are loaded the same
// way the prototype page loads them: evaluated, not parsed out of a .json file.
const fixtureWindow = {};
vm.runInContext(readFileSync(FIXTURES, "utf8"), vm.createContext({ window: fixtureWindow }), { filename: "engine-check-fixtures.js" });
const fixtures = fixtureWindow.RC_ENGINE_CHECK_FIXTURES.fixtures;
const rendered = [];
for (const fixture of fixtures) {
  rendered.push({
    fixture_id: fixture.fixture_id,
    outcome: fixture.check.outcome,
    tree: describe(view.render(fixture.check)),
    tree_zh: describe(viewZh.render(fixture.check)),
  });
}

// Degenerate inputs must produce a rendered explanation, never a thrown error:
// a consumer that crashes on a malformed check would show nothing at all, which
// is a worse failure than saying "this is not an engine-check.v1 result".
const degenerate = [];
for (const [label, value] of [["null", null], ["string", "not an object"], ["wrong_schema", { schema_version: "engine-check.v0", outcome: "supported" }], ["empty_object", {}]]) {
  degenerate.push({ label, tree: describe(view.render(value)) });
}

// mount() must replace, not append -- a stale check left on screen next to a
// new one is a correctness problem, not a cosmetic one.
const host = new Node("div");
host.append(new Node("p"));
view.mount(host, fixtures[0].check);
view.mount(host, fixtures[1].check);
const mounted = { child_count: host.children.length, tree: describe(host) };

process.stdout.write(JSON.stringify({ outcomes: view.outcomes, rendered, degenerate, mounted }, null, 2));
