"""Robot Framework keywords for the Homa lab: thin wrappers over tools/homalab.py (the same code lab.sh bench runs)."""
import json
import os
import sys

from robot.api import logger
from robot.api.deco import keyword, library

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import homalab as L  # noqa: E402


@library(scope="GLOBAL")
class HomaLab:
    def __init__(self):
        self.inv = L.inventory()

    # ---- facts -------------------------------------------------------------------------------------------------------
    @keyword
    def lab_inventory(self):
        return self.inv

    @keyword
    def homa_hosts(self):
        return L.hosts()

    @keyword
    def data_ip(self, host, ipv6=False):
        h = self.inv["by_name"][host]
        return h["ip6"] if ipv6 else h["ip"]

    # ---- commands ----------------------------------------------------------------------------------------------------
    @keyword
    def run_on(self, node, command, timeout=120, expect_rc=0):
        rc, out = L.run(node, command, timeout=int(timeout))
        logger.info(f"{node}$ {command}\n{out}")
        if expect_rc is not None and str(expect_rc) != "any" and rc != int(expect_rc):
            raise AssertionError(f"{node}: `{command}` returned {rc}, expected {expect_rc}:\n{out[-1500:]}")
        return out.strip()

    @keyword
    def run_on_rc(self, node, command, timeout=120):
        rc, out = L.run(node, command, timeout=int(timeout))
        logger.info(f"{node}$ {command} -> rc {rc}\n{out}")
        return rc, out.strip()

    # ---- Homa --------------------------------------------------------------------------------------------------------
    @keyword
    def homa_rtt(self, src, dst, length=100, count=50, ipv6=False):
        r = L.rtt(src, dst, int(length), int(count), bool(ipv6) and str(ipv6).lower() != "false")
        logger.info(json.dumps(r, indent=1))
        return r

    @keyword
    def homa_rtt_matrix(self, count=20):
        r = L.matrix(int(count))
        bad = [x for x in r["results"] if not x["ok"]]
        logger.info("\n".join(f"{x['src']}->{x['dst']} {'v6' if x['ipv6'] else 'v4'} {x['length']} B: "
                              + (f"p50 {x['p50']} us" if x["ok"] else f"FAIL {x['errors'] or x.get('output', '')[-200:]}") for x in r["results"]))
        return r, bad

    @keyword
    def homa_metrics(self, host):
        return L.metrics(host)

    @keyword
    def metrics_delta(self, after, before, prefix=""):
        return L.mdiff(after, before, prefix)

    @keyword
    def set_homa_sysctls(self, *assignments):
        cmd = "sudo sysctl -qw " + " ".join(f"net.homa.{a}" for a in assignments)
        res = L.parallel({h: (L.run, h, cmd) for h in L.hosts()})
        bad = {h: o for h, (rc, o) in res.items() if rc}
        if bad:
            raise AssertionError(f"sysctl failed: {bad}")

    @keyword
    def homa_sysctl(self, host, name):
        return L.run(host, f"sysctl -n net.homa.{name}")[1].strip()

    # ---- sw1 ---------------------------------------------------------------------------------------------------------
    @keyword
    def switch_qos(self, *args):
        return L.qos(*args)

    @keyword
    def switch_qos_stats(self):
        return L.qos_stats()

    @keyword
    def restore_switch_default(self):
        L.qos_apply(self.inv["switch"]["qos"]["mode"])

    # ---- experiments -------------------------------------------------------------------------------------------------
    @keyword
    def compare_homa_and_tcp(self, workload="w3", gbps=0.3, seconds=12):
        r = L.compare(workload, float(gbps), int(seconds))
        self._table("Homa vs TCP, same workload", [(p, k, v) for p in ("homa", "tcp") for k, v in r[p]["rtt_us"].items()])
        return r

    @keyword
    def run_incast(self, modes="prio,fifo", protocols="homa,tcp", seconds=10, rate_mbit=1000):
        r = L.incast(modes.split(","), protocols.split(","), int(seconds), rate_mbit=int(rate_mbit))
        logger.info(json.dumps(r, indent=1))
        rows = []
        for x in r["runs"]:
            rows.append((f"sw1 {x['mode']} / {x['protocol']}", "probe idle", x["probe_idle"]))
            rows.append((f"sw1 {x['mode']} / {x['protocol']}", f"probe under incast (bulk {x['bulk_mbit']} Mbit/s, sw1 drops {x['sw_drops']})", x["probe_loaded"]))
        self._table(f"Incast at {r['target']}: bulk from {', '.join(r['bulk_senders'])}, probes from {r['prober']}", rows)
        return {f"{x['mode']}_{x['protocol']}": x for x in r["runs"]}

    @keyword
    def run_loss(self, n=50, count=300):
        r = L.loss(int(n), int(count))
        logger.info(json.dumps(r, indent=1))
        return r

    @keyword
    def capture_homa(self, seconds=4):
        r = L.capture(int(seconds))
        logger.info(json.dumps(r, indent=1))
        return r

    @keyword
    def incast_bulk(self, seconds=8, target="h1"):
        """Bulk only (no probes): two senders, 500 KB one-way messages, at the lab's normal rate. Returns throughput, sw1
        drops, and the target's RESEND / RPC timeout counts."""
        port = self.inv["by_name"][target]["sw_port"]
        senders = [h for h in L.hosts() if h != target][:2]
        q0, m0 = L.qos_stats()[port], L.metrics(target)
        r = L.parallel({b: (L.cp_client, b, "homa", 500000, [target], int(seconds), 0.0, 4, 1, True, 1, "bulk_timers") for b in senders})
        q1, d = L.qos_stats()[port], L.mdiff(L.metrics(target), m0)
        out = {"mbit": round(sum(len(r[b]["samples"]) for b in senders) * 500000 * 8 / (int(seconds) + 1) / 1e6, 1),
               "sw_drops": q1["total"]["drops"] - q0["total"]["drops"], "resends": d.get("packets_sent_RESEND", 0),
               "rpc_timeouts": d.get("rpc_timeouts", 0)}
        logger.info(json.dumps(out))
        return out

    def _table(self, title, rows):
        html = [f"<b>{title}</b><table border=1 cellpadding=3><tr><th></th><th>messages</th><th>n</th><th>p50 µs</th><th>p99 µs</th><th>p99.9 µs</th></tr>"]
        for a, b, v in rows:
            v = v or {}
            html.append(f"<tr><td>{a}</td><td>{b}</td><td>{v.get('n', '')}</td><td>{v.get('p50', '')}</td><td>{v.get('p99', '')}</td><td>{v.get('p99.9', '')}</td></tr>")
        logger.info("".join(html) + "</table>", html=True)
