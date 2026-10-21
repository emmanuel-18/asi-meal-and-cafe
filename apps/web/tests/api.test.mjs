import test from "node:test";
import assert from "node:assert/strict";
import { apiRequest, ApiError } from "../src/lib/api.ts";

test("session/login/logout use same-origin cookies, no cache, and the real CSRF headers", async t => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return path === "/auth/logout" ? new Response(null, { status: 204 }) : Response.json({ user: { display_name: "Synthetic Admin" }, csrf_token: "synthetic-csrf" });
  });
  await apiRequest("/auth/me");
  await apiRequest("/auth/login", { method: "POST", body: { login_name: "Synthetic.Login", password: "synthetic-test-only" } });
  await apiRequest("/auth/logout", { method: "POST" }, "synthetic-csrf");
  await apiRequest("/api/orders/1", { method: "PATCH", body: { expected_version: 4 } }, "synthetic-csrf");
  await apiRequest("/api/menus/1/dates", { method: "PUT", body: { assignments: [] } }, "synthetic-csrf");
  for (const { options } of calls) {
    assert.equal(options.credentials, "same-origin"); assert.equal(options.cache, "no-store");
    assert.equal("Authorization" in options.headers, false);
    assert.equal("Cookie" in options.headers, false);
  }
  assert.equal(calls[1].options.headers["X-ASI-Request"], "1");
  assert.equal(calls[2].options.headers["X-CSRF-Token"], "synthetic-csrf");
  assert.equal(calls[0].options.body, undefined);
  assert.equal(calls[3].options.method, "PATCH");
  assert.equal(calls[3].options.headers["X-CSRF-Token"], "synthetic-csrf");
  assert.equal(calls[4].options.method, "PUT");
  assert.equal(calls[4].options.headers["X-CSRF-Token"], "synthetic-csrf");
});

test("API errors expose clear status messages without returning sensitive diagnostics", async t => {
  for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
    t.mock.method(globalThis, "fetch", async () => new Response("synthetic-private-diagnostic", { status }));
    await assert.rejects(apiRequest("/api/orders"), error => error instanceof ApiError && error.status === status && !error.message.includes("synthetic-private"));
    t.mock.restoreAll();
  }
  assert.match(new ApiError(409).message, /changed.*refreshed/);
  assert.match(new ApiError(401).message, /expired/);
  t.mock.method(globalThis, "fetch", async () => { throw new Error("synthetic-private-network-error"); });
  await assert.rejects(apiRequest("/api/employees"), error => error.status === 0 && !error.message.includes("synthetic-private"));
  await assert.rejects(apiRequest("https://outside.invalid/api/orders"), /Invalid API path/);
});
