#!/usr/bin/env python3
"""Drive the Homa lab from the host: the inventory, SSH to the VMs, Homa round trips, cp_node workloads, sw1's queues,
packet captures and Homa's kernel metrics. Used by lab.sh (verify, bench) and by the Robot suites (tests/resources).

  homalab.py matrix [--count N]                  one Homa RTT test per host pair, IPv4 and IPv6
  homalab.py rtt SRC DST [--length B] [--count N] [--ipv6]
  homalab.py compare [--workload w3] [--gbps 0.3] [--seconds 12]      Homa vs TCP, same workload, h1 -> h2..h4
  homalab.py incast [--modes prio,fifo] [--protocols homa,tcp] [--seconds 10]   bulk h2,h3 -> h1 + probes h4 -> h1
  homalab.py loss [--n 50] [--count 300]        drop 1/N on sw1 towards h1; Homa recovers (RESENDs, no failures)
  homalab.py capture [--seconds 4]              one mixed run into h1, captured on sw1, decoded (types, priorities)
  homalab.py offload [--configs a,b] [--sizes 1000,..]   round trips per segmentation-offload setting (GSO, hijacking)
  homalab.py metrics HOST                       /proc/net/homa_metrics summed over cores (JSON)
Every command prints JSON on stdout (human summary on stderr).
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import time

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=5"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


_inv = None


def inventory():
    global _inv
    if _inv is None:
        env = {k: v for k, v in os.environ.items() if k != "FORCE_COLOR"}   # python's json.tool colours otherwise
        _inv = json.loads(subprocess.run([f"{LAB}/lab.sh", "inventory"], capture_output=True, text=True, check=True, env=env).stdout)
        _inv["by_name"] = {h["name"]: h for h in _inv["hosts"]}
    return _inv


def mgmt(node):
    inv = inventory()
    return inv["switch"]["mgmt_ip"] if node == inv["switch"]["name"] else inv["by_name"][node]["mgmt_ip"]


def run(node, cmd, timeout=120, check=False):
    """Run a shell command on a node; returns (rc, stdout+stderr)."""
    # the remote side gets its own timeout: killing ssh alone leaves the command (and its Homa RPCs) running on the VM
    remote = f"timeout -k 5 {int(timeout)} bash -c {shlex.quote(cmd)}"
    r = subprocess.run(SSH + [f"lab@{mgmt(node)}", remote], capture_output=True, text=True, timeout=timeout + 15)
    out = r.stdout + r.stderr
    if check and r.returncode != 0:
        raise RuntimeError(f"{node}: `{cmd}` failed ({r.returncode}): {out.strip()[-500:]}")
    return r.returncode, out


def parallel(jobs):
    """jobs: {key: (fn, args...)} -> {key: result}"""
    with cf.ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
        futs = {k: ex.submit(v[0], *v[1:]) for k, v in jobs.items()}
        return {k: f.result() for k, f in futs.items()}


def hosts():
    return [h["name"] for h in inventory()["hosts"]]


def idx(host):
    return inventory()["by_name"][host]["idx"]


# ---- Homa round trips (homa_test against the standing echo servers) ----------------------------------------------------
def rtt(src, dst, length=100, count=100, ipv6=False, timeout=180):
    target = f"{dst}-v6:4101" if ipv6 else f"{dst}:4100"
    rc, out = run(src, f"homa_test {target} {'--ipv6 ' if ipv6 else ''}--count {count} --length {length} rtt", timeout=timeout)
    res = {"src": src, "dst": dst, "ipv6": ipv6, "length": length, "count": count, "rc": rc,
           "errors": [l for l in out.splitlines() if "Error" in l or "failed" in l.lower()]}
    for k, v in re.findall(r"^(Min|P\d+|Max|Avg):\s+([\d.]+) us", out, re.M):
        res[k.lower()] = float(v)
    res["ok"] = rc == 0 and not res["errors"] and "p50" in res
    if not res["ok"]:
        res["output"] = out[-800:]
    return res


def matrix(count=20, lengths=(100, 100000)):
    jobs = {}
    for a in hosts():
        for b in hosts():
            if a != b:
                for v6 in (False, True):
                    for ln in lengths:
                        jobs[(a, b, v6, ln)] = (rtt, a, b, ln, count, v6)
    # one pair at a time: the hosts have 2 vCPUs and one echo server thread each, so concurrent tests measure the overload
    rows = [v[0](*v[1:]) for _, v in sorted(jobs.items())]
    for r in rows:
        log(f"  {r['src']} -> {r['dst']} {'v6' if r['ipv6'] else 'v4'} {r['length']:>7} B  "
            + (f"p50 {r['p50']:8.1f} us  p90 {r['p90']:8.1f} us" if r["ok"] else f"FAIL {r['errors'][:1] or r.get('output', '')[-200:]}"))
    ok = sum(r["ok"] for r in rows)
    log(f"  {ok}/{len(rows)} Homa RTT tests ok")
    return {"ok": ok == len(rows), "passed": ok, "total": len(rows), "results": rows}


# ---- metrics ----------------------------------------------------------------------------------------------------------
def metrics(host):
    _, out = run(host, "cat /proc/net/homa_metrics", check=True)
    m = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 2 and p[1].lstrip("-").isdigit() and p[0] not in ("core", "time_cycles", "cpu_khz"):
            m[p[0]] = m.get(p[0], 0) + int(p[1])
    return m


def mdiff(after, before, prefix=""):
    return {k: after[k] - before.get(k, 0) for k in after if k.startswith(prefix) and after[k] - before.get(k, 0)}


# ---- sw1 --------------------------------------------------------------------------------------------------------------
def qos(*args):
    _, out = run(inventory()["switch"]["name"], "sudo sw-qos " + " ".join(shlex.quote(a) for a in args), check=True)
    return out


def qos_stats():
    return json.loads(qos("stats"))


def qos_apply(mode, rate=None, limit=None):
    sw = inventory()["switch"]["qos"]
    return qos("apply", mode, rate or sw["rate"], str(limit or sw["limit"]))


# ---- cp_node workloads ------------------------------------------------------------------------------------------------
def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = min(len(xs) - 1, max(0, int(round(p / 100 * (len(xs) - 1)))))
    return round(xs[k], 1)


def summarize(samples):
    """[(length, rtt_us)] -> per size class: n, p50, p99, p99.9, mean (us)"""
    classes = {"short (<=1 KB)": (0, 1000), "medium (1-100 KB)": (1001, 100000), "long (>100 KB)": (100001, 1 << 40), "all": (0, 1 << 40)}
    out = {}
    for name, (lo, hi) in classes.items():
        xs = [r for ln, r in samples if lo <= ln <= hi]
        if xs:
            out[name] = {"n": len(xs), "p50": pct(xs, 50), "p99": pct(xs, 99), "p99.9": pct(xs, 99.9), "mean": round(statistics.fmean(xs), 1)}
    return out


def cp_client(host, protocol, workload, servers, seconds, gbps=0.0, client_max=1, ports=1, one_way=False, warmup=2, tag=None, probe=False):
    """Run one cp_node client for `seconds` (after `warmup`), return its RTT samples [(length, us)] and its last stats line."""
    tag = tag or f"{protocol}_{workload}"
    f = f"/tmp/{tag}.rtts"
    opts = (f"--protocol {protocol} --workload {workload} --servers {','.join(str(idx(s)) for s in servers)} "
            f"--client-max {client_max} --ports {ports} --gbps {gbps} --id {idx(host)} --exp {tag}" + (" --one-way" if one_way else "")
            + (f" --first-port {4010 if protocol == 'homa' else 5010}" if probe else ""))   # the cp-*-probe servers
    script = (f"rm -f {f}; (printf 'client {opts}\\n'; sleep {warmup}; printf 'dump_times /dev/null\\n'; sleep {seconds}; "
              f"printf 'dump_times {f} {tag}\\nstop clients\\nexit\\n') | timeout {seconds + warmup + 30} cp_node > /tmp/{tag}.out 2>&1; "
              f"grep 'clients:' /tmp/{tag}.out | tail -1; echo '--RTTS--'; grep -v '^#' {f}")
    rc, out = run(host, script, timeout=seconds + warmup + 60)
    stats, _, body = out.partition("--RTTS--")
    samples = []
    for line in body.split("\n"):
        p = line.split()
        if len(p) == 2:
            try:
                samples.append((int(p[0]), float(p[1])))
            except ValueError:
                pass
    return {"host": host, "protocol": protocol, "workload": workload, "rc": rc, "stats_line": stats.strip()[-300:], "samples": samples}


def compare(workload="w3", gbps=0.3, seconds=12, client="h1"):
    servers = [h for h in hosts() if h != client]
    res = {}
    for proto in ("homa", "tcp"):
        r = cp_client(client, proto, workload, servers, seconds, gbps=gbps, client_max=8, ports=2, tag=f"cmp_{proto}")
        res[proto] = {"rpcs": len(r["samples"]), "rtt_us": summarize(r["samples"]), "cp_node": r["stats_line"]}
        s = res[proto]["rtt_us"]
        log(f"  {proto:4}: {len(r['samples'])} RPCs  " + "  ".join(f"{k.split()[0]} p50 {v['p50']} p99 {v['p99']}" for k, v in s.items() if k != "all"))
    return {"workload": workload, "gbps": gbps, "seconds": seconds, "client": client, "servers": servers, **res}


def set_rate(rate_mbit):
    """The bottleneck rate: sw1's per-port shaper and Homa's link_mbps on every host (they must agree)."""
    sw = inventory()["switch"]["qos"]
    parallel({h: (run, h, f"sudo sysctl -qw net.homa.link_mbps={rate_mbit}") for h in hosts()})
    return f"{rate_mbit}mbit"


def incast(modes=("prio", "fifo"), protocols=("homa", "tcp"), seconds=10, bulk_size=500000, probe_size=100, target="h1", rate_mbit=500):
    """h2, h3 stream bulk_size-byte one-way messages to target while h4 sends probe_size probes to target (to separate server
    processes, one at a time). The bottleneck is sw1's port towards target, shaped to rate_mbit (below what the two senders
    offer, so a queue builds there); the probes' RTT shows what that queue does to short messages."""
    others = [h for h in hosts() if h != target]
    bulk, probe = others[:-1], others[-1]
    port = inventory()["by_name"][target]["sw_port"]
    sw = inventory()["switch"]["qos"]
    default_mbit = int(re.match(r"(\d+)", sw["rate"]).group(1)) * (1000 if sw["rate"].endswith("gbit") else 1)
    out = {"target": target, "bulk_senders": bulk, "prober": probe, "bulk_size": bulk_size, "probe_size": probe_size,
           "rate_mbit": rate_mbit, "seconds": seconds, "runs": []}
    try:
        set_rate(rate_mbit)
        for mode in modes:
            qos_apply(mode, rate=f"{rate_mbit}mbit")
            for proto in protocols:
                base = cp_client(probe, proto, probe_size, [target], 3, tag=f"idle_{proto}", probe=True)
                jobs = {b: (cp_client, b, proto, bulk_size, [target], seconds + 2, 0.0, 4, 1, True, 1, f"bulk_{proto}") for b in bulk}
                jobs["probe"] = (cp_client, probe, proto, probe_size, [target], seconds, 0.0, 1, 1, False, 3, f"probe_{proto}", True)
                q0 = qos_stats()[port]
                r = parallel(jobs)
                q1 = qos_stats()[port]
                p = summarize(r["probe"]["samples"]).get("all", {})
                idle = summarize(base["samples"]).get("all", {})
                bulk_msgs = sum(len(r[b]["samples"]) for b in bulk)          # one-way: the dump lists the 100 B replies
                drops = (q1["total"] or {}).get("drops", 0) - (q0["total"] or {}).get("drops", 0)
                bands = {k: v["packets"] - q0["prio"].get(k, {}).get("packets", 0) for k, v in q1["prio"].items()}
                run_ = {"mode": mode, "protocol": proto, "probe_idle": idle, "probe_loaded": p,
                        "bulk_mbit": round(bulk_msgs * bulk_size * 8 / (seconds + 2) / 1e6, 1), "sw_drops": drops,
                        "sw_band_packets": {k: v for k, v in sorted(bands.items(), reverse=True) if v}}
                out["runs"].append(run_)
                log(f"  sw1 {mode:4} {proto:4}: probe RTT idle p50 {idle.get('p50')} us | under incast p50 {p.get('p50')} p99 {p.get('p99')} us "
                    f"(n={p.get('n')}); bulk {run_['bulk_mbit']} Mbit/s into a {rate_mbit} Mbit/s port; sw1 drops {drops}; packets by priority {run_['sw_band_packets']}")
    finally:
        set_rate(default_mbit)
        qos_apply(sw["mode"])
    return out


def loss(n=50, count=300, length=20000, src="h2", dst="h1"):
    port = inventory()["by_name"][dst]["sw_port"]
    before = {h: metrics(h) for h in (src, dst)}
    try:
        qos("loss", port, str(n))
        r = rtt(src, dst, length=length, count=count, timeout=600)
        filt = qos("show", port)
    finally:
        qos("loss", port, "off")
    after = {h: metrics(h) for h in (src, dst)}
    d = {h: mdiff(after[h], before[h]) for h in (src, dst)}
    dropped = re.findall(r"dropped (\d+)", filt)
    keys = ("packets_sent_RESEND", "packets_rcvd_RESEND", "resent_packets", "rpc_timeouts", "packets_sent_DATA", "packets_sent_NEED_ACK")
    res = {"drop_one_in": n, "port": port, "rtt": r, "metrics": {h: {k: d[h].get(k, 0) for k in keys} for h in d}, "sw_filter": filt[-600:]}
    log(f"  1/{n} dropped towards {dst}: {count} RTTs of {length} B {'all ok' if r['ok'] else 'FAILED'}; p50 {r.get('p50')} p99 {r.get('p99')} us; "
        f"{dst} sent {res['metrics'][dst]['packets_sent_RESEND']} RESENDs, {src} resent {res['metrics'][src]['resent_packets']} packets")
    return res


# ---- segmentation offload (GSO, TCP hijacking) -------------------------------------------------------------------------
# hijack_tcp is read when a socket is created, so every configuration restarts the echo servers. "guest_tso": the hosts'
# virtio NICs claim TCP segmentation; a Homa GSO frame (IP protocol 146) handed to them reaches the lab host, which has no
# Homa and drops it (the host must segment it because sw1's NICs take no offloads). With the guests' TSO off, the guest
# kernel segments it with Homa's own homa_gso_segment.
OFFLOAD = {
    "default":     ({"max_gso_size": 1000, "hijack_tcp": 0}, True),
    "gso":         ({"max_gso_size": 100000, "hijack_tcp": 0}, True),
    "gso_guest":   ({"max_gso_size": 100000, "hijack_tcp": 0}, False),
    "hijack":      ({"max_gso_size": 1000, "hijack_tcp": 1}, True),
    "hijack_gso":  ({"max_gso_size": 100000, "hijack_tcp": 1}, True),
}


def offload_apply(name):
    cfg, tso = OFFLOAD[name]
    kv = " ".join(f"net.homa.{k}={v}" for k, v in cfg.items())
    nic = "sudo ethtool -K eth1 tso on && sudo ethtool -K eth1 tx-tcp-mangleid-segmentation off" if tso else "sudo ethtool -K eth1 tso off"   # tso is a group: it sets mangleid too
    parallel({h: (run, h, f"sudo sysctl -qw {kv} && {nic} >/dev/null && sudo systemctl restart homa-echo homa-echo6", 60, True) for h in hosts()})
    time.sleep(1)


def offload(configs=("default", "gso", "gso_guest", "hijack", "hijack_gso"), sizes=(1000, 10000, 100000, 1000000), count=10, src="h2", dst="h1"):
    """Homa round trips src -> dst per offload configuration and message size: ok, latency, and how many DATA frames the
    sender handed to its NIC against the DATA packets the receiver saw (fewer frames than packets = segmentation offload)."""
    out = {"src": src, "dst": dst, "count": count, "sizes": list(sizes), "configs": {}}
    try:
        for name in configs:
            offload_apply(name); rows = []
            for size in sizes:
                m0 = {h: metrics(h) for h in (src, dst)}
                r = rtt(src, dst, length=size, count=count, timeout=60)
                m1 = {h: metrics(h) for h in (src, dst)}
                d = {h: mdiff(m1[h], m0[h]) for h in (src, dst)}
                row = {"size": size, "ok": r["ok"], "p50": r.get("p50"), "p90": r.get("p90"),
                       "frames_sent": d[src].get("packets_sent_DATA", 0), "packets_received": d[dst].get("packets_rcvd_DATA", 0),
                       "resends": d[dst].get("packets_sent_RESEND", 0) + d[src].get("packets_sent_RESEND", 0),
                       "timeouts": d[dst].get("rpc_timeouts", 0) + d[src].get("rpc_timeouts", 0)}
                rows.append(row)
                log(f"  {name:10} {size:>8} B  {'ok  ' if r['ok'] else 'FAIL'}  p50 {r.get('p50')} us  frames sent {row['frames_sent']}, "
                    f"DATA packets received {row['packets_received']}, RESENDs {row['resends']}, timeouts {row['timeouts']}")
            out["configs"][name] = rows
    finally:
        offload_apply("default")
    return out


def capture(seconds=4, host="h1"):
    """Capture Homa on sw1's port towards `host` (both directions) while `host` serves a mix (short + 500 KB messages from
    two peers); decode with the lab dissector. Not on the host itself: Homa consumes many arriving GRANT and DATA packets
    in its GRO handler (gro_*_bypasses), before tcpdump's tap, so a receiver-side capture misses them."""
    sw = inventory()["switch"]["name"]
    iface = inventory()["by_name"][host]["sw_port"]
    peers = [h for h in hosts() if h != host][:2]
    f = "/tmp/lab-capture.pcap"
    run(sw, f"sudo rm -f {f}; sudo systemd-run -q --unit lab-capture -p RuntimeMaxSec={seconds + 25} tcpdump -i {iface} -s 128 -w {f} 'ip proto 146 or ip6 proto 146'", check=True)
    time.sleep(1.5)
    parallel({peers[0]: (cp_client, peers[0], "homa", 500000, [host], seconds, 0.0, 2, 1, True, 1, "cap_bulk"),
              peers[1]: (cp_client, peers[1], "homa", 100, [host], seconds, 0.0, 1, 1, False, 1, "cap_probe", True)})
    time.sleep(1)
    run(sw, "sudo systemctl stop lab-capture 2>/dev/null; sleep 1")
    _, out = run(sw, f"sudo cat {f} | tshark -r - -T fields -E separator=, -e ip.src -e ip.dst -e ip.dsfield.dscp "
                     f"-e homa.type_name -e homa.offset -e homa.seg_length -e homa.priority -e homa.msg_length -e homa.retransmit", timeout=300)
    pk = []
    for line in out.splitlines():
        p = line.split(",")
        if len(p) == 9 and p[3]:
            pk.append({"src": p[0], "dst": p[1], "prio": int(p[2] or 0) >> 3, "type": p[3], "offset": int(p[4] or -1),
                       "seg": int(p[5] or 0), "grant_prio": int(p[6]) if p[6] else None, "msg": int(p[7] or 0), "retransmit": p[8] == "1"})
    types = {}
    for x in pk:
        types[x["type"]] = types.get(x["type"], 0) + 1
    data = [x for x in pk if x["type"] == "DATA"]
    short = [x for x in data if x["msg"] <= 1000]
    long_unsched = [x for x in data if x["msg"] > 100000 and x["offset"] == 0]
    long_sched = [x for x in data if x["msg"] > 100000 and x["offset"] >= 100000]
    grants = [x for x in pk if x["type"] == "GRANT"]
    pr = lambda xs: sorted({x["prio"] for x in xs})
    res = {"packets": len(pk), "types": types,
           "priorities": {"short_data": pr(short), "long_first_packet": pr(long_unsched), "long_scheduled_data": pr(long_sched),
                          "grants_carry": sorted({x["grant_prio"] for x in grants if x["grant_prio"] is not None}), "control": pr([x for x in pk if x["type"] != "DATA"])},
           "data_packets": len(data), "retransmitted": sum(x["retransmit"] for x in data)}
    log(f"  {len(pk)} Homa packets on sw1 {iface} (to and from {host}): " + ", ".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda kv: -kv[1])))
    log(f"  priorities on the wire: {res['priorities']}")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("matrix"); a.add_argument("--count", type=int, default=20)
    a = sp.add_parser("rtt"); a.add_argument("src"); a.add_argument("dst"); a.add_argument("--length", type=int, default=100)
    a.add_argument("--count", type=int, default=100); a.add_argument("--ipv6", action="store_true")
    a = sp.add_parser("compare"); a.add_argument("--workload", default="w3"); a.add_argument("--gbps", type=float, default=0.3); a.add_argument("--seconds", type=int, default=12)
    a = sp.add_parser("incast"); a.add_argument("--modes", default="prio,fifo"); a.add_argument("--protocols", default="homa,tcp"); a.add_argument("--seconds", type=int, default=10)
    a.add_argument("--rate", type=int, default=500, help="bottleneck Mbit/s during the test")
    a = sp.add_parser("loss"); a.add_argument("--n", type=int, default=50); a.add_argument("--count", type=int, default=300)
    a = sp.add_parser("capture"); a.add_argument("--seconds", type=int, default=4)
    a = sp.add_parser("offload"); a.add_argument("--configs", default=",".join(OFFLOAD)); a.add_argument("--sizes", default="1000,10000,100000,1000000")
    a.add_argument("--count", type=int, default=10)
    a = sp.add_parser("metrics"); a.add_argument("host")
    o = ap.parse_args()
    if o.cmd == "matrix": r = matrix(o.count)
    elif o.cmd == "rtt": r = rtt(o.src, o.dst, o.length, o.count, o.ipv6)
    elif o.cmd == "compare": r = compare(o.workload, o.gbps, o.seconds)
    elif o.cmd == "incast": r = incast(o.modes.split(","), o.protocols.split(","), o.seconds, rate_mbit=o.rate)
    elif o.cmd == "loss": r = loss(o.n, o.count)
    elif o.cmd == "capture": r = capture(o.seconds)
    elif o.cmd == "offload": r = offload(o.configs.split(","), [int(x) for x in o.sizes.split(",")], o.count)
    else: r = metrics(o.host)
    print(json.dumps(r, indent=1))
    return 0 if (r.get("ok", True) if isinstance(r, dict) else True) else 1


if __name__ == "__main__":
    sys.exit(main())
