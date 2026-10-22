import test from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../src/lib/api.ts";
import { listingError, loadOrderPage, receiveError } from "../src/lib/order-register.ts";

test("quick receipt errors require correction or review without blind retries", () => {
  assert.match(receiveError(new ApiError(422)), /allocations.*Edit Pending/);
  assert.match(receiveError(new ApiError(409)), /changed.*review/i);
  for (const status of [0, 500, 503]) assert.match(receiveError(new ApiError(status)), /could not be confirmed.*review/i);
  assert.match(receiveError(new ApiError(403)), /not permitted/i);
});

test("register binds later pages to the listing revision and resets on refresh or filters", async () => {
  const calls = [];
  const request = async path => { calls.push(path); return { revision: 'a'.repeat(64), orders: [] }; };
  const first = await loadOrderPage(request, '2040-01-02', 'pending', 0, null);
  await loadOrderPage(request, '2040-01-02', 'pending', 20, first.revision);
  await loadOrderPage(request, '2040-01-03', 'received', 0, first.revision);
  assert.match(calls[1], /revision=aaa/);
  assert.doesNotMatch(calls[2], /revision=/);
  assert.match(calls[2], /status=received/);
  await assert.rejects(loadOrderPage(request, '', '', 20, null), /Restart/);
  assert.match(listingError(new ApiError(409)), /listing changed.*Refresh orders/i);
});
