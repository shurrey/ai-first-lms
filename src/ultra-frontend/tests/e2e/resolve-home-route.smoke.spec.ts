import { expect, test } from "@playwright/test";
import { resolveHomeRoute } from "../../lib/api";

const ORIGIN = "http://localhost:3110";

for (const home of ["/course/..//evil.example", "/course/\t/evil.example", "/account/%09/evil.example",
                    "/course/../../evil", "//course/x", "/elsewhere", null, ""]) {
  test(`resolveHomeRoute falls back to / for ${JSON.stringify(home)}`, () => {
    expect(resolveHomeRoute(home, ORIGIN)).toBe("/");
  });
}

test("resolveHomeRoute keeps a known same-origin home", () => {
  expect(resolveHomeRoute("/course/cs101", ORIGIN)).toBe("/course/cs101");
  expect(resolveHomeRoute("/account/password", ORIGIN)).toBe("/account/password");
});
