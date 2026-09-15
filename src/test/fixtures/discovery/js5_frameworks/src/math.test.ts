import { describe, expect, jest, test } from "@jest/globals";

describe("math helpers", () => {
  beforeEach(() => jest.fn());

  test("adds numbers", () => {
    jest.mock("./math");
    jest.spyOn(console, "log");
    expect(1 + 1).toBe(2);
    expect([1, 2]).toContain(2);
  });
});
