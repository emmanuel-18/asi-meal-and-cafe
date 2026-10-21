import test from "node:test";
import assert from "node:assert/strict";
import { apiRequest, ApiError } from "../src/lib/api.ts";
import { canImport, fileError, fileErrorMessage, issueMessage, maxUpload, searchEmployees, submitImport, uploadEmployees } from "../src/lib/employees.ts";

test("employee search uses server pagination and preserves text identifiers", async () => {
  const paths = [];
  const request = async path => { paths.push(path); return [{ employee_number: "0001", full_name: "Synthetic Person" }]; };
  const result = await searchEmployees(request, " 0001 ", 2);
  assert.equal(result[0].employee_number, "0001");
  assert.equal(paths[0], "/api/employees?q=0001&limit=20&offset=40");
  await searchEmployees(request, "Synthetic Name", 0);
  assert.match(paths[1], /q=Synthetic\+Name&limit=20&offset=0/);
  assert.equal(canImport("admin"), true); assert.equal(canImport("assistant_admin"), false);
});

test("file selection rejects wrong extension and oversize without reading contents", () => {
  assert.match(fileError(null), /Select/);
  assert.match(fileError({ name: "data.txt", size: 1 }), /\.csv/);
  assert.match(fileError({ name: "data.csv", size: maxUpload + 1 }), /8 MiB/);
  assert.equal(fileError({ name: "data.CSV", size: maxUpload }), "");
});

test("upload sends raw bytes with session cookie and CSRF and preserves safe result", async t => {
  const file = new File(["synthetic,csv\n"], "synthetic.csv", { type: "application/octet-stream" });
  let options;
  t.mock.method(globalThis, "fetch", async (path, value) => {
    assert.equal(path, "/api/employees/import"); options = value;
    return Response.json({ import_id: 1, status: "completed", total_rows: 1, inserted_rows: 1, updated_rows: 0, unchanged_rows: 0, rejected_rows: 0, file_error_code: null, errors: [], errors_truncated: false });
  });
  const request = (path, value) => apiRequest(path, value, "synthetic-csrf");
  assert.equal((await uploadEmployees(request, file)).inserted_rows, 1);
  assert.equal(options.body, file); assert.equal(options.headers["Content-Type"], "text/csv");
  assert.equal(options.headers["X-CSRF-Token"], "synthetic-csrf");
  assert.equal(options.credentials, "same-origin"); assert.equal(options.cache, "no-store");
});

test("failed batch summary is available while unknown diagnostics stay private", async t => {
  const payload = { import_id: 2, status: "failed", total_rows: 2, inserted_rows: 0, updated_rows: 0, unchanged_rows: 0, rejected_rows: 2, file_error_code: "VALIDATION_FAILED", errors: [{ row_number: 1, issues: [{ field: "full_name", code: "REQUIRED" }] }], errors_truncated: false };
  t.mock.method(globalThis, "fetch", async () => Response.json(payload, { status: 422 }));
  const result = await uploadEmployees((p, o) => apiRequest(p, o, "csrf"), new File(["x"], "test.csv"));
  assert.equal(result.rejected_rows, 2); assert.match(issueMessage(result.errors[0].issues[0]), /Full name is required/);
  assert.match(fileErrorMessage(result.file_error_code), /validation/);
  assert.doesNotMatch(issueMessage({ field: "synthetic-private", code: "synthetic-private" }), /synthetic-private/);
  assert.doesNotMatch(fileErrorMessage("synthetic-private"), /synthetic-private/);
});

test("session and authorization errors remain errors for CSV uploads", async t => {
  for (const status of [401, 403, 413, 503]) {
    t.mock.method(globalThis, "fetch", async () => new Response("synthetic-private", { status }));
    await assert.rejects(uploadEmployees((p, o) => apiRequest(p, o, "csrf"), new File(["x"], "test.csv")), error => error instanceof ApiError && error.status === status && !error.message.includes("synthetic-private"));
    t.mock.restoreAll();
  }
});

test("in-flight submission is guarded and only completion refreshes the directory", async () => {
  let resolve, calls = 0, refreshes = 0;
  const file = new File(["x"], "test.csv"), guard = { current: false };
  const request = () => { calls++; return new Promise(done => { resolve = done; }); };
  const pending = submitImport(request, file, guard, () => { refreshes++; });
  assert.equal(guard.current, true);
  assert.equal(await submitImport(request, file, guard, () => { refreshes++; }), null);
  assert.equal(calls, 1);
  resolve({ import_id: 1, status: "completed", total_rows: 1, inserted_rows: 1, updated_rows: 0, unchanged_rows: 0, rejected_rows: 0, file_error_code: null, errors: [], errors_truncated: false });
  await pending; assert.equal(refreshes, 1); assert.equal(guard.current, false);
  const failed = async () => ({ import_id: 2, status: "failed", total_rows: 1, inserted_rows: 0, updated_rows: 0, unchanged_rows: 0, rejected_rows: 1, file_error_code: "VALIDATION_FAILED", errors: [], errors_truncated: false });
  await submitImport(failed, file, guard, () => { refreshes++; });
  assert.equal(refreshes, 1);
});
