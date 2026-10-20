#!/usr/bin/env python3
"""Throwaway Windows VMs for STAR CI: one golden image, copy-on-write clones resumed from a saved memory state.

Runs as root inside the `winvm-host` LXD container (setup-host.sh), standard library only, plain QEMU/KVM.

    winvm.py fetch                        download the pinned Windows ISO + toolchain (tools.json), verify SHA-256
    winvm.py build-image --repo DIR       unattended install -> provision -> save the running state (golden.state)
    winvm.py start ID                     new qcow2 overlay on the golden disk, resume the saved state; prints ready time
    winvm.py run ID --task FILE [--timeout S]   hand the guest one task (e.g. a GitHub JIT runner), wait, destroy
    winvm.py destroy ID                   stop the VM and delete its overlay
    winvm.py serve                        controller: keep a warm pool while the brain is idle, start VMs on demand
    winvm.py gate                         pause all VMs during the owner's chat or another agent's quiet lock
    winvm.py guest-http ID                (internal) QEMU guestfwd handler: one HTTP request on stdin/stdout

Guest <-> host: the guest agent (guest/agent.ps1) polls http://<GUEST_IP>/task; QEMU forwards each connection to
`winvm.py guest-http ID`, which answers from the files in /run/winvm/ID. No SSH, no credentials stored in the image.
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import socket
import string
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("WINVM_ROOT", "/srv/winvm")
RUN = os.environ.get("WINVM_RUN", "/run/winvm")
GOLDEN = os.path.join(ROOT, "golden")
OVMF_CODE = "/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS = "/usr/share/OVMF/OVMF_VARS_4M.fd"
GUEST_IP = "10.0.2.100"  # star:allow QEMU user-mode net address inside the VM; forwarded to guest-http
DEFAULTS = {"cpus": 8, "mem_mb": 8192, "disk_gb": 64, "pool": 1, "max_vms": 2, "job_timeout": 3600}


# ----------------------------------------------------------------------------------------------- pure helpers (tested)
def qemu_args(vm_id, run_dir, disk, cpus, mem_mb, mode, isos=(), helper=None, disk_cache="none"):
    """QEMU command line. mode: 'install' (boot the ISOs), 'golden' (boot the golden disk) or 'resume' (-incoming).

    The device list must be identical between the golden run that saved the state and every resumed clone, so the
    ISOs are only attached in install mode and everything else is shared.
    """
    # disk_cache "none" (direct I/O): with "unsafe" the overlay writes piled up in the host page cache and their
    # write-back slowed star-fast 42-66 % even while the VM was frozen (measured 2026-10-20); "none": ~0 %.
    if mode not in ("install", "golden", "resume"):
        raise ValueError("mode must be install, golden or resume")
    helper = helper or [sys.executable, os.path.abspath(__file__)]
    hv = "hv-relaxed,hv-vapic,hv-spinlocks=0x1fff,hv-time,hv-vpindex,hv-synic,hv-stimer,hv-runtime,hv-frequencies"
    fwd = "guestfwd=tcp:%s:80-cmd:%s guest-http %s" % (GUEST_IP, " ".join(helper), vm_id)
    a = ["qemu-system-x86_64", "-name", "winvm-" + vm_id, "-machine", "q35,accel=kvm,smm=off",
         "-cpu", "host," + hv, "-smp", str(cpus), "-m", str(mem_mb),
         "-drive", "if=pflash,format=raw,readonly=on,file=" + OVMF_CODE,
         "-drive", "if=pflash,format=raw,file=" + os.path.join(run_dir, "vars.fd"),
         "-drive", "if=none,id=d0,format=qcow2,cache=%s,discard=unmap,aio=threads,file=%s" % (disk_cache, disk),
         "-device", "ide-hd,drive=d0,bus=ide.2,bootindex=1",  # AHCI: inbox driver and migratable (QEMU nvme is not)
         "-netdev", "user,id=n0," + fwd, "-device", "e1000e,netdev=n0,mac=52:54:00:57:49:4e",
         "-device", "qemu-xhci", "-device", "usb-tablet", "-vga", "std", "-display", "none",
         "-rtc", "base=utc", "-qmp", "unix:%s,server=on,wait=off" % os.path.join(run_dir, "qmp.sock"),
         "-qmp", "unix:%s,server=on,wait=off" % os.path.join(run_dir, "gate.sock"),
         "-qmp", "unix:%s,server=on,wait=off" % os.path.join(run_dir, "ctl.sock"),
         "-pidfile", os.path.join(run_dir, "qemu.pid"), "-daemonize"]
    if mode == "install":
        for i, iso in enumerate(isos):
            a += ["-drive", "if=none,id=cd%d,media=cdrom,readonly=on,file=%s" % (i, iso),
                  "-device", "ide-cd,drive=cd%d,bus=ide.%d%s" % (i, i, ",bootindex=0" if i == 0 else "")]
    if mode == "resume":
        a += ["-incoming", "defer"]
    return a


def parse_request(raw):
    """(path, {query}) from the first line of an HTTP request."""
    line = raw.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split()
    if len(parts) < 2:
        return None, {}
    path, _, q = parts[1].partition("?")
    query = {}
    for kv in q.split("&"):
        if kv:
            k, _, v = kv.partition("=")
            query[k] = v
    return path, query


def guest_reply(run_dir, path, query, now):
    """Answer one guest request from the files in run_dir. Returns the JSON-able reply."""
    if path == "/task":
        seen = os.path.join(run_dir, "first_poll")
        if not os.path.exists(seen):
            with open(seen, "w") as f:
                f.write("%.3f" % now)
        task, served = os.path.join(run_dir, "task.json"), os.path.join(run_dir, "task.served")
        if os.path.exists(task) and not os.path.exists(served):
            with open(task) as f:
                body = json.load(f)
            os.replace(task, served)
            body["epoch"] = int(now)
            return body
        return {"kind": "wait", "epoch": int(now)}
    if path == "/done":
        with open(os.path.join(run_dir, "done"), "w") as f:
            f.write(query.get("rc", "?"))
        return {"ok": True}
    if path == "/log":
        with open(os.path.join(run_dir, "guest.log"), "a") as f:
            f.write("%.0f %s\n" % (now, urllib.parse.unquote(query.get("m", ""))[:300]))
        return {"ok": True}
    return {"error": "unknown path"}


def want_pool(brain_busy, brain_idle_s, running, ready, demand, cfg):
    """How many VMs to start now (>= 0).

    Demand (queued jobs for our label) is always served up to max_vms: a waiting job matters more than a few
    percent of background speed, and a job never waits behind the owner's chat for long. The warm pool (ready VMs
    with no job yet) is only kept while the brain has been idle for 60 s, and is not refilled while it is busy.
    """
    room = max(0, cfg["max_vms"] - running)
    need = max(0, demand - ready)
    if not brain_busy and brain_idle_s >= 60:
        need = max(need, cfg["pool"] - ready)
    return min(room, need)


def guest_file(run_dir, path):
    """Path of a host file offered to the guest as /file/NAME (only plain names inside run_dir/files), else None."""
    if not path or not path.startswith("/file/"):
        return None
    name = path[len("/file/"):]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    p = os.path.join(run_dir, "files", name)
    return p if os.path.isfile(p) else None


def gate_want(chat, quiet_s, hold=1.0):
    """'stop' while the owner's chat is served and for `hold` s after it, else 'cont'."""
    return "stop" if chat or quiet_s < hold else "cont"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def render_unattend(template, password, computer="STARCI"):
    if any(c in password for c in "<>&\"'"):
        raise ValueError("password must not need XML escaping")
    return template.replace("@@PASSWORD@@", password).replace("@@COMPUTER@@", computer)


# ------------------------------------------------------------------------------------------------------- QMP / qemu
class QMP:
    def __init__(self, path, timeout=30):
        deadline = time.time() + timeout
        while True:
            try:
                self.s = socket.socket(socket.AF_UNIX)
                self.s.settimeout(timeout)
                self.s.connect(path)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        self.f = self.s.makefile("rwb")
        self._read()
        self.cmd("qmp_capabilities")
        self.s.settimeout(None)  # later commands wait, e.g. while the gate has the VM frozen

    def _read(self):
        while True:
            m = json.loads(self.f.readline())
            if "event" not in m:
                return m

    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}).encode() + b"\n")
        self.f.flush()
        r = self._read()
        if "error" in r:
            raise RuntimeError("%s: %s" % (name, r["error"]))
        return r.get("return")


def run_dir(vm_id):
    return os.path.join(RUN, vm_id)


def load_cfg():
    cfg = dict(DEFAULTS)
    p = os.path.join(ROOT, "winvm.json")
    if os.path.exists(p):
        with open(p) as f:
            cfg.update(json.load(f))
    return cfg


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def launch(vm_id, disk, mode, cfg, isos=(), vars_src=None):
    d = run_dir(vm_id)
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(vars_src or os.path.join(GOLDEN, "vars.fd"), os.path.join(d, "vars.fd"))
    subprocess.run(qemu_args(vm_id, d, disk, cfg["cpus"], cfg["mem_mb"], mode, isos,
                              disk_cache=cfg.get("disk_cache", "none")), check=True)
    return QMP(os.path.join(d, "qmp.sock"))


def destroy(vm_id):
    d = run_dir(vm_id)
    try:
        with open(os.path.join(d, "qemu.pid")) as f:
            pid = int(f.read())
        os.kill(pid, 9)
        for _ in range(100):
            os.kill(pid, 0)
            time.sleep(0.05)
    except (OSError, ValueError):
        pass
    shutil.rmtree(d, ignore_errors=True)
    for p in (os.path.join(ROOT, "clones", vm_id + ".qcow2"),):
        if os.path.exists(p):
            os.unlink(p)


def wait_file(path, timeout, poll=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(poll)
    return False


# --------------------------------------------------------------------------------------------------------- commands
def cmd_fetch(a):
    spec = json.load(open(os.path.join(HERE, "tools.json")))
    items = [spec["windows_iso"]] + spec["tools"]
    dest = os.path.join(ROOT, "iso")
    os.makedirs(os.path.join(dest, "tools"), exist_ok=True)
    for it in items:
        p = os.path.join(dest, it["name"]) if it is spec["windows_iso"] else os.path.join(dest, "tools", it["name"])
        if not (os.path.exists(p) and sha256_file(p) == it["sha256"]):
            log("download " + it["name"])
            subprocess.run(["curl", "-sSfL", "--retry", "3", "-C", "-", "-o", p, it["url"]], check=True)
        got = sha256_file(p)
        if got != it["sha256"]:
            os.unlink(p)
            sys.exit("SHA-256 mismatch for %s: got %s" % (it["name"], got))
        log("ok %s %s" % (it["name"], got[:16]))


def make_config_iso(repo, out, password):
    """Small ISO (label WINVMCFG) with the answer file, provisioning scripts, verified tools and repo dep lists."""
    stage = out + ".d"
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, "repo", "frontend"))
    tpl = open(os.path.join(HERE, "guest", "autounattend.xml")).read()
    with open(os.path.join(stage, "autounattend.xml"), "w") as f:
        f.write(render_unattend(tpl, password))
    for n in ("provision.ps1", "agent.ps1"):
        shutil.copy(os.path.join(HERE, "guest", n), stage)
    shutil.copytree(os.path.join(ROOT, "iso", "tools"), os.path.join(stage, "tools"))
    for n in os.listdir(repo):
        if n.startswith("requirements") and n.endswith(".txt"):
            shutil.copy(os.path.join(repo, n), os.path.join(stage, "repo"))
    for n in ("package.json", "package-lock.json"):
        if os.path.exists(os.path.join(repo, "frontend", n)):
            shutil.copy(os.path.join(repo, "frontend", n), os.path.join(stage, "repo", "frontend"))
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-J", "-joliet-long", "-r", "-V", "WINVMCFG", "-o", out,
                    stage], check=True)
    shutil.rmtree(stage)


def cmd_build_image(a):
    cfg = load_cfg()
    spec = json.load(open(os.path.join(HERE, "tools.json")))
    os.makedirs(GOLDEN, exist_ok=True)
    disk, state = os.path.join(GOLDEN, "golden.qcow2"), os.path.join(GOLDEN, "golden.state")
    vm_id = "golden"
    t0 = time.time()
    if a.resume_install:  # an earlier build-image process died; the install VM is still running
        q = None
    else:
        if not a.repo:
            sys.exit("--repo is required for a new image")
        for p in (disk, state):
            if os.path.exists(p):
                os.chmod(p, 0o644)
                os.unlink(p)
        pw_file = os.path.join(ROOT, "guest-password")  # local throwaway account of the image; 0600, never printed
        if not os.path.exists(pw_file):
            alphabet = string.ascii_letters + string.digits
            with open(os.open(pw_file, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
                f.write("W1n-" + "".join(random.SystemRandom().choice(alphabet) for _ in range(20)))
        cfg_iso = os.path.join(ROOT, "iso", "winvmcfg.iso")
        make_config_iso(a.repo, cfg_iso, open(pw_file).read().strip())
        shutil.copyfile(OVMF_VARS, os.path.join(GOLDEN, "vars.fd"))
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", disk, "%dG" % cfg["disk_gb"]], check=True)
        destroy(vm_id)
        q = launch(vm_id, disk, "install", cfg, isos=(os.path.join(ROOT, "iso", spec["windows_iso"]["name"]), cfg_iso))
        sent = 0
        while sent < 30:  # "Press any key to boot from CD or DVD": 30 s of key presses while the VM really runs
            if q.cmd("query-status").get("status") == "running":  # the chat/lock gate may hold it paused
                q.cmd("send-key", keys=[{"type": "qcode", "data": "ret"}])
                sent += 1
            time.sleep(1)
    d = run_dir(vm_id)
    pid = int(open(os.path.join(d, "qemu.pid")).read())
    log("installing; waiting for setup + provisioning to power the VM off (up to %d min)" % a.timeout_min)
    deadline = time.time() + a.timeout_min * 60
    while os.path.exists("/proc/%d" % pid):
        if time.time() > deadline:
            sys.exit("install did not finish; look at it with: winvm.py screen golden FILE.ppm")
        time.sleep(5)
    # Boot once more without the ISOs (the device set must match the clones), let the agent come up, save.
    shutil.copyfile(os.path.join(d, "vars.fd"), os.path.join(GOLDEN, "vars.fd"))  # keeps Windows' boot entry
    shutil.rmtree(d, ignore_errors=True)
    log("installed after %.0f min; booting the golden VM" % ((time.time() - t0) / 60))
    q = launch(vm_id, disk, "golden", cfg)
    if not wait_file(os.path.join(d, "first_poll"), 1800, poll=2):
        q.cmd("screendump", filename=os.path.join(ROOT, "golden-timeout.ppm"))
        sys.exit("guest agent never polled; screen saved to golden-timeout.ppm")
    log("agent up after %.0f s total; settling %d s before saving the state" % (time.time() - t0, a.settle))
    time.sleep(a.settle)
    save_state(q, state)
    destroy(vm_id)
    os.chmod(disk, 0o444)
    os.chmod(state, 0o444)
    log("golden ready: %s (%.1f GB), %s (%.1f GB), total %.0f min" % (
        disk, os.path.getsize(disk) / 1e9, state, os.path.getsize(state) / 1e9, (time.time() - t0) / 60))


def save_state(q, state):
    q.cmd("stop")
    q.cmd("migrate", uri="exec:cat > " + state)
    while True:
        s = q.cmd("query-migrate").get("status")
        if s == "completed":
            return
        if s in ("failed", "cancelled"):
            raise RuntimeError("state save " + s)
        time.sleep(0.2)


def cmd_save_state(a):
    """Save the running state of an already booted golden VM (if build-image was interrupted after the install)."""
    q = QMP(os.path.join(run_dir("golden"), "qmp.sock"))
    state = os.path.join(GOLDEN, "golden.state")
    save_state(q, state)
    destroy("golden")
    os.chmod(os.path.join(GOLDEN, "golden.qcow2"), 0o444)
    os.chmod(state, 0o444)
    log("saved " + state)


def start(vm_id, cfg):
    """Overlay + resume. Returns seconds until the guest agent polled (VM ready for a task)."""
    t0 = time.time()
    destroy(vm_id)
    os.makedirs(os.path.join(ROOT, "clones"), exist_ok=True)
    disk = os.path.join(ROOT, "clones", vm_id + ".qcow2")
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b",
                    os.path.join(GOLDEN, "golden.qcow2"), disk], check=True)
    q = launch(vm_id, disk, "resume", cfg)
    q.cmd("migrate-incoming", uri="exec:cat " + os.path.join(GOLDEN, "golden.state"))
    while True:  # the state was saved from a stopped VM, so it arrives paused: wait for the load, then cont
        if time.time() - t0 > 600:
            raise RuntimeError("state load did not finish within 600 s")
        m = q.cmd("query-migrate").get("status")  # blocks while the gate has the VM frozen
        if m == "completed":
            break
        if m in ("failed", "cancelled"):
            raise RuntimeError("state load " + m)
        time.sleep(0.05)
    if q.cmd("query-status").get("status") != "running":
        q.cmd("cont")
    t_resume = time.time() - t0
    limit = cfg.get("agent_timeout", 600)  # generous: the gate may hold the VM frozen
    if not wait_file(os.path.join(run_dir(vm_id), "first_poll"), limit, poll=0.05):
        raise RuntimeError("guest agent did not poll within %d s of resume" % limit)
    ready = time.time() - t0
    with open(os.path.join(run_dir(vm_id), "ready"), "w") as f:
        f.write("%.2f %.2f" % (t_resume, ready))
    return t_resume, ready


def cmd_start(a):
    r, ready = start(a.id, load_cfg())
    print("%s resumed in %.1f s, agent ready in %.1f s" % (a.id, r, ready))


def run_task(vm_id, task, timeout):
    d = run_dir(vm_id)
    tmp = os.path.join(d, "task.tmp")
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(task, f)
    os.replace(tmp, os.path.join(d, "task.json"))
    t0 = time.time()
    ok = wait_file(os.path.join(d, "done"), timeout, poll=1)
    rc = open(os.path.join(d, "done")).read() if ok else "timeout"
    return rc, time.time() - t0


def cmd_run(a):
    task = json.load(open(a.task))
    rc, el = run_task(a.id, task, a.timeout)
    print("%s task rc=%s after %.0f s" % (a.id, rc, el))
    if not a.keep:
        destroy(a.id)


def cmd_screen(a):
    """Save the VM screen as PPM (debugging an install): winvm.py screen ID FILE."""
    q = QMP(os.path.join(run_dir(a.id), "ctl.sock"))
    q.cmd("screendump", filename=os.path.abspath(a.file))
    print("status %s, screen saved to %s" % (q.cmd("query-status").get("status"), a.file))


def cmd_destroy(a):
    destroy(a.id)


def cmd_guest_http(a):
    raw = b""
    while b"\r\n\r\n" not in raw and len(raw) < 65536:
        b = sys.stdin.buffer.read1(4096) if hasattr(sys.stdin.buffer, "read1") else sys.stdin.buffer.read(4096)
        if not b:
            break
        raw += b
    path, query = parse_request(raw)
    f = guest_file(run_dir(a.id), path)
    if f:  # host-provided input files (e.g. a built Setup for the installer test), streamed
        sys.stdout.buffer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nConnection: close\r\n"
                                b"Content-Length: %d\r\n\r\n" % os.path.getsize(f))
        with open(f, "rb") as src:
            shutil.copyfileobj(src, sys.stdout.buffer, 1 << 20)
        sys.stdout.buffer.flush()
        return
    body = json.dumps(guest_reply(run_dir(a.id), path, query, time.time())).encode()
    sys.stdout.buffer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
                            b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()


# ------------------------------------------------------------------------------------------------- runner tokens
def github_jit(repo, token, name, labels):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/actions/runners/generate-jitconfig" % repo,
        data=json.dumps({"name": name, "runner_group_id": 1, "labels": labels, "work_folder": "_work"}).encode(),
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["encoded_jit_config"]


def github_demand(repo, token, label):
    """Queued jobs whose labels include ours."""
    h = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    n = 0
    url = "https://api.github.com/repos/%s/actions/runs?status=queued&per_page=20" % repo
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        runs = json.loads(r.read()).get("workflow_runs", [])
    for run in runs:
        with urllib.request.urlopen(urllib.request.Request(run["jobs_url"], headers=h), timeout=30) as r:
            for j in json.loads(r.read()).get("jobs", []):
                if j.get("status") == "queued" and label in j.get("labels", []):
                    n += 1
    return n


def brain_state(path):
    """(busy, idle_seconds) from the file the brain watcher writes; missing or stale (>10 s) counts as busy."""
    try:
        st = os.stat(path)
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return True, 0.0
    if time.time() - st.st_mtime > 10:
        return True, 0.0
    return bool(d.get("busy")), float(d.get("idle_s", 0))


def cmd_serve(a):
    """GitHub ephemeral runners: each VM gets one JIT runner (one job), then it is destroyed."""
    cfg = load_cfg()
    token = open(cfg.get("github_token_file", "/etc/winvm/github-token")).read().strip()
    repo, label = cfg.get("github_repo", "oncoursemail/Star-AI-Private"), "star-win-vm"
    labels = ["self-hosted", "windows", "X64", label]
    vms = {}  # id -> {"state": "ready"|"job", "proc": Popen}
    seq = 0
    last_demand, demand = 0.0, 0
    while True:
        for vid, v in list(vms.items()):
            if v["state"] == "job" and v["proc"].poll() is not None:
                log("%s finished: %s" % (vid, v["proc"].returncode))
                del vms[vid]
        if time.time() - last_demand > 20:
            try:
                demand = github_demand(repo, token, label)
            except Exception as e:  # network hiccup: keep the last value
                log("demand check failed: %s" % e)
            last_demand = time.time()
        busy, idle_s = brain_state(cfg.get("brain_state_file", "/srv/winvm/shared/brain-state.json"))
        ready = sum(1 for v in vms.values() if v["state"] == "ready")
        for _ in range(want_pool(busy, idle_s, len(vms), ready, demand, cfg)):
            seq += 1
            vid = "w%d-%d" % (os.getpid() % 1000, seq)
            try:
                r, rd = start(vid, cfg)
                jit = github_jit(repo, token, "star-win-vm-" + vid, labels)
                with open(os.path.join(run_dir(vid), "task.json"), "w") as f:
                    json.dump({"kind": "github", "jit": jit}, f)
                log("%s ready in %.1f s (resume %.1f s); runner offered" % (vid, rd, r))
                p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "wait-done", vid,
                                      "--timeout", str(cfg["job_timeout"])])
                vms[vid] = {"state": "job", "proc": p}
            except Exception as e:
                log("%s failed to start: %s" % (vid, e))
                destroy(vid)
        time.sleep(2)


def must_yield(path, own_lock_prefix="claude-winvm-run"):
    """True while the owner's chat is served or any quiet lock is held, except by holder `winvm-run` (a timing
    run of these VMs). A missing or stale (>10 s) state file also yields: fail safe for chat."""
    try:
        if time.time() - os.stat(path).st_mtime > 10:
            return True
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return True
    lock = d.get("lock") or ""
    return bool(d.get("chat")) or (lock != "" and not lock.startswith(own_lock_prefix))


def cmd_gate(a):
    """Freeze every VM (SIGSTOP on its QEMU) while the brain serves chat or another agent holds the quiet lock;
    SIGCONT after. Signals instead of QMP stop/cont: a QMP stop during early firmware hung QEMU's monitor (seen
    2026-10-20), and a frozen process needs no cooperation. Builds just take longer."""
    cfg = load_cfg()
    path = cfg.get("brain_state_file", "/srv/winvm/shared/brain-state.json")
    quiet_since, applied = time.time(), {}
    while True:
        chat, now = must_yield(path), time.time()
        if chat:
            quiet_since = now
        want = gate_want(chat, now - quiet_since)
        vids = os.listdir(RUN) if os.path.isdir(RUN) else []
        for vid in vids:
            if applied.get(vid) == want:
                continue
            try:
                with open(os.path.join(RUN, vid, "qemu.pid")) as f:
                    os.kill(int(f.read()), signal.SIGSTOP if want == "stop" else signal.SIGCONT)
                applied[vid] = want
                log("gate: %s %s" % (vid, want))
            except (OSError, ValueError):
                pass  # VM gone or not started yet: retry next round
        for vid in set(applied) - set(vids):
            applied.pop(vid, None)
        time.sleep(0.2)


def cmd_wait_done(a):
    ok = wait_file(os.path.join(run_dir(a.id), "done"), a.timeout, poll=1)
    destroy(a.id)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(fn=cmd_fetch)
    p = sub.add_parser("build-image")
    p.add_argument("--repo", help="checkout with requirements*.txt and frontend/package.json (new image)")
    p.add_argument("--timeout-min", type=int, default=600, help="wall clock; the gate freezes the VM during locks")
    p.add_argument("--resume-install", action="store_true", help="re-attach to a running install VM")
    p.add_argument("--settle", type=int, default=90, help="seconds to let the guest go idle before saving")
    p.set_defaults(fn=cmd_build_image)
    sub.add_parser("save-state").set_defaults(fn=cmd_save_state)
    for n, fn in (("start", cmd_start), ("destroy", cmd_destroy), ("guest-http", cmd_guest_http)):
        p = sub.add_parser(n)
        p.add_argument("id")
        p.set_defaults(fn=fn)
    p = sub.add_parser("screen")
    p.add_argument("id")
    p.add_argument("file")
    p.set_defaults(fn=cmd_screen)
    p = sub.add_parser("run")
    p.add_argument("id")
    p.add_argument("--task", required=True)
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--keep", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("wait-done")
    p.add_argument("id")
    p.add_argument("--timeout", type=int, default=3600)
    p.set_defaults(fn=cmd_wait_done)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    sub.add_parser("gate").set_defaults(fn=cmd_gate)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
