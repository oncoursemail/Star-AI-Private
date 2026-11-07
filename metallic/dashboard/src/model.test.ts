import { describe, expect, it } from "vitest";
import { ago, byAttention, health, seconds, type CheckRun, type Project } from "./model";

const run = (verdict: "green" | "red", warn = false) =>
  ({ verdict, checks: [{ name: "x", status: warn ? "warn" : "pass" }] }) as unknown as CheckRun;

describe("model", () => {
  it("health reads only real data: no clone is offline, no run is none", () => {
    expect(health({ name: "a", connected: false })).toBe("offline");
    expect(health({ name: "a", connected: true, checks: [] })).toBe("none");
    expect(health({ name: "a", connected: true, checks: [run("red")] })).toBe("red");
    expect(health({ name: "a", connected: true, checks: [run("green", true)] })).toBe("warn");
  });

  it("red projects come first, otherwise the configured order is kept", () => {
    const ps: Project[] = [
      { name: "mc", connected: false }, { name: "star", connected: true, checks: [run("green")] },
      { name: "rb", connected: true, checks: [run("red")] }, { name: "px", connected: true, checks: [run("green")] },
    ];
    expect(byAttention(ps).map((p) => p.name)).toEqual(["rb", "star", "px", "mc"]);
  });

  it("formats ages and durations without inventing values", () => {
    const now = new Date("2026-10-20T12:00:00Z");
    expect(ago("2026-10-20T11:58:00Z", now)).toBe("2 min ago");
    expect(ago("not a date", now)).toBe("unknown age");
    expect(seconds(undefined)).toBe("not reached");
    expect(seconds(4.26)).toBe("4.3 s");
    expect(seconds(475)).toBe("7 min 55 s");
  });
});
