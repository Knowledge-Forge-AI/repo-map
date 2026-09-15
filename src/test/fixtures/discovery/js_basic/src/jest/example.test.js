import { describe, expect, test } from "@jest/globals";
import { helper } from "../util.mjs";

describe("helper", () => {
  test("returns ok", () => {
    expect(helper()).toBe("ok");
  });
});
