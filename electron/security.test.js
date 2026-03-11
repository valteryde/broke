const test = require("node:test");
const assert = require("node:assert/strict");

const {
  isAllowedBackendUrl,
  isAllowedBootstrapUrl,
  isAllowedExternalUrl,
  isAllowedNavigationUrl,
  isLocalRendererUrl,
  sameOrigin,
} = require("./security");

test("sameOrigin matches exact origin only", () => {
  assert.equal(sameOrigin("https://broke.example.com/news", "https://broke.example.com/settings"), true);
  assert.equal(sameOrigin("https://broke.example.com", "https://broke.example.com.evil.test"), false);
});

test("backend URLs require https except localhost http", () => {
  assert.equal(isAllowedBackendUrl("https://broke.example.com"), true);
  assert.equal(isAllowedBackendUrl("http://localhost:8000"), true);
  assert.equal(isAllowedBackendUrl("http://127.0.0.1:5000"), true);
  assert.equal(isAllowedBackendUrl("http://example.com"), false);
  assert.equal(isAllowedBackendUrl("file:///tmp/test"), false);
});

test("bootstrap URL is restricted to the desktop bootstrap endpoint", () => {
  assert.equal(isAllowedBootstrapUrl("https://broke.example.com/api/desktop/bootstrap"), true);
  assert.equal(isAllowedBootstrapUrl("http://localhost:8000/api/desktop/bootstrap"), true);
  assert.equal(isAllowedBootstrapUrl("https://broke.example.com/api/desktop/session"), false);
  assert.equal(isAllowedBootstrapUrl("file:///tmp/bootstrap.json"), false);
});

test("external URL opening is limited to http and https", () => {
  assert.equal(isAllowedExternalUrl("https://example.com/docs"), true);
  assert.equal(isAllowedExternalUrl("http://localhost:3000"), true);
  assert.equal(isAllowedExternalUrl("mailto:user@example.com"), false);
  assert.equal(isAllowedExternalUrl("file:///etc/passwd"), false);
  assert.equal(isAllowedExternalUrl("javascript:alert(1)"), false);
});

test("navigation allows only local picker or same-origin backend pages", () => {
  assert.equal(isAllowedNavigationUrl("file:///app/index.html", "https://broke.example.com"), true);
  assert.equal(isAllowedNavigationUrl("https://broke.example.com/news", "https://broke.example.com"), true);
  assert.equal(isAllowedNavigationUrl("https://broke.example.com.evil.test/news", "https://broke.example.com"), false);
  assert.equal(isAllowedNavigationUrl("https://other.example.com/news", "https://broke.example.com"), false);
});

test("local renderer detection matches file URLs only", () => {
  assert.equal(isLocalRendererUrl("file:///app/index.html"), true);
  assert.equal(isLocalRendererUrl("https://broke.example.com/news"), false);
});