import { describe, expect, it } from "vitest";
import { nearest, segments } from "./Chart";
import { ago, bytes, level, ms, pct, ticks, timeTicks } from "./format";
import { backupHealth } from "./pages/Backups";
import { buttonWord, warnings } from "./pages/Admin";
import type { Action, BackupRow, Point, State } from "./types";

describe("format", () => {
  it("shows units and n/a, never a silent zero", () => {
    expect(bytes(0)).toBe("0 B");
    expect(bytes(1536)).toBe("1.5 KB");
    expect(bytes(134820335616, 0)).toBe("126 GB");
    expect(bytes(null)).toBe("n/a");
    expect(pct(91.6)).toBe("92 %");
    expect(pct(undefined)).toBe("n/a");
    expect(ms(850)).toBe("850 ms");
    expect(ms(11804.1)).toBe("11.8 s");
    expect(ago(1000, 1045)).toBe("45 s ago");
    expect(ago("2026-10-21T03:07:07+00:00", Date.parse("2026-10-21T05:07:07Z") / 1000)).toBe("2.0 h ago");
    expect(level(92, 90, 95)).toBe("warn");
    expect(level(null, 90, 95)).toBe("none");
  });

  it("makes round axis ticks that cover the data", () => {
    expect(ticks(0, 100)).toEqual([0, 25, 50, 75, 100]);
    const t = ticks(0, 7.3e9);
    expect(t[0]).toBe(0);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(7.3e9);
    expect(t.length).toBeLessThanOrEqual(6);
    const hour = timeTicks(1_800_000_000, 1_800_003_600);
    expect(hour.length).toBeGreaterThanOrEqual(3);
    expect(hour.length).toBeLessThanOrEqual(8);
    expect(hour.every((x) => x >= 1_800_000_000 && x <= 1_800_003_600)).toBe(true);
  });
});

describe("chart helpers", () => {
  const p = (t: number, v: number | null): Point => [t, v, v, v];
  it("breaks a line where samples are missing for more than three steps", () => {
    const segs = segments([p(0, 1), p(5, 2), p(10, null), p(30, 3), p(35, 4)], 5);
    expect(segs.map((s) => s.map((x) => x[0]))).toEqual([[0, 5], [30, 35]]);
  });
  it("finds the nearest sample to the crosshair", () => {
    const pts = [p(0, 1), p(10, 2), p(20, 3)];
    expect(nearest(pts, 14)).toBe(1);
    expect(nearest(pts, 16)).toBe(2);
    expect(nearest([], 5)).toBe(-1);
  });
});

describe("backups and admin", () => {
  const now = Date.parse("2026-10-21T04:00:00Z") / 1000;
  const row: BackupRow = { set: "starai", where: "brain 2", schedule: "hourly", machine: "brain2",
    max_repository_bytes: 12884901888, last_success_utc: "2026-10-21T03:10:47+00:00" };
  it("flags a stale backup or an error newer than the last success", () => {
    expect(backupHealth(row, now)).toBe("ok");
    expect(backupHealth({ ...row, last_success_utc: "2026-10-21T00:10:47+00:00" }, now)).toBe("warn");
    expect(backupHealth({ ...row, last_error: { at: "2026-10-21T03:30:00+00:00", action: "retention", message: "x" } }, now)).toBe("warn");
    expect(backupHealth({ ...row, schedule: "daily", last_success_utc: "2026-10-20T09:00:00+00:00" }, now)).toBe("ok");
  });

  it("warns before restarting a brain that is answering", () => {
    const a: Action = { id: "brain1/restart:star-brain", machine: "brain1", machine_name: "Brain 1",
      verb: "restart:star-brain", group: "STAR services", label: "Restart star-brain", detail: "", danger: "high" };
    const state = { star: { models: [{ id: "star-fast", slots: { busy: 1, total: 2, ctx: 0 } }] }, backups: [],
      machines: [{ id: "brain1", name: "Brain 1", online: true }], dev_pc: null } as unknown as State;
    expect(warnings(a, state)[0]).toContain("1 of 2 slots busy");
    expect(buttonWord("backup-now:kb")).toBe("Back up");
    expect(buttonWord("ns-resume")).toBe("Resume");
  });
});
