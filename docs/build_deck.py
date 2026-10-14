#!/usr/bin/env python3
"""Build docs/homa-lab.pptx — the slide version of the walkthrough (docs/homa-lab-walkthrough.pdf).

The numbers come from docs/data/, the same measurements the PDF is built from (tools/build_walkthrough.py --refresh
collects them). Alongside the PowerPoint it writes docs/homa-lab-deck-preview.html, an HTML replica at the same
coordinates (this host has no LibreOffice). Run with a Python that has python-pptx and Pillow, e.g.
   ~/cat8000v-ipsec/webapp/.venv/bin/python docs/build_deck.py"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from decklib import (AMBER, BODY, CARD, DEEP, GREEN, GROUND, HEAD_FONT, INK, LINE, MONO_FONT, MUTED, PALE, TEAL, W,  # noqa: E402
                     Deck, para)

DATA = HERE / "data"
OUT, PREVIEW = HERE / "homa-lab.pptx", HERE / "homa-lab-deck-preview.html"
J = lambda n: json.loads((DATA / f"{n}.json").read_text())
HOMA, TCP = TEAL, AMBER
d = Deck(HERE)
slide, text, box, circle, line, table, chart = d.slide, d.text, d.box, d.circle, d.line, d.table, d.chart


def ms(us): return round(us / 1000, 2 if us < 10000 else 1)


def head(s, title, sub=None):
    t = text(s, 0.75, 0.5, 11.83, 0.8, size=32, color=INK, bold=True, font=HEAD_FONT)
    para(t, title, space_after=0)
    if sub:
        b = text(s, 0.75, 1.3, 11.83, 0.45, size=16, color=MUTED)
        para(b, sub, space_after=0)


def wraps(title, w, num=False):
    """Would a 17 pt card title wrap in a card w inches wide? (~0.115 in per character, a conservative estimate)"""
    return len(title) * 0.115 > w - (0.95 if num else 0.3) - 0.25


def card(s, x, y, w, h, title, body, num=None, size=14, fill=CARD, title_color=INK, body_color=BODY, line_color=LINE, two=None):
    box(s, x, y, w, h, fill=fill, line=line_color)
    tx = x + 0.3
    if num is not None:
        circle(s, x + 0.28, y + 0.27, 0.5, fill=TEAL)
        n = text(s, x + 0.28, y + 0.36, 0.5, 0.35, size=15, color="FFFFFF", bold=True, align="c", font=HEAD_FONT)
        para(n, str(num), space_after=0)
        tx = x + 0.95
    tw = x + w - tx - 0.25
    two = wraps(title, w, num is not None) if two is None else two   # cards in one row pass the row's answer
    t = text(s, tx, y + 0.3, tw, 0.8 if two else 0.45, size=17, color=title_color, bold=True, spacing=1.0)
    para(t, title, space_after=0)
    by = y + (1.2 if two else 0.88)
    b = text(s, x + 0.3, by, w - 0.6, h - (by - y) - 0.17, size=size, color=body_color, spacing=1.2)
    para(b, body, space_after=0)


def stat(s, x, y, w, big, label, color=TEAL, big_size=54, fill=CARD):
    box(s, x, y, w, 2.1, fill=fill)
    b = text(s, x + 0.25, y + 0.2, w - 0.5, 1.05, size=big_size, color=color, bold=True, font=HEAD_FONT, align="c", anchor="m")
    para(b, big, space_after=0)
    l = text(s, x + 0.25, y + 1.3, w - 0.5, 0.7, size=14, color=MUTED, align="c")
    para(l, label, space_after=0)


def divider(kicker, title, lines, notes):
    s = slide(DEEP, notes)
    k = text(s, 1.1, 2.35, 10.5, 0.45, size=15, color="8DB8EE", bold=True)
    para(k, kicker, space_after=0)
    t = text(s, 1.1, 2.85, 10.8, 1.1, size=44, color="FFFFFF", bold=True, font=HEAD_FONT, spacing=1.0)
    para(t, title, space_after=0)
    b = text(s, 1.1, 4.2, 10.8, 1.8, size=17, color=PALE, spacing=1.35)
    for i, ln in enumerate(lines):
        para(b, ln, space_after=0 if i == len(lines) - 1 else 8)


# ---- data ----------------------------------------------------------------------------------------------------------------
inc = {(r["mode"], r["protocol"]): r for r in J("incast")["runs"]}
cmp_ = J("compare"); loss = J("loss"); tim = J("timers"); cap = J("capture")
version = (HERE.parent / "VERSION").read_text().strip()

# 1 title
s = slide(INK, "homa-lab tests the Linux kernel module that implements Homa, a datacenter transport protocol from Stanford "
               "designed as an alternative to TCP for remote procedure calls. The lab runs the module on four hosts joined by "
               "a switch with real priority queues, and measures what Homa does under load, under incast and under loss.")
t = text(s, 0.9, 2.0, 11.0, 1.2, size=48, color="FFFFFF", bold=True, font=HEAD_FONT, spacing=1.0)
para(t, "Homa, in a lab", space_after=0)
sb = text(s, 0.9, 3.15, 11.0, 1.0, size=22, color=PALE)
para(sb, "Testing the Linux kernel module for the Homa transport protocol", space_after=0)
m = text(s, 0.9, 5.4, 11.0, 1.0, size=14, color="8DA2BE", spacing=1.4)
para(m, f"homa-lab {version}  ·  kernel 6.17.8  ·  HomaModule main @ 65cecd7  ·  26 of 26 tests passing", space_after=2)
para(m, "Companion to the lab walkthrough (homa-lab-walkthrough.pdf)", space_after=0)

# 2 what the lab is
s = slide(INK, "The four things the lab is built around. It tests behaviour and correctness, not raw performance: these are "
               "VMs on one 12-core host, so absolute numbers are not datacenter numbers, but comparisons on the same machines are fair.")
t = text(s, 0.9, 0.85, 11.5, 0.9, size=34, color="FFFFFF", bold=True, font=HEAD_FONT)
para(t, "What the lab does", space_after=0)
sb = text(s, 0.9, 1.7, 11.5, 0.5, size=17, color=PALE)
para(sb, "Behaviour and correctness, not datacenter benchmarks", space_after=0)
cols = [("Pinned build", "Mainline kernel 6.17.8 and a pinned HomaModule commit. One command builds the image and runs the module's 840 unit tests."),
        ("A real switch", "sw1 shapes each port to 1 Gbit/s with 8 strict priority queues chosen by the DSCP bits Homa sets, or one FIFO."),
        ("Homa's own tools", "homa_test, the echo server and cp_node from the module's util/, driven over SSH; a Homa dissector for tshark."),
        ("26 tests", "Robot suites: platform, function v4/v6, the wire, Homa vs TCP, incast, loss recovery, resend timers.")]
cw = (11.52 - 0.6) / 4
for i, (a, b) in enumerate(cols):
    card(s, 0.9 + i * (cw + 0.2), 2.6, cw, 3.4, a, b, two=any(wraps(t, cw) for t, _ in cols), fill=DEEP, title_color="FFFFFF", body_color=PALE, line_color=DEEP, size=15)

# ---- part 1: Homa for dummies -------------------------------------------------------------------------------------------
divider("PART 1", "Homa for dummies", ["What problem Homa solves, how it works, and what it costs — no networking background needed."],
        "This part is for people who don't live in transport protocols. If the audience knows TCP well, it can be skipped to part 2.")

# the problem: tail latency
s = slide(notes="The key idea: a request to a datacenter service fans out to many servers and finishes only when the slowest "
                "answer arrives. If 1 message in 100 is slow and a page needs 100 of them, 1 - 0.99^100 = 63% of pages are slow. "
                "So what matters is the tail, the 99th percentile, not the average.")
head(s, "The problem is the slowest message", "One click fans out to hundreds of small requests; the page waits for the last answer")
stat(s, 0.75, 2.2, 3.6, "1 in 100", "messages is slow")
stat(s, 4.6, 2.2, 3.6, "× 100", "messages per page")
stat(s, 8.45, 2.2, 4.13, "63%", "of pages are slow", color=AMBER)
b = text(s, 0.75, 4.75, 11.83, 2.0, size=17, color=BODY, spacing=1.3)
para(b, "Datacenter traffic is mostly tiny messages — a few hundred bytes — mixed with occasional big transfers. "
        "With TCP the tiny ones get stuck in queues behind the big ones.", space_after=10)
para(b, "What has to improve is the tail (the 99th percentile), not the average.", bold=True, space_after=0)

# TCP vs Homa analogy
s = slide(notes="The analogy. TCP: every sender accelerates until something is lost, then brakes; small messages queue behind "
                "big ones. Homa: the receiver acts as a dispatcher that sees everything heading its way, and the network has "
                "express lanes for small messages.")
head(s, "A road versus a loading dock", "Who decides when data moves, and whether small things can overtake")
card(s, 0.75, 2.05, 5.75, 4.6, "TCP: a single-lane road",
     "Each sender opens a connection and streams bytes. Drivers accelerate until there is a crash (a lost packet), then brake. "
     "Queues fill up before anyone slows down.\n\nA pizza scooter behind a convoy of trucks waits behind all of them.", size=16)
card(s, 6.83, 2.05, 5.75, 4.6, "Homa: a dock with a dispatcher",
     "Small parcels drive straight in on an express lane. Anyone with a truckload phones ahead; the dispatcher, who sees "
     "everything coming, tells each truck when to come — the one with the least left to unload goes first.\n\n"
     "Nobody crashes into a full queue, and the scooter never waits behind a truck.", size=16)

# five ideas
s = slide(notes="The five ideas, in order. Note idea 3 in this module version: messages up to about 40 KB go immediately; "
                "since September 2026 a longer message is announced with START_MSG and every byte waits for a grant.")
head(s, "How Homa works, in five ideas")
ideas = [("Messages, not streams", "Whole messages in, whole messages out: request + response = an RPC."),
         ("No connections", "One socket talks to thousands of peers with no setup or teardown."),
         ("Small messages just go", "Up to ~40 KB is sent at once; a longer message is announced and waits."),
         ("The receiver dispatches", "It grants permission to send, closest-to-finishing first."),
         ("Express lanes in the switch", "Each packet carries a priority 0–7; switches serve 7 first.")]
for i, (a, b) in enumerate(ideas):
    y = 1.6 + i * 1.08
    circle(s, 0.75, y + 0.08, 0.62, fill=TEAL)
    n = text(s, 0.75, y + 0.2, 0.62, 0.4, size=18, color="FFFFFF", bold=True, align="c", font=HEAD_FONT)
    para(n, str(i + 1), space_after=0)
    t = text(s, 1.65, y + 0.02, 4.4, 0.5, size=19, color=INK, bold=True, anchor="m")
    para(t, a, space_after=0)
    bt = text(s, 6.0, y + 0.08, 6.6, 0.6, size=16, color=BODY, anchor="m")
    para(bt, b, space_after=0)

# benefits
s = slide(notes="Benefits. The 10-100x figure is the Homa authors' measurement on real datacenter hardware; the lab reproduces "
                "the direction of the effect at small scale: under incast, Homa's short messages stayed under 2 ms at p99 "
                "while TCP's took 20-40 ms.")
head(s, "What Homa gives you")
ben = [("Low tail latency", "Papers report 10–100× lower p99 for short messages under load than TCP."),
       ("No head-of-line blocking", "Messages are independent; one slow message doesn't hold up the rest."),
       ("Incast by design", "When 100 servers answer at once, the receiver lets them in a few at a time."),
       ("Scales to many peers", "No connection per pair: no handshakes, no connection tables."),
       ("Fits RPC software", "Gives frameworks messages directly instead of a byte stream."),
       ("Uses existing hardware", "Switch priority queues already exist; they just need configuring.")]
cw, ch = (11.83 - 0.6) / 3, 2.3
for i, (a, b) in enumerate(ben):
    card(s, 0.75 + (i % 3) * (cw + 0.3), 1.6 + (i // 3) * (ch + 0.3), cw, ch, a, b, size=16,
         two=any(wraps(t, cw) for t, _ in ben[(i // 3) * 3:(i // 3) * 3 + 3]))

# drawbacks
s = slide(notes="Drawbacks, several measured in this lab: without priority queues the short-message advantage shrinks about "
                "10x at the median; TCP wins big transfers because NIC offloads only understand TCP; the default timers "
                "misfire at 1 Gbit/s. grant_fifo_fraction reserves bandwidth for the oldest message and is 0 (off) in this build.")
head(s, "What it costs")
drw = [("Not in Linux yet", "Out-of-tree module tied to kernel versions; upstreaming in stages since 2024."),
       ("Apps must change", "Message API, mapped receive buffers, 1 MB limit. Not a drop-in for TCP."),
       ("Datacenter only", "No encryption; NAT, firewalls and load balancers don't know protocol 146."),
       ("Needs switch config", "Without priority queues much of the benefit is gone."),
       ("Offloads are for TCP", "NICs don't segment Homa; TCP was faster for big transfers here."),
       ("Big messages can starve", "Shortest-first favours small ones; the FIFO-share knob is off by default."),
       ("Tuned for 25–100 Gbit/s", "Default timers misfired on this lab's 1 Gbit/s links."),
       ("A young ecosystem", "Few tools and few deployments; even its dissector was stale.")]
cw, ch = (11.83 - 0.9) / 4, 2.35
for i, (a, b) in enumerate(drw):
    card(s, 0.75 + (i % 4) * (cw + 0.3), 1.6 + (i // 4) * (ch + 0.3), cw, ch, a, b, size=14,
         two=any(wraps(t, cw) for t, _ in drw[(i // 4) * 4:(i // 4) * 4 + 4]))

# TCP vs Homa table
s = slide(notes="When to use which. Homa makes sense for RPC-heavy services inside one datacenter whose owner controls hosts "
                "and switches, where tail latency is the problem. Across the internet, for bulk transfer, or with apps that "
                "can't change, TCP or QUIC remains the answer.")
head(s, "TCP or Homa?", "Homa fits RPC-heavy services inside one datacenter you control")
table(s, 0.75, 1.95, 11.83, [
    ["", "TCP", "Homa"],
    ["Unit of data", "a byte stream", "a message (≤ 1 MB)"],
    ["Setup", "a connection per pair of machines", "none"],
    ["Who sets the pace", "each sender, probing until loss", "the receiver, with grants"],
    ["Switch priority queues", "not used", "essential"],
    ["Short messages under load", "wait behind big transfers", "overtake them"],
    ["Big transfers", "hardware offload, efficient", "no offload; can be starved"],
    ["Where it works", "everywhere", "inside one datacenter network"],
    ["In Linux", "since the beginning", "out-of-tree; upstreaming in progress"]],
    col_w=[3.0, 3.2, 3.2], size=16, row_h=0.52, bold_first_col=True)

# ---- part 2: the lab -----------------------------------------------------------------------------------------------------
divider("PART 2", "The lab", ["Four hosts, one switch with priority queues, a pinned build, and the tools to watch it work."],
        "How the lab is put together, and why each piece is the way it is.")

# architecture
s = slide(notes="Each host-to-sw1 link is its own isolated libvirt bridge. sw1 bridges them and applies its egress policy on "
                "the way to each host, i.e. at the receiver's downlink, where incast congestion happens. The hosts set "
                "link_mbps=1000 so Homa sizes its pacing and grants for the real bottleneck (the default assumes 25 Gbit/s).")
head(s, "Four hosts, one switch that matters")
hosts = [("h1", "192.168.80.11", 0.75, 1.75), ("h2", "192.168.80.12", 0.75, 4.55), ("h3", "192.168.80.13", 5.95, 1.75), ("h4", "192.168.80.14", 5.95, 4.55)]
sw = (3.25, 3.05, 2.2, 1.6)
for n, ip, x, y in hosts:
    line(s, x + 1.0, y + 0.55, sw[0] + sw[2] / 2, sw[1] + sw[3] / 2, color=TEAL, width=2.5)
for n, ip, x, y in hosts:
    box(s, x, y, 2.0, 1.1)
    t = text(s, x, y + 0.15, 2.0, 0.4, size=18, color=INK, bold=True, align="c")
    para(t, n, space_after=0)
    t = text(s, x, y + 0.6, 2.0, 0.35, size=13, color=MUTED, align="c", font=MONO_FONT)
    para(t, ip, space_after=0)
box(s, *sw, fill="E3EEFB", line=TEAL, width=1.5)
t = text(s, sw[0], sw[1] + 0.2, sw[2], 1.3, size=14, color=BODY, align="c", spacing=1.2)
para(t, "sw1", size=19, bold=True, color=INK, space_after=4)
para(t, "Linux bridge", space_after=0)
para(t, "1 Gbit/s · 8 queues", space_after=0)
d.side_note(s, 8.45, ["Kernel 6.17.8, homa.ko, homa_prio and test servers on every host.",
                      "Each link is an isolated libvirt bridge, MTU 9000.",
                      "sw1 queues traffic on the way to each host — the receiver's downlink, where incast hits.",
                      "Hosts set link_mbps=1000 to match the bottleneck."],
            y=1.75, w=4.13, title="What runs where", h=3.9)
s["items"][-1]["size"] = 15
for p in s["items"][-1]["paras"]: p["size"] = 15 if not p["bold"] else 17

# image build
s = slide(notes="tools/build_image.sh boots a throwaway builder VM on libvirt's NAT network, runs image/homa-build.sh once, "
                "and powers off. The unit tests needed two definitions to compile against Ubuntu's mainline headers "
                "(no __seg_gs address space, CONFIG_TRACE_PREEMPT_TOGGLE); with them all 840 pass.")
head(s, "One command builds and tests the module", "./lab.sh image — about 10 minutes, then every VM is an overlay on the result")
steps = [("Pin", "Hold the kernel packages; no background upgrades."),
         ("Kernel", "Install mainline 6.17.8; boot it by name."),
         ("Build", "homa.ko and util/ from the pinned commit."),
         ("Unit tests", "840 tests, user-space harness: all pass."),
         ("Lab pieces", "sw-qos, services, dissector; generalise.")]
cw = (11.83 - 4 * 0.25) / 5
for i, (a, b) in enumerate(steps):
    x = 0.75 + i * (cw + 0.25)
    card(s, x, 2.35, cw, 2.9, a, b, num=i + 1, size=15, two=any(wraps(t, cw, True) for t, _ in steps))
r = text(s, 0.75, 5.75, 11.83, 0.9, size=16, color=BODY, spacing=1.3)
para(r, "Result kept in the image and checked by suite 01:  unit tests: PASS (840 / 840 tests passed)", space_after=0)

# one RPC on the wire
tl = (DATA / "trace_long.txt").read_text().splitlines()
pick = tl[:13]
s = slide(notes="A 300 KB RPC captured on sw1's port to h1. The sender announces the message with START_MSG; the receiver "
                "grants 200,000 bytes one round trip later; data follows in full 9 KB frames and further grants extend the window. "
                "All grants say priority 0: with one message incoming, Homa uses the lowest scheduled priority. "
                "Capture on sw1, not the host: Homa's GRO handler consumes many arriving packets before tcpdump sees them.")
head(s, "One 300 KB RPC on the wire", "Announced, granted, then sent — captured on sw1, decoded with the lab's dissector")
box(s, 0.75, 1.95, 11.83, 3.3, fill="0F1D33", line="0F1D33")
tt = text(s, 1.0, 2.12, 11.4, 3.0, size=12, color="DCE7F5", font=MONO_FONT, spacing=1.15)
for i, l in enumerate(pick):
    para(tt, l.strip(), space_after=0)
cols = [("START_MSG", "The sender announces 300,000 bytes and sends nothing else."),
        ("GRANT", "0.2 ms later h2 allows 200,000 bytes, at priority 0."),
        ("DATA", "Full 9 KB frames; more grants extend the window as data drains.")]
cw = (11.83 - 0.6) / 3
for i, (a, b) in enumerate(cols):
    card(s, 0.75 + i * (cw + 0.3), 5.45, cw, 1.55, a, b, size=14, two=False)

# sw1 queues
bands = inc[("prio", "homa")]["sw_band_packets"]
cats = [f"priority {p}" for p in ["7", "6", "5", "4", "3", "2", "1", "0"]]
vals = [round(bands.get(p, 0) / 1000, 1) for p in ["7", "6", "5", "4", "3", "2", "1", "0"]]
s = slide(notes="Packets leaving sw1 towards h1 during the Homa incast run, by the priority Homa wrote into the IP header. "
                "Priority 7 carries short messages and every control packet (grants, acks); 6 and below carry scheduled data "
                "at the priorities the grants assigned. sw1 serves them strictly in that order.")
head(s, "sw1 sorts Homa's packets by priority", "Packets towards h1 during incast, by the priority in the IP header (thousands)")
chart(s, 0.75, 1.9, 7.4, 5.1, "bar", cats, [("packets (thousands)", vals)], [HOMA], size=13, number_format="0.0")
d.side_note(s, 8.5, ["Priority 7: short messages and all control packets — grants, acks, resends.",
                     "Priorities 6 and below: big messages' data, at the priority each grant names.",
                     "sw1 serves 7 first, then 6, and so on. TCP marks everything 0."],
            y=1.9, w=4.08, title="Strict priority, by DSCP", h=4.0)
s["items"][-1]["size"] = 15
for p in s["items"][-1]["paras"]: p["size"] = 15 if not p["bold"] else 17

# ---- part 3: results -----------------------------------------------------------------------------------------------------
divider("PART 3", "What the lab measured", ["Incast, Homa against TCP, loss recovery, and a finding about Homa's timers."],
        "All numbers come from one collection run against the live lab, the same data as the PDF.")

# incast
cats = ["Homa · priority queues", "Homa · one FIFO", "TCP · priority queues", "TCP · one FIFO"]
keys = [("prio", "homa"), ("fifo", "homa"), ("prio", "tcp"), ("fifo", "tcp")]
p50 = [ms(inc[k]["probe_loaded"]["p50"]) for k in keys]
p99 = [ms(inc[k]["probe_loaded"]["p99"]) for k in keys]
s = slide(notes=f"h2 and h3 stream 500 KB messages into h1, twice what its 1 Gbit/s port can take, while h4 sends 100-byte "
                f"probes to h1. With priority queues Homa's probes overtake the queued bulk data: median {p50[0]} ms against "
                f"{p50[1]} ms with one FIFO. TCP marks everything priority 0, so the queues can't help it: {p50[2]}-{p50[3]} ms. "
                f"Idle probe RTT is about 0.15 ms. Log scale.")
head(s, "Under incast, Homa's short messages overtake", "100-byte probes into h1 while two senders saturate its port — round trip in ms, log scale")
chart(s, 0.75, 1.9, 8.0, 5.2, "bar", cats, [("median", p50), ("99th percentile", p99)], [HOMA, "9DC1EE"], log=True, size=13, number_format="0.0#")
stat(s, 9.1, 1.95, 3.48, f"{p50[0]} ms", "Homa median, priority queues", color=HOMA, big_size=40)
stat(s, 9.1, 4.3, 3.48, f"{p50[2]:g} ms", "TCP median, same queues", color=AMBER, big_size=40)

# compare
cls = ["short (<=1 KB)", "medium (1-100 KB)", "long (>100 KB)"]
hp = [ms(cmp_["homa"]["rtt_us"][c]["p99"]) for c in cls]; tp = [ms(cmp_["tcp"]["rtt_us"][c]["p99"]) for c in cls]
hm = [ms(cmp_["homa"]["rtt_us"][c]["p50"]) for c in cls]; tm = [ms(cmp_["tcp"]["rtt_us"][c]["p50"]) for c in cls]
s = slide(notes=f"Light mixed load: Homa's W3 message-size distribution at 0.3 Gbit/s, about 170,000 RPCs each. Medians are close "
                f"(short: Homa {hm[0]} ms, TCP {tm[0]} ms). Homa's p99 is lower for short and medium messages; TCP wins long "
                f"messages because the virtio NICs give it segmentation offload and Homa gets none.")
head(s, "Light load: a shorter tail, slower big transfers", "Same workload over each protocol — 99th-percentile round trip in ms")
chart(s, 0.75, 1.9, 7.6, 5.2, "col", ["short ≤ 1 KB", "medium 1–100 KB", "long > 100 KB"], [("Homa", hp), ("TCP", tp)], [HOMA, TCP], size=13)
d.side_note(s, 8.75, [f"Short messages: Homa p99 {hp[0]} ms, TCP {tp[0]} ms.",
                      f"Medians are close: {hm[0]} vs {tm[0]} ms.",
                      f"Long messages: TCP {tp[2]} ms, Homa {hp[2]} ms — TCP has NIC offload, Homa doesn't."],
            y=1.9, w=3.83, title="Reading it", h=4.2)
s["items"][-1]["size"] = 15
for p in s["items"][-1]["paras"]: p["size"] = 15 if not p["bold"] else 17

# loss
m = loss["metrics"]
s = slide(notes=f"sw1 drops 1 in 50 packets towards h1, any type. h2 runs {loss['rtt']['count']} round trips of 20 KB each way. "
                f"Every RPC completes intact: h1 noticed the gaps and sent {m['h1']['packets_sent_RESEND']} RESENDs, h2 "
                f"retransmitted {m['h2']['resent_packets']} packets, nothing timed out. No connection state to repair.")
head(s, "Loss recovery without connections", "sw1 drops 1 packet in 50 towards h1 while h2 runs 20 KB round trips")
stat(s, 0.75, 2.1, 3.7, f"{loss['rtt']['count']}/{loss['rtt']['count']}", "RPCs completed intact", color=GREEN)
stat(s, 4.82, 2.1, 3.7, str(m["h1"]["packets_sent_RESEND"]), "RESENDs sent by h1")
stat(s, 8.88, 2.1, 3.7, "0", "RPC timeouts", color=GREEN)
b = text(s, 0.75, 4.75, 11.83, 1.8, size=17, color=BODY, spacing=1.3)
para(b, "The receiver tracks which byte ranges of each message arrived and asks for the missing ones; the sender "
        f"retransmits exactly those ({m['h2']['resent_packets']} packets). Nothing else to rebuild.", space_after=0)

# timers
dd, sc = tim["default"], tim["scaled"]
s = slide(notes="The lab's own finding. Shortest-first grants park all but the leading message at low priorities; strict "
                "priority starves them for tens of milliseconds at 1 Gbit/s. After 5 ms of silence (resend_ticks) the receiver "
                "asks for data that is only queued; the copies overflow the same queue and RPCs time out. Homa's defaults assume "
                "25-100 Gbit/s. Scaling resend_ticks, resend_interval and timeout_ticks by 10 removes the effect.")
head(s, "Finding: Homa's timers assume a fast network", "Two senders into h1 at 1 Gbit/s, priority queues — default timers vs ×10")
steps = [("Parked", "Shortest-first grants park the other messages at low priority."),
         ("Starved", "Strict priority leaves them queued for tens of ms."),
         ("False alarm", "After 5 ms of silence the receiver asks for queued data."),
         ("Overflow", "The copies fill the queue: drops and timeouts.")]
cw = (11.83 - 0.9) / 4
for i, (a, b) in enumerate(steps):
    card(s, 0.75 + i * (cw + 0.3), 1.95, cw, 2.1, a, b, num=i + 1, size=14, two=any(wraps(t, cw, True) for t, _ in steps))
table(s, 0.75, 4.4, 11.83, [
    ["Timers", "sw1 drops", "RESENDs", "RPC timeouts", "Bulk Mbit/s"],
    ["Defaults: resend 5 ms, timeout 100 ms", str(dd["sw_drops"]), str(dd["resends"]), str(dd["rpc_timeouts"]), f"{dd['mbit']:.0f}"],
    ["Scaled ×10: resend 50 ms, timeout 1000 ms", str(sc["sw_drops"]), str(sc["resends"]), str(sc["rpc_timeouts"]), f"{sc['mbit']:.0f}"]],
    col_w=[4.6, 1.6, 1.6, 1.8, 1.8], size=16, row_h=0.6, bold_first_col=True)

# tests
s = slide(notes="./lab.sh test runs seven Robot suites in about 12 minutes; the last full run passed all 26 tests. "
                "Suite 07 keeps the timer finding as a regression test.")
head(s, "26 tests, seven suites", "./lab.sh test — about 12 minutes; the last full run passed 26 of 26")
table(s, 0.75, 1.95, 11.83, [
    ["Suite", "What it checks", "Tests"],
    ["01 platform", "Pinned kernel, the right module build, unit tests passed, sysctls, services, sw1", "5"],
    ["02 function", "Jumbo frames; 48 round trips v4/v6; 8 B–1 MB intact; unload and autoload", "5"],
    ["03 wire", "Packet types; short and control at priority 7; granted priorities below", "6"],
    ["04 compare", "Homa vs TCP on the same workload; Homa's short tail not worse", "2"],
    ["05 incast", "Priority queues help Homa; Homa beats TCP 10× at p50, 3× at p99", "4"],
    ["06 loss", "1/50 loss: all RPCs complete, RESENDs answered, no timeouts", "2"],
    ["07 timers", "Default timers misfire; ×10 timers: no drops, no timeouts", "2"]],
    col_w=[1.9, 8.2, 1.0], size=15, row_h=0.6, bold_first_col=True)

# findings (dark)
s = slide(INK, "Summary of the findings. The priority-queue result reproduces Homa's central claim at small scale. The timer "
               "finding matters for anyone running Homa on slower links or emulating it. The offload and ecosystem points are "
               "the practical costs of adopting it today.")
t = text(s, 0.9, 0.85, 11.5, 0.9, size=34, color="FFFFFF", bold=True, font=HEAD_FONT)
para(t, "What we learned", space_after=0)
cols = [("Priority queues work", f"Under incast Homa's short messages stayed at {p50[0]} ms median; one FIFO: {p50[1]} ms; TCP: {p50[2]:g}+ ms."),
        ("Scale the timers", "At 1 Gbit/s the default resend timer misfires; ×10 removes drops and timeouts."),
        ("Offload gap", "NICs segment TCP, not Homa; its GSO and TCP-hijack modes failed for 1 MB messages here."),
        ("Lab plumbing matters", "UDP tunnels lost Homa's bursts silently; captures must be taken on the switch.")]
cw = (11.52 - 0.6) / 4
for i, (a, b) in enumerate(cols):
    card(s, 0.9 + i * (cw + 0.2), 2.0, cw, 3.0, a, b, two=any(wraps(t, cw) for t, _ in cols), fill=DEEP, title_color="FFFFFF", body_color=PALE, line_color=DEEP, size=15)

# next steps
s = slide(INK, "Not built yet: portal and NMS integration, the upstream patch-series kernel as a second track, the offload "
               "investigation, and HomaModule's cluster benchmarks adapted to four nodes.")
t = text(s, 0.9, 0.85, 11.5, 0.9, size=34, color="FFFFFF", bold=True, font=HEAD_FONT)
para(t, "What's next", space_after=0)
nxt = [("Portal and metrics", "A Prometheus exporter for Homa's metrics, a Grafana board, a portal on port 8108."),
       ("Upstream track", "A second kernel built from the upstream Homa patches, compared with the module."),
       ("Offloads", "Why GSO'd and TCP-hijacked large messages time out here."),
       ("Cluster benchmarks", "HomaModule's cp_vs_tcp and cp_load adapted to four nodes.")]
for i, (a, b) in enumerate(nxt):
    card(s, 0.9 + i * (cw + 0.2), 2.0, cw, 3.0, a, b, num=i + 1, two=any(wraps(t, cw, True) for t, _ in nxt), fill=DEEP, title_color="FFFFFF", body_color=PALE, line_color=DEEP, size=15)
f = text(s, 0.9, 5.55, 11.5, 0.8, size=15, color="8DA2BE")
para(f, "Everything here is in ~/homa-lab — README, walkthrough PDF, and ./lab.sh to run it yourself.", space_after=0)

if __name__ == "__main__":
    d.save_preview(PREVIEW, "homa-lab deck preview")
    print(f"wrote {PREVIEW.name}")
    if "--preview" not in sys.argv:
        d.save_pptx(OUT); print(f"wrote {OUT.name}: {len(d.slides)} slides")
