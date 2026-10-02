import { expect, test } from "@playwright/test";
import { safeNextPath } from "../../lib/api";

const ORIGIN = "http://localhost:3110";

const REJECTED = [
  "//evil.example",
  "/\\evil.example",
  "/%09/evil.example",
  "/\t/evil.example",
  "/\n/evil.example",
  "https://evil.example",
  "javascript:alert(1)",
  "/%2F%2Fevil.example",
  "/%5Cevil.example",
  "/login",
  "/login?next=/x",
];

for (const next of REJECTED) {
  test(`safeNextPath rejects ${JSON.stringify(next)}`, () => {
    expect(safeNextPath(next, ORIGIN)).toBeNull();
  });
}

test("safeNextPath keeps a same-origin path with search and hash", () => {
  expect(safeNextPath("/course/x?tab=1", ORIGIN)).toBe("/course/x?tab=1");
  expect(safeNextPath("/course/x?tab=1#grades", ORIGIN)).toBe("/course/x?tab=1#grades");
});

test("safeNextPath rejects null, empty and relative input", () => {
  expect(safeNextPath(null, ORIGIN)).toBeNull();
  expect(safeNextPath("", ORIGIN)).toBeNull();
  expect(safeNextPath("course/x", ORIGIN)).toBeNull();
});
