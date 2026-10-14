#!/usr/bin/env python3
"""The homa-lab portal: the four hosts and sw1 live (Homa's counters on each host, sw1's eight priority queues per port),
the measurements and the Robot suites as runs, and the last test report.

Runs go through the shared run engine (labportal): one at a time, streamed, kept in runs/<id>.json, resumable:

    verify     ./lab.sh verify: kernel + module, sw1 policy, jumbo pings v4/v6, a Homa round trip between every pair
    test       the Robot suites (all, or one), results in tests/results_<date>_<time>/ (results/latest links the newest)
    bench      one measurement from tools/homalab.py: matrix | compare | incast | loss | capture; its JSON is kept in the run

sw1's queueing mode and Homa's resend timers can be switched from the page (not while a run is going: the suites and
benchmarks set them themselves). Sign-in is the Lab Hub's (labportal.gate). Start with ./lab.sh webapp (port 8108)."""
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from labportal import RunBase, RunRegistry, install_runs_api, gate, run_metrics, exposition, metrics_generated, metric_line as line
from pydantic import BaseModel, Field

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "tools"))
import homalab as H  # noqa: E402

NAME = "homa-lab"
PORT = int(os.environ.get("WEBAPP_PORT", "8108"))
RUNS_DIR = Path(__file__).resolve().parent / "runs"; RUNS_DIR.mkdir(exist_ok=True)
STATIC = Path(__file__).resolve().parent / "static"
VERSION = (LAB / "VERSION").read_text().strip()
HOSTS = ["h1", "h2", "h3", "h4"]
SUITES = sorted(p.stem for p in (LAB / "tests" / "suites").glob("*.robot"))
BENCH = {"matrix": "Homa round trips between every pair, v4/v6, 100 B and 100 KB (~1 min)",
         "compare": "Homa vs TCP on the W3 workload at 0.3 Gbit/s (~30 s)",
         "incast": "h2, h3 bulk into h1 while h4 probes; sw1 priority queues vs FIFO; Homa and TCP (~1.5 min)",
         "loss": "1 in 50 packets dropped towards h1: 300 RPCs of 20 KB must all complete (~10 s)",
         "capture": "decoded capture on sw1's port to h1: packet types and priorities on the wire (~15 s)"}
TIMERS = {"default": {"resend_ticks": 5, "resend_interval": 5, "timeout_ticks": 100},
          "x10": {"resend_ticks": 50, "resend_interval": 20, "timeout_ticks": 1000}}
COUNTERS = ("packets_sent_DATA", "packets_rcvd_DATA", "packets_sent_GRANT", "packets_sent_RESEND", "packets_rcvd_RESEND", "resent_packets",
            "packets_sent_BUSY", "rpc_timeouts", "client_requests_done", "server_requests_done", "packet_discards",
            *(f"priority{i}_packets" for i in range(8)))

app = FastAPI(title="homa-lab portal API", version="1.0", docs_url="/docs",
              description="Homa kernel module lab: hosts, sw1's queues, measurements and tests. UI: [/](/)")
gate.install(app, open_paths={"/metrics", "/api/sd"}, open_from=["10.0.0.0/24", "192.168.122.0/24"])
registry = RunRegistry(RUNS_DIR)


def lab_sh(*args, timeout=60):
    env = {k: v for k, v in os.environ.items() if k != "FORCE_COLOR"}
    r = subprocess.run([str(LAB / "lab.sh"), *args], capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout


def nodes():
    """lab.sh status's node table (it stops at the first blank line)."""
    _, out = lab_sh("status", timeout=30); rows = []
    for l in out.splitlines()[1:]:
        if not l.strip(): break
        c = l.split()
        if len(c) < 5: continue
        st, rest = ("shut off", c[4:]) if c[2] == "shut" else (c[2], c[3:])
        rows.append({"node": c[0], "role": c[1], "state": st, "mgmt": rest[0], "data": rest[1], "data6": rest[2], "vm": rest[-1]})
    return rows


HOST_CMD = ("uname -r; lsmod | grep -c '^homa ' || true; systemctl is-active homa-prio || true; "
            "sysctl -n net.homa.link_mbps net.homa.resend_ticks net.homa.resend_interval net.homa.timeout_ticks 2>/dev/null || echo; "
            "echo ---; cat /proc/net/homa_metrics 2>/dev/null")


def host_state(h):
    try:
        _, out = H.run(h, HOST_CMD, timeout=8)
        head, _, metrics = out.partition("---\n"); hl = head.split("\n")
        m = {}
        for l in metrics.splitlines():
            p = l.split()
            if len(p) >= 2 and p[1].lstrip("-").isdigit() and p[0] not in ("core", "time_cycles", "cpu_khz"): m[p[0]] = m.get(p[0], 0) + int(p[1])
        ints = [int(x) if x.strip().lstrip("-").isdigit() else None for x in hl[3:7]] + [None] * 4
        return {"up": True, "kernel": hl[0], "homa": hl[1].strip() == "1", "homa_prio": hl[2].strip(),
                "link_mbps": ints[0], "timers": {"resend_ticks": ints[1], "resend_interval": ints[2], "timeout_ticks": ints[3]},
                "counters": {k: m.get(k, 0) for k in COUNTERS}}
    except Exception as e:   # noqa: BLE001
        return {"up": False, "error": str(e)[:200]}


_cache = {"t": 0, "v": None}; _lock = threading.Lock()


def live():
    """Every host's state and counters plus sw1's queue counters, gathered in parallel; cached for 1.5 s (several viewers)."""
    with _lock:
        if _cache["v"] and time.time() - _cache["t"] < 1.5: return _cache["v"]
        with ThreadPoolExecutor(5) as ex:
            hs = dict(zip(HOSTS, ex.map(host_state, HOSTS))); sw = ex.submit(H.qos_stats)
            try: sw = sw.result(timeout=10)
            except Exception as e: sw = {"error": str(e)[:200]}   # noqa: BLE001
        _cache.update(t=time.time(), v={"at": time.time(), "hosts": hs, "sw1": sw})
        return _cache["v"]


def tests_summary():
    latest = LAB / "results" / "latest" / "output.xml"
    if not latest.exists(): return None
    try:
        from labportal.runs import parse_robot
        r = parse_robot(latest); r["when"] = latest.resolve().parent.name; return r
    except Exception: return None   # noqa: BLE001


def latest_bench():
    out = {}
    for r in registry.list(limit=200):
        k = (r.get("options") or {}).get("kind")
        if r["mode"] == "bench" and k and k not in out and r["status"] == "success" and r.get("result"): out[k] = {"id": r["id"], "finished": r["finished"], "result": r["result"]}
    return out


def busy(): return registry.busy()


# ---- API -------------------------------------------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index(): return FileResponse(STATIC / "index.html")


@app.get("/api/lab", tags=["lab"], summary="What the lab is: nodes, links, kernel and module pins, the benchmarks and suites")
def lab():
    inv = H.inventory()
    return {"name": NAME, "version": VERSION, "inventory": {k: v for k, v in inv.items() if k != "by_name"}, "bench": BENCH, "suites": SUITES,
            "timers": TIMERS}


@app.get("/api/state", tags=["lab"], summary="Nodes, every host's Homa state and counters, sw1's queues, the last tests, the last result of each benchmark")
def state():
    ns = nodes(); up = any(n["state"] == "running" for n in ns)
    return {"at": time.time(), "nodes": ns, "up": up, "live": live() if up else None, "tests": tests_summary(), "bench": latest_bench(), "busy": busy()}


@app.get("/api/live", tags=["lab"], summary="Just the live part: hosts' counters and sw1's queues (poll this for rates)")
def live_api(): return live()


@app.get("/report/{name}", tags=["tests"], summary="The last Robot run's report.html / log.html")
def report(name: str):
    if name not in ("report.html", "log.html"): raise HTTPException(404)
    p = LAB / "results" / "latest" / name
    if not p.exists(): raise HTTPException(404, "no test run yet")
    return FileResponse(p)


class Qos(BaseModel):
    mode: str = Field(..., description="prio | fifo | off")


@app.post("/api/qos", tags=["control"], summary="sw1's egress policy on every host port: 8 strict priority queues, one FIFO, or no shaping")
def set_qos(q: Qos):
    if q.mode not in ("prio", "fifo", "off"): raise HTTPException(422, "mode: prio, fifo or off")
    if busy(): raise HTTPException(409, "a run is going; it sets sw1 itself")
    out = H.qos_apply(q.mode); _cache["t"] = 0
    return {"ok": True, "mode": q.mode, "output": out[-400:]}


class Timers(BaseModel):
    preset: str = Field(..., description="default (resend_ticks 5) | x10 (resend_ticks 50, resend_interval 20, timeout_ticks 1000)")


@app.post("/api/timers", tags=["control"], summary="Homa's resend timers on every host: the module's defaults, or ×10 (the lab's timer finding)")
def set_timers(t: Timers):
    if t.preset not in TIMERS: raise HTTPException(422, "preset: default or x10")
    if busy(): raise HTTPException(409, "a run is going; it sets the timers itself")
    kv = " ".join(f"net.homa.{k}={v}" for k, v in TIMERS[t.preset].items())
    r = H.parallel({h: (H.run, h, f"sudo sysctl -qw {kv}") for h in HOSTS}); _cache["t"] = 0
    return {"ok": all(x[0] == 0 for x in r.values()), "preset": t.preset}


# ---- runs ------------------------------------------------------------------------------------------------------------
class RunRequest(BaseModel):
    mode: str = Field(..., description="verify | test | bench")
    options: dict = Field(default_factory=dict, description="test: {suite: <name>} (default all); bench: {kind: matrix|compare|incast|loss|capture}")


class Run(RunBase):
    LAB = NAME
    EXTRA = {"result": "result"}
    STEP_TITLES = {"verify": "Verify: kernel + module, sw1 policy, jumbo pings v4/v6, Homa round trips between every pair",
                   "test": "Robot Framework suites", "bench": "Measurement (tools/homalab.py)"}

    def __init__(self, mode, options=None, resume_of=None):
        self.result = None
        super().__init__(mode, options, resume_of, runs_dir=RUNS_DIR, cwd=LAB)
        if mode == "bench": self.steps[0]["title"] = f"{self.options['kind']}: {BENCH[self.options['kind']]}"
        if mode == "test" and self.options.get("suite"): self.steps[0]["title"] = f"Robot suite {self.options['suite']}"

    def plan(self): return [self.mode]

    def do_verify(self, s):
        rc = self.sh([LAB / "lab.sh", "verify"], check=False)
        pairs = next((l["line"].strip() for l in reversed(self.log) if "pairs ok" in l["line"]), "")
        homa = next((l["line"].strip() for l in reversed(self.log) if "RTT tests ok" in l["line"]), "")
        s["summary"] = "; ".join(x for x in (f"pings {pairs}" if pairs else "", homa) if x)
        if rc: raise RuntimeError(s["summary"] or "verify failed")

    def do_test(self, s):
        suite = self.options.get("suite")
        args = [f"suites/{suite}.robot"] if suite else []
        self.record_tests(LAB / "results", s, self.sh([LAB / "tests" / "run.sh", *args], check=False))

    def do_bench(self, s):
        kind = self.options["kind"]; out = RUNS_DIR / f"{self.id}.bench.json"
        rc = self.sh(["bash", "-c", f'python3 "{LAB}/tools/homalab.py" {kind} > "{out}"'], check=False)
        try: self.result = json.loads(out.read_text()); out.unlink()
        except Exception: self.result = None   # noqa: BLE001
        s["summary"] = bench_summary(kind, self.result) if self.result else ""
        if rc: raise RuntimeError(f"{kind} failed (rc={rc})" + (f": {s['summary']}" if s["summary"] else ""))

    def after(self): _cache["t"] = 0


def bench_summary(kind, r):
    try:
        if kind == "matrix": return f"{r['passed']}/{r['total']} round trips ok"
        if kind == "compare":
            return "; ".join(f"{p} p50 {r[p]['rtt_us']['all']['p50']} µs p99 {r[p]['rtt_us']['all']['p99']} µs" for p in ("homa", "tcp") if "all" in r[p]["rtt_us"])
        if kind == "incast":
            return "; ".join(f"{x['mode']}/{x['protocol']} probe p50 {x['probe_loaded'].get('p50')} µs" for x in r["runs"])
        if kind == "loss":
            m = r["metrics"]; return f"{r['rtt']['count']} RPCs {'all ok' if r['rtt']['ok'] else 'FAILED'}, p50 {r['rtt'].get('p50')} µs; RESENDs {sum(v['packets_sent_RESEND'] for v in m.values())}, timeouts {sum(v['rpc_timeouts'] for v in m.values())}"
        if kind == "capture": return f"{r['packets']} packets: " + ", ".join(f"{k} {v}" for k, v in sorted(r["types"].items(), key=lambda kv: -kv[1]))
    except Exception: pass   # noqa: BLE001
    return ""


install_runs_api(app, registry, resume_factory=lambda d: Run(d["mode"], d.get("options"), resume_of=d))


@app.post("/api/runs", tags=["runs"], summary="Start a run: verify | test (all or one suite) | bench (one measurement)")
def start_run(req: RunRequest):
    if req.mode not in ("verify", "test", "bench"): raise HTTPException(422, "mode: verify, test or bench")
    if req.mode == "bench" and req.options.get("kind") not in BENCH: raise HTTPException(422, f"options.kind: one of {', '.join(BENCH)}")
    if req.mode == "test" and req.options.get("suite") not in (None, "", *SUITES): raise HTTPException(422, f"options.suite: one of {', '.join(SUITES)}")
    if not all(n["state"] == "running" for n in nodes()): raise HTTPException(409, "the lab is not (fully) running: power it on from the Lab Hub")
    return registry.start(Run(req.mode, req.options))


# ---- monitoring ------------------------------------------------------------------------------------------------------
@app.get("/api/sd", tags=["monitoring"], summary="Prometheus HTTP service discovery: this portal")
def prometheus_sd():
    return [{"targets": [f"10.0.0.1:{PORT}"], "labels": {"lab": NAME, "job": "portal", "role": "portal"}}]


@app.get("/metrics", tags=["monitoring"], summary="Prometheus metrics: nodes, Homa's counters per host, sw1's queues, runs", response_class=PlainTextResponse)
def metrics():
    lab = {"lab": NAME}; out = []
    def gauge(name, help_, typ="gauge"): out.extend([f"# HELP {name} {help_}", f"# TYPE {name} {typ}"])
    ns = nodes()
    gauge("lab_vm_running", "1 if the node's VM is running")
    for n in ns: out.append(line("lab_vm_running", {**lab, "node": n["node"], "role": n["role"]}, int(n["state"] == "running")))
    if any(n["state"] == "running" for n in ns):
        v = live()
        gauge("homa_module_loaded", "1 if homa.ko is loaded on the host")
        for h, s in v["hosts"].items(): out.append(line("homa_module_loaded", {**lab, "node": h}, int(s.get("homa", False))))
        gauge("homa_resend_ticks", "net.homa.resend_ticks (ms of silence before a RESEND)")
        for h, s in v["hosts"].items():
            if s.get("up"): out.append(line("homa_resend_ticks", {**lab, "node": h}, s["timers"]["resend_ticks"] or 0))
        gauge("homa_link_mbps", "net.homa.link_mbps (the bottleneck rate Homa's pacer and grants assume)")
        for h, s in v["hosts"].items():
            if s.get("up"): out.append(line("homa_link_mbps", {**lab, "node": h}, s["link_mbps"] or 0))
        gauge("homa_counter_total", "/proc/net/homa_metrics, summed over cores (a selection)", "counter")
        for h, s in v["hosts"].items():
            for k, x in (s.get("counters") or {}).items(): out.append(line("homa_counter_total", {**lab, "node": h, "counter": k}, x))
        sw = v["sw1"]; to = {h["sw_port"]: h["name"] for h in H.inventory()["hosts"]}
        if "error" not in sw:
            gauge("sw1_qos_mode", "1 for sw1's current egress policy on the port (prio, fifo or off)")
            for port, p in sw.items(): out.append(line("sw1_qos_mode", {**lab, "port": port, "host": to.get(port, ""), "mode": p.get("mode") or "unknown"}, 1))
            gauge("sw1_port_bytes_total", "Bytes sw1 sent out of the port towards its host (any policy)", "counter")
            gauge("sw1_port_drops_total", "Packets sw1 dropped on the port (any policy)", "counter")
            for port, p in sw.items():
                t = p.get("total") or {}
                out.append(line("sw1_port_bytes_total", {**lab, "port": port, "host": to.get(port, "")}, t.get("bytes", 0)))
                out.append(line("sw1_port_drops_total", {**lab, "port": port, "host": to.get(port, "")}, t.get("drops", 0)))
            gauge("sw1_queue_packets_total", "Packets sent by sw1's egress queue (band 7 = highest priority)", "counter")
            gauge("sw1_queue_drops_total", "Packets dropped by sw1's egress queue", "counter")
            gauge("sw1_queue_bytes_total", "Bytes sent by sw1's egress queue", "counter")
            for port, p in sw.items():
                for band, q in (p.get("prio") or {}).items():
                    out.append(line("sw1_queue_packets_total", {**lab, "port": port, "host": to.get(port, ""), "band": band}, q["packets"]))
                    out.append(line("sw1_queue_drops_total", {**lab, "port": port, "host": to.get(port, ""), "band": band}, q["drops"]))
                    out.append(line("sw1_queue_bytes_total", {**lab, "port": port, "host": to.get(port, ""), "band": band}, q["bytes"]))
    gauge("homa_lab_run_active", "1 while a portal run (tests or a measurement) is going: they load the network, change sw1 and the timers on purpose")
    out.append(line("homa_lab_run_active", lab, int(busy())))
    out += run_metrics(NAME, registry.list())
    return exposition(out + metrics_generated(NAME))


def main():
    import uvicorn; uvicorn.run(app, host=os.environ.get("WEBAPP_HOST", "0.0.0.0"), port=PORT)


if __name__ == "__main__": main()
