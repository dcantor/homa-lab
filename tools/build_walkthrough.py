#!/usr/bin/env python3
"""Build docs/homa-lab-walkthrough.pdf from docs/walkthrough.src.html.

    build_walkthrough.py --refresh     collect everything from the running lab into docs/data/ (~5 min), then build
    build_walkthrough.py               build from docs/data/ as collected last time
    build_walkthrough.py --html-only   stop after docs/walkthrough.html

Placeholders in the source: {{text:NAME}} (docs/data/NAME.txt, preformatted), {{file:PATH}} / {{code:PATH:A-B}}
(repository files), {{chart:incast}}, {{table:NAME}}, {{val:NAME.path}} (a value from docs/data/NAME.json), {{results}},
{{version}}, {{date}}, {{tests}}. Headless Chrome prints the HTML."""
import html
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
DOCS, DATA = LAB / "docs", LAB / "docs" / "data"
SRC, STYLE, OUT_HTML, OUT_PDF = DOCS / "walkthrough.src.html", DOCS / "walkthrough.style.html", DOCS / "walkthrough.html", DOCS / "homa-lab-walkthrough.pdf"
sys.path.insert(0, str(LAB / "tools"))
sys.path.insert(0, str(LAB / "tests" / "resources"))
E = html.escape
ENV = {k: v for k, v in os.environ.items() if k != "FORCE_COLOR"}


def sh(*args, timeout=900):
    r = subprocess.run([str(LAB / "lab.sh"), *args], capture_output=True, text=True, timeout=timeout, cwd=LAB, env=ENV)
    return re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout + r.stderr)).rstrip()


def put(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / (name + (".json" if not isinstance(obj, str) else ".txt"))
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1))
    print(f"  data/{p.name}", file=sys.stderr)


# ---- collection -------------------------------------------------------------------------------------------------------
def trace(L, length, count=1):
    """One homa_test RTT h1 -> h2 captured on sw1's port to h1 (both directions), decoded with the lab dissector."""
    f = "/tmp/wt-trace.pcap"
    L.run("sw1", f"sudo rm -f {f}; sudo systemd-run -q --unit wt-trace -p RuntimeMaxSec=60 tcpdump -i eth1 -s 160 -w {f} 'ip proto 146'", check=True)
    time.sleep(1.5)
    L.run("h1", f"homa_test h2:4100 --count {count} --length {length} rtt")
    time.sleep(1)
    L.run("sw1", "sudo systemctl stop wt-trace 2>/dev/null; sleep 1")
    _, out = L.run("sw1", f"sudo cat {f} | tshark -r - -T fields -E separator='|' -e frame.time_relative -e ip.src -e ip.dst -e ip.dsfield.dscp -e frame.len -e _ws.col.Info")
    rows = []
    for line in out.splitlines():
        p = line.split("|")
        if len(p) == 6:
            t, s, d, dscp, ln, info = p
            name = {f"192.168.80.1{i}": f"h{i}" for i in range(1, 5)}
            rows.append(f"{float(t) * 1000:8.3f} ms  {name.get(s, s):>3} → {name.get(d, d):<3} prio {int(dscp or 0) >> 3}  {int(ln):>5} B  {info}")
    _, verbose = L.run("sw1", f"sudo cat {f} | tshark -r - -V -Y 'homa.type == 0x11' 2>/dev/null | sed -n '/^Homa/,/^$/p' | head -15")
    return rows, verbose.strip()


def collect():
    import homalab as L
    from HomaLab import HomaLab
    lib = HomaLab()
    print("collecting from the lab:", file=sys.stderr)
    put("status", sh("status"))
    put("usage", sh("help").split("\n", 1)[1] if sh("help") else "")
    put("homa_status", sh("homa", "status"))
    put("verify", "\n".join(l for l in sh("verify").splitlines() if not re.match(r"^\s+h\d -> h\d v6 ", l)))
    put("build_log", "\n".join(l.strip() for l in (LAB / "images" / "build.log").read_text(errors="replace").replace("\r", "").splitlines()
                               if re.search(r"HOMA-BUILD|unit tests:|dissector:|tests passed|^\+ make|modinfo|srcversion|vermagic", l))[-1500:])
    put("sysctl", L.run("h1", "sudo sysctl net.homa")[1].strip())
    put("unit", L.run("h1", "tail -4 /var/log/homa-unit.log; cat /var/log/homa-unit.result")[1].strip())
    put("modinfo", L.run("h1", "modinfo homa | grep -E '^(filename|version|description|license|srcversion|vermagic|name|alias)'")[1].strip())
    rows, gv = trace(L, 100)
    put("trace_short", "\n".join(rows))
    rows, gv = trace(L, 300000)
    put("trace_long", "\n".join(rows[:40]) + (f"\n… {len(rows) - 40} more packets" if len(rows) > 40 else ""))
    put("trace_long_counts", json.dumps({t: sum(t in r for r in rows) for t in ("DATA", "GRANT", "START_MSG", "ACK", "NEED_ACK", "RESEND", "CUTOFFS", "BUSY")}))
    put("grant_verbose", gv)
    L.qos("apply", "prio", "1gbit", "200")       # zero the counters, then one mixed capture
    put("capture", L.capture(4))
    put("qos_show", "\n".join(L.qos("show", "eth1").splitlines()[:40]))
    put("compare", L.compare("w3", 0.3, 12))
    put("incast", L.incast(("prio", "fifo"), ("homa", "tcp"), 10, rate_mbit=1000))
    put("loss", L.loss(50, 300))
    lib.set_homa_sysctls("resend_ticks=5", "resend_interval=5", "timeout_ticks=100")
    d = lib.incast_bulk(8)
    lib.set_homa_sysctls("resend_ticks=50", "resend_interval=20", "timeout_ticks=1000")
    s = lib.incast_bulk(8)
    lib.set_homa_sysctls("resend_ticks=5", "resend_interval=5", "timeout_ticks=100")
    put("timers", {"default": d, "scaled": s})
    put("metrics_h1", L.metrics("h1"))
    L.qos_apply("prio")


# ---- rendering helpers ------------------------------------------------------------------------------------------------
def j(name):
    return json.loads((DATA / f"{name}.json").read_text())


def ms(us):
    return "–" if us is None else (f"{us / 1000:.2f}" if us < 10000 else f"{us / 1000:.1f}")


def table_compare():
    c = j("compare"); rows = []
    for cls in ("short (<=1 KB)", "medium (1-100 KB)", "long (>100 KB)"):
        h, t = c["homa"]["rtt_us"].get(cls, {}), c["tcp"]["rtt_us"].get(cls, {})
        rows.append(f"<tr><td>{E(cls.replace('<=', '≤'))}</td><td class='num'>{h.get('n', '')}</td><td class='num'>{ms(h.get('p50'))}</td><td class='num'>{ms(h.get('p99'))}</td><td class='num'>{ms(h.get('p99.9'))}</td>"
                    f"<td class='num'>{t.get('n', '')}</td><td class='num'>{ms(t.get('p50'))}</td><td class='num'>{ms(t.get('p99'))}</td><td class='num'>{ms(t.get('p99.9'))}</td></tr>")
    return ("<table><tr><th rowspan=2>messages</th><th colspan=4>Homa (ms)</th><th colspan=4>TCP (ms)</th></tr>"
            "<tr><th class='num'>n</th><th class='num'>p50</th><th class='num'>p99</th><th class='num'>p99.9</th><th class='num'>n</th><th class='num'>p50</th><th class='num'>p99</th><th class='num'>p99.9</th></tr>"
            + "".join(rows) + "</table>")


def table_incast():
    r = j("incast"); rows = []
    for x in r["runs"]:
        p, i = x["probe_loaded"], x["probe_idle"]
        rows.append(f"<tr><td>{'strict priority' if x['mode'] == 'prio' else 'one FIFO'}</td><td>{'Homa' if x['protocol'] == 'homa' else 'TCP'}</td>"
                    f"<td class='num'>{ms(i.get('p50'))}</td><td class='num'>{ms(p.get('p50'))}</td><td class='num'>{ms(p.get('p99'))}</td><td class='num'>{p.get('n')}</td>"
                    f"<td class='num'>{x['bulk_mbit']:.0f}</td><td class='num'>{x['sw_drops']}</td></tr>")
    return ("<table><tr><th>sw1 queues</th><th>protocol</th><th class='num'>probe p50 idle (ms)</th><th class='num'>probe p50 under incast</th>"
            "<th class='num'>probe p99 under incast</th><th class='num'>probes</th><th class='num'>bulk Mbit/s</th><th class='num'>sw1 drops</th></tr>" + "".join(rows) + "</table>")


def table_timers():
    t = j("timers"); rows = []
    for k, label in (("default", "Homa defaults: resend_ticks 5, resend_interval 5, timeout_ticks 100"), ("scaled", "×10: resend_ticks 50, resend_interval 20, timeout_ticks 1000")):
        v = t[k]
        rows.append(f"<tr><td>{label}</td><td class='num'>{v['mbit']:.0f}</td><td class='num'>{v['sw_drops']}</td><td class='num'>{v['resends']}</td><td class='num'>{v['rpc_timeouts']}</td></tr>")
    return "<table><tr><th>timers</th><th class='num'>bulk Mbit/s</th><th class='num'>sw1 drops</th><th class='num'>RESENDs from h1</th><th class='num'>RPC timeouts</th></tr>" + "".join(rows) + "</table>"


def table_loss():
    l = j("loss"); m = l["metrics"]; r = l["rtt"]
    return (f"<table><tr><th></th><th class='num'>value</th></tr>"
            f"<tr><td>round trips (20 KB each way), completed</td><td class='num'>{r['count'] if r['ok'] else 'FAILED'}</td></tr>"
            f"<tr><td>RTT p50 / p90 (ms)</td><td class='num'>{ms(r.get('p50'))} / {ms(r.get('p90'))}</td></tr>"
            f"<tr><td>RESENDs sent by h1 (receiver of the requests)</td><td class='num'>{m['h1']['packets_sent_RESEND']}</td></tr>"
            f"<tr><td>packets retransmitted by h2</td><td class='num'>{m['h2']['resent_packets']}</td></tr>"
            f"<tr><td>RESENDs sent by h2 (receiver of the replies)</td><td class='num'>{m['h2']['packets_sent_RESEND']}</td></tr>"
            f"<tr><td>RPC timeouts (h1 / h2)</td><td class='num'>{m['h1']['rpc_timeouts']} / {m['h2']['rpc_timeouts']}</td></tr></table>")


def table_capture():
    c = j("capture")
    types = "".join(f"<tr><td class='mono'>{E(k)}</td><td class='num'>{v}</td></tr>" for k, v in sorted(c["types"].items(), key=lambda kv: -kv[1]))
    pr = c["priorities"]
    prio = "".join(f"<tr><td>{E(a)}</td><td class='mono'>{E(', '.join(map(str, pr[b])))}</td></tr>" for a, b in (
        ("short messages (≤ 1 KB): their only packet", "short_data"), ("500 KB messages: the first packet", "long_first_packet"),
        ("500 KB messages: data after 100 KB (scheduled)", "long_scheduled_data"), ("priorities the GRANTs assign", "grants_carry"),
        ("control packets (GRANT, RESEND, ACK, …)", "control")))
    return (f"<div class='two'><table><tr><th>packet type</th><th class='num'>packets</th></tr>{types}</table>"
            f"<table><tr><th>what</th><th>priorities seen (0-7)</th></tr>{prio}</table></div>")


def chart_incast():
    """Dot plot, log x axis: per configuration the idle p50 (hollow gray), loaded p50 (filled) and p99 (diamond), Homa blue
    and TCP orange (reference palette slots 1 and 2), values labeled."""
    r = j("incast"); runs = {(x["mode"], x["protocol"]): x for x in r["runs"]}
    order = [("prio", "homa"), ("fifo", "homa"), ("prio", "tcp"), ("fifo", "tcp")]
    col = {"homa": "#2a78d6", "tcp": "#eb6834"}
    W, left, right, top, rowh = 680, 170, 30, 34, 44
    H = top + rowh * len(order) + 46
    import math
    lo, hi = 0.1, 100.0
    X = lambda v: left + (math.log10(max(lo, min(hi, v))) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (W - left - right)
    s = [f"<svg viewBox='0 0 {W} {H}' width='100%' xmlns='http://www.w3.org/2000/svg' style='font-size:11px'>"]
    for v in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100):
        x = X(v); major = v in (0.1, 1, 10, 100)
        s.append(f"<line x1='{x:.1f}' y1='{top - 8}' x2='{x:.1f}' y2='{H - 40}' stroke='{'#d4d4d0' if major else '#ecebe8'}' stroke-width='1'/>")
        s.append(f"<text x='{x:.1f}' y='{H - 26}' text-anchor='middle' fill='#52514e'>{v:g}</text>")
    s.append(f"<text x='{(left + W - right) / 2:.0f}' y='{H - 8}' text-anchor='middle' fill='#52514e'>probe round-trip time, ms (log scale)</text>")
    for i, k in enumerate(order):
        x = runs.get(k)
        if not x: continue
        y = top + rowh * i + rowh / 2
        c = col[k[1]]
        idle, p50, p99 = x["probe_idle"].get("p50", 0) / 1000, x["probe_loaded"].get("p50", 0) / 1000, x["probe_loaded"].get("p99", 0) / 1000
        s.append(f"<text x='{left - 12}' y='{y - 3:.0f}' text-anchor='end' fill='#0b0b0b' font-weight='600'>{'Homa' if k[1] == 'homa' else 'TCP'}</text>")
        s.append(f"<text x='{left - 12}' y='{y + 11:.0f}' text-anchor='end' fill='#52514e'>{'strict priority queues' if k[0] == 'prio' else 'one FIFO queue'}</text>")
        s.append(f"<line x1='{X(p50):.1f}' y1='{y}' x2='{X(p99):.1f}' y2='{y}' stroke='{c}' stroke-width='2'/>")
        s.append(f"<circle cx='{X(idle):.1f}' cy='{y}' r='4.5' fill='#fcfcfb' stroke='#8a8984' stroke-width='2'/>")
        s.append(f"<circle cx='{X(p50):.1f}' cy='{y}' r='5.5' fill='{c}' stroke='#fcfcfb' stroke-width='2'/>")
        d = 6.5; xx = X(p99)
        s.append(f"<path d='M{xx:.1f},{y - d} L{xx + d:.1f},{y} L{xx:.1f},{y + d} L{xx - d:.1f},{y} Z' fill='{c}' stroke='#fcfcfb' stroke-width='2'/>")
        s.append(f"<text x='{X(p50):.1f}' y='{y - 10:.0f}' text-anchor='middle' fill='#0b0b0b'>{p50:.2g}</text>")
        s.append(f"<text x='{xx:.1f}' y='{y - 10:.0f}' text-anchor='middle' fill='#0b0b0b'>{p99:.2g}</text>")
    # legend
    lx = left
    s.append(f"<circle cx='{lx}' cy='12' r='5' fill='#2a78d6'/><text x='{lx + 9}' y='16' fill='#0b0b0b'>Homa</text>")
    s.append(f"<circle cx='{lx + 60}' cy='12' r='5' fill='#eb6834'/><text x='{lx + 69}' y='16' fill='#0b0b0b'>TCP</text>")
    s.append(f"<circle cx='{lx + 120}' cy='12' r='5' fill='#52514e'/><text x='{lx + 129}' y='16' fill='#52514e'>p50 under incast</text>")
    s.append(f"<path d='M{lx + 238},6 L{lx + 244},12 L{lx + 238},18 L{lx + 232},12 Z' fill='#52514e'/><text x='{lx + 249}' y='16' fill='#52514e'>p99 under incast</text>")
    s.append(f"<circle cx='{lx + 358}' cy='12' r='4' fill='#fcfcfb' stroke='#8a8984' stroke-width='2'/><text x='{lx + 367}' y='16' fill='#52514e'>p50 idle</text>")
    s.append("</svg>")
    return "".join(s)


def results():
    out = LAB / "results" / "latest" / "output.xml"
    root = ET.parse(out).getroot()
    rows, passed, failed = [], 0, 0
    for su in root.iter("suite"):
        if not su.get("source", "").endswith(".robot"): continue
        tests = list(su.iter("test"))
        p = sum(t.find("status").get("status") == "PASS" for t in tests)
        st = su.find("status")
        secs = float(st.get("elapsed", 0))
        rows.append(f"<tr><td>{E(su.get('name'))}</td><td class='num'>{p}/{len(tests)}</td><td class='num'>{secs:.0f} s</td></tr>")
        passed += p; failed += len(tests) - p
    when = out.resolve().parent.name
    return passed, failed, (f"<table><tr><th>suite</th><th class='num'>passed</th><th class='num'>time</th></tr>{''.join(rows)}</table>"
                            f"<p class='cap'>Run {E(when)}: {passed} passed, {failed} failed.</p>")


def code(path, spec):
    lines = (LAB / path).read_text().splitlines()
    a, b = (int(x) for x in spec.split("-"))
    return "\n".join(lines[a - 1:b])


def val(spec):
    name, path = spec.split(".", 1)
    v = j(name)
    for p in path.split("."):
        v = v[int(p)] if isinstance(v, list) else v[p]
    return str(v)


def build():
    s = SRC.read_text()
    passed, failed, res = results()
    s = s.replace("{{style}}", STYLE.read_text()).replace("{{results}}", res)
    s = s.replace("{{version}}", (LAB / "VERSION").read_text().strip()).replace("{{date}}", time.strftime("%-d %B %Y"))
    s = s.replace("{{tests}}", str(passed + failed)).replace("{{passed}}", str(passed))
    s = s.replace("{{chart:incast}}", chart_incast())
    for name, fn in (("compare", table_compare), ("incast", table_incast), ("timers", table_timers), ("loss", table_loss), ("capture", table_capture)):
        s = s.replace(f"{{{{table:{name}}}}}", fn())
    s = re.sub(r"\{\{text:([\w]+)\}\}", lambda m: E((DATA / f"{m.group(1)}.txt").read_text().rstrip()), s)
    s = re.sub(r"\{\{val:([\w.]+)\}\}", lambda m: E(val(m.group(1))), s)
    s = re.sub(r"\{\{file:([\w./-]+)\}\}", lambda m: E((LAB / m.group(1)).read_text().strip()), s)
    s = re.sub(r"\{\{code:([\w./-]+):([\d-]+)\}\}", lambda m: E(code(m.group(1), m.group(2))), s)
    left = re.findall(r"\{\{[^}]+\}\}", s)
    if left: raise SystemExit(f"unfilled placeholders: {left}")
    OUT_HTML.write_text(s); print(f"wrote {OUT_HTML.relative_to(LAB)}")
    if "--html-only" in sys.argv: return
    subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=/tmp/homa-lab-walkthrough-chrome", "--no-pdf-header-footer",
                    "--virtual-time-budget=8000", f"--print-to-pdf={OUT_PDF}", f"file://{OUT_HTML}"], capture_output=True, timeout=300)
    print(f"wrote {OUT_PDF.relative_to(LAB)}: {OUT_PDF.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    if "--refresh" in sys.argv: collect()
    build()
