const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
function app(data) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        innerHTML: "",
        textContent: "",
        value: "",
        hidden: false,
        style: {},
        dataset: {},
        classList: {
          add: (x) => classes.add(x),
          remove: (x) => classes.delete(x),
          contains: (x) => classes.has(x),
          toggle: (x, v) => (v ? classes.add(x) : classes.delete(x)),
        },
        setAttribute() {},
        focus() {},
        scrollIntoView() {},
        checked: false,
      });
    }
    return elements.get(id);
  }
  const context = vm.createContext({
    console,
    URL,
    URLSearchParams,
    AbortSignal,
    setTimeout,
    clearTimeout,
    localStorage: { getItem: () => null, setItem() {} },
    window: {
      fmhyData: data,
      location: { href: "http://localhost/", pathname: "/", search: "" },
      history: { replaceState() {} },
      matchMedia: () => ({ matches: false }),
    },
    document: {
      getElementById: element,
      querySelector: () => null,
      querySelectorAll: () => [],
      activeElement: null,
      createTreeWalker: () => ({ nextNode: () => null }),
    },
    NodeFilter: { SHOW_TEXT: 4 },
    fetch: async () => {
      throw new Error("offline");
    },
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"),
    context,
  );
  return { run: (code) => vm.runInContext(code, context), element, context };
}
const link = (name, type = "new", source = "video") => ({
  link: `* [${name}](https://example.com/${name})`,
  type,
  source,
});
const commit = (sha, added = [], removed = []) => ({
  sha,
  date: "2026-09-29T00:00:00Z",
  message: "resource changes",
  added,
  removed,
});

test("pagination excludes non-matching commits and caps one large commit at 50 rows", () => {
  const a = app({
    commits: [
      commit(
        "a",
        Array.from({ length: 65 }, (_, i) => link(`item${i}`)),
      ),
      ...Array.from({ length: 60 }, (_, i) =>
        commit(`b${i}`, [link("updated", "updated")]),
      ),
    ],
  });
  a.run('state.currentFilter = "new"; renderCommits()');
  assert.equal(
    (a.element("commits-container").innerHTML.match(/<li /g) || []).length,
    50,
  );
  assert.match(a.element("commits-container").innerHTML, /Page 1 of 2/);
  a.run("changePage(1)");
  assert.equal(
    (a.element("commits-container").innerHTML.match(/<li /g) || []).length,
    15,
  );
  assert.match(a.element("commits-container").innerHTML, /Page 2 of 2/);
});

test("facet totals include monthly data, deduplicate SHA and rows, and respect other filters", () => {
  const first = commit("a", [
    link("⭐ alpha"),
    link("⭐ alpha"),
    link("beta", "updated", "audio"),
  ]);
  const a = app({ commits: [first] });
  a.context.month = { commits: [first, commit("b", [], [link("⭐ old")])] };
  a.run(
    'state.monthlyData = month; state.showMonthly = true; state.showOnlyStarred = true; state.categoryFilter = "video"; renderCommits()',
  );
  assert.equal(a.element("total-all").textContent, 2);
  assert.equal(a.element("total-new").textContent, 1);
  assert.equal(a.element("total-removed").textContent, 1);
  a.run('state.currentFilter = "removed"; renderCommits()');
  assert.equal(a.element("total-all").textContent, 2);
  assert.equal(
    (a.element("commits-container").innerHTML.match(/<li /g) || []).length,
    1,
  );
  assert.match(
    a.element("category-filters").innerHTML,
    /video[\s\S]*category-count">1/,
  );
});

test("search trims whitespace and finds categories and commit messages", () => {
  const a = app({
    commits: [
      commit("a", [link("alpha")]),
      commit("b", [link("beta", "new", "audio")]),
    ],
  });
  assert.equal(
    a.run('state.searchQuery = "  VIDEO  "; matchingRows().length'),
    1,
  );
  assert.equal(
    a.run('state.searchQuery = "resource changes"; matchingRows().length'),
    2,
  );
});

test("search finds and reveals the previous link for an updated row", () => {
  const updated = {
    ...link("new-site", "updated"),
    relatedLink: "* [old-site](https://old.example.test/resource)",
  };
  const a = app({ commits: [commit("a", [updated])] });

  a.run('state.searchQuery = "old.example.test"; renderCommits()');

  assert.equal(a.run("matchingRows().length"), 1);
  assert.match(
    a.element("commits-container").innerHTML,
    /<details class="change-details"[^>]* open>/,
  );
  assert.match(
    a.element("commits-container").innerHTML,
    /href="https:\/\/old\.example\.test\/resource"/,
  );
});

test("history failure remains visible and retry succeeds with the actual archive month", async () => {
  const a = app({ commits: [] });
  a.element("monthly-toggle").checked = true;
  await a.run("toggleMonthlyView()");
  assert.equal(
    a.element("monthly-message").classList.contains("hidden"),
    false,
  );
  assert.equal(a.element("monthly-retry").hidden, false);
  assert.equal(a.element("monthly-toggle").checked, false);
  a.context.fetch = async () => ({
    ok: true,
    json: async () => ({
      month: "2026-07",
      totalCommits: 1,
      commits: [commit("a", [link("alpha")])],
    }),
  });
  a.element("monthly-toggle").checked = true;
  await a.run("toggleMonthlyView()");
  assert.match(a.element("monthly-message").textContent, /July 2026/);
  assert.equal(a.element("monthly-retry").hidden, true);
  assert.equal(a.run("state.showMonthly"), true);
});

test("unsafe before/after markup is escaped and script URLs are not clickable", () => {
  const item = {
    ...link("<img onerror=alert(1)>", "updated"),
    relatedLink: "* [Old](javascript:alert(1)) <script>alert(1)</script>",
  };
  const a = app({ commits: [commit("a", [item])] });
  a.run("renderCommits()");
  const html = a.element("commits-container").innerHTML;
  assert.match(html, /<summary>What changed\?<\/summary>/);
  assert.doesNotMatch(html, /href="javascript:|<img|<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("starred links keep their filter signal and render an accessible icon", () => {
  const a = app({
    commits: [
      commit("a", [
        { ...link("alpha"), link: "* ⭐ **[alpha](https://example.com/alpha)**" },
      ]),
    ],
  });
  a.run("renderCommits()");
  const html = a.element("commits-container").innerHTML;
  assert.match(html, /class="resource-marker" role="img" aria-label="Starred source"/);
  assert.doesNotMatch(html, /⭐/);
  const featured = a.run('parseMarkdownLinks("🌟 **[featured](https://example.com/featured)**")');
  assert.match(featured, /aria-label="Featured source"/);
  assert.doesNotMatch(featured, /🌟/);
  assert.equal(a.run('getFilterView().rows.length'), 1);
  assert.equal(a.run('prepareItem(getRows()[0].item, getRows()[0].commit).starred'), true);
});

test("storage failures do not prevent application startup or preferences", () => {
  const a = app({ commits: [] });
  a.context.localStorage = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  };
  assert.equal(a.run('readPreference("test")'), null);
  assert.doesNotThrow(() => a.run('writePreference("test", true)'));
});

test("rapid typing renders only the final query after the debounce", async () => {
  const a = app({ commits: [commit("a", [link("alpha"), link("beta")])] });
  let scheduled;
  let pending = 0;
  a.context.setTimeout = (callback) => {
    scheduled = callback;
    pending++;
    return pending;
  };
  a.context.clearTimeout = () => {
    pending = 0;
  };
  a.run(
    'handleSearch({target: {value: "a"}}); handleSearch({target: {value: "alpha"}})',
  );
  assert.equal(a.element("commits-container").innerHTML, "");
  assert.equal(pending, 1);
  scheduled();
  assert.equal(
    (a.element("commits-container").innerHTML.match(/<li /g) || []).length,
    1,
  );
});

test("malformed monthly data fails without enabling history", async () => {
  const a = app({ commits: [] });
  a.context.fetch = async () => ({
    ok: true,
    json: async () => ({ month: "September", commits: [{}] }),
  });
  a.element("monthly-toggle").checked = true;
  await a.run("toggleMonthlyView()");
  assert.equal(a.run("state.showMonthly"), false);
  assert.equal(a.element("monthly-retry").hidden, false);
});

test("page URLs restore, clamp to matching results, and reset when filters change", () => {
  const a = app({ commits: [commit('a', Array.from({ length: 125 }, (_, i) => link(`item${i}`)))] });
  let url;
  a.context.window.history.replaceState = (_, __, value) => { url = value; };
  a.context.window.location.search = '?page=3&starred=0';
  a.run('restoreStateFromUrl(); renderCommits()');
  assert.equal(a.run('state.currentPage'), 3);
  assert.match(url, /page=3/);
  a.run('goToPage(999)');
  assert.equal(a.run('state.currentPage'), 3);
  a.run('setFilter("updated")');
  assert.equal(a.run('state.currentPage'), 1);
  assert.doesNotMatch(url, /page=/);
  a.context.window.location.search = '?page=Infinity';
  a.run('restoreStateFromUrl()');
  assert.equal(a.run('state.currentPage'), 1);
});

test("facet cache survives pagination and invalidates on filters and archive changes", () => {
  const a = app({ commits: [commit('a', [link('alpha'), link('beta', 'updated', 'audio')])] });
  a.run('globalThis.firstView = getFilterView(); state.currentPage = 2');
  assert.equal(a.run('getFilterView() === firstView'), true);
  a.run('state.categoryFilter = "video"');
  assert.equal(a.run('getFilterView() === firstView'), false);
  assert.equal(a.run('getFilterView().rows.length'), 1);
  assert.equal(a.run('getFilterView().categoryCounts.audio'), 1);
  a.context.month = { commits: [commit('b', [], [link('old')])] };
  a.run('state.monthlyData = month; state.showMonthly = true');
  assert.equal(a.run('getFilterView().rows.length'), 2);
  assert.equal(a.run('getFilterView().typeCounts.removed'), 1);
  a.run('state.showMonthly = false');
  assert.equal(a.run('getFilterView().rows.length'), 1);
});

test("history restores a requested page only after the archive is available", async () => {
  const a = app({ commits: [] });
  a.context.fetch = async () => ({ ok: true, json: async () => ({
    month: '2026-09', commits: [commit('a', Array.from({ length: 160 }, (_, i) => link(`item${i}`)))],
  }) });
  a.element('monthly-toggle').checked = true;
  await a.run('toggleMonthlyView({ restorePage: 3 })');
  assert.equal(a.run('state.currentPage'), 3);
  assert.match(a.element('commits-container').innerHTML, /Page 3 of 4/);
});

test("header timestamp shows only the relative time; the full date is the tooltip", () => {
  const updated = new Date(Date.now() - (15 * 60 + 40) * 60 * 1000).toISOString();
  const a = app({ commits: [], lastUpdated: updated });
  a.run("refreshRelativeTimes()");
  const element = a.element("last-updated");
  assert.equal(element.textContent, "15h 40m ago");
  assert.notEqual(element.title, "");
});
