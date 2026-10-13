# homa-lab

A lab for testing the Linux kernel module that implements the **Homa** transport protocol
([PlatformLab/HomaModule](https://github.com/PlatformLab/HomaModule)). Four Linux hosts run `homa.ko`. They are joined by
a Linux switch VM whose ports behave like a datacenter top-of-rack switch: a rate limit, which is the bottleneck, and
8 strict-priority queues selected by the IP header field where Homa writes its packet priority.

```
  h1 eth1 ── eth1 ┐
  h2 eth1 ── eth2 ├─ sw1   Linux bridge br0; per-port egress (sw-qos): htb 1 Gbit/s → prio, 8 bands by DSCP/TC top 3 bits
  h3 eth1 ── eth3 │        (or one FIFO, or nothing); optional random loss per port
  h4 eth1 ── eth4 ┘
  data 192.168.80.0/24 + fd00:80::/64, MTU 9000          OOB 10.8.0.0/24 (eth0), user lab / lab + your SSH key
```

The lab tests behaviour, not performance. These are KVM guests on one 12-core host, so absolute numbers are not
datacenter numbers. What the lab shows honestly is correctness, comparisons on the same machines (Homa vs TCP,
priority queues vs FIFO), and protocol behaviour (priorities, grants, loss recovery, timers).

## Quick start
```bash
./lab.sh image        # once, ~10 min: Ubuntu 26.04 + mainline 6.17.8 + homa.ko built and unit-tested (840 tests)
./lab.sh up && ./lab.sh wait
./lab.sh verify       # kernel + module, sw1 policy, jumbo ping matrix v4/v6, a Homa RTT between every pair
./lab.sh test         # Robot Framework, results/<timestamp>/report.html (~12 min)
./lab.sh down
```
Resources: 5 VMs, 9 GiB RAM, 10 vCPUs. Disk: about 4 GB of base image plus small overlays.

## What is built, and why
| Piece | Choice | Why |
|---|---|---|
| Kernel | mainline **6.17.8** (kernel.ubuntu.com) on Ubuntu 26.04 | HomaModule's `main` is developed against 6.17.8; the host's 7.0 is "compiles, not supported" |
| Module | HomaModule `main` @ `65cecd7` (2026-10-08), pinned in `lab.conf` | out-of-tree module; Homa is not in mainline (upstreaming in stages) |
| Image | `tools/build_image.sh`: a builder VM installs the kernel, builds `homa.ko` + `util/`, runs the unit tests | every node is a qcow2 overlay on `images/homa-base.qcow2` |
| Links | one isolated libvirt bridge per host↔sw1 link (`networks/homa-link*.xml`) | the UDP tunnels the other labs use lost Homa's bursts in the host's 208 KB socket buffer (see Findings) |
| Switch | `sw-qos` on sw1 (`image/sw-qos`) | Homa needs priority queues in the switch, by the top 3 bits of DSCP (IPv4) / traffic class (IPv6) |
| Settings | `net.homa.link_mbps=1000` on the hosts | the default assumes 25 Gbit/s; Homa's pacer and grants must match the real bottleneck |
| Dissector | `image/homa.lua` (tshark/Wireshark) | HomaModule's `dissector/` still expects IP protocol 253 and the old header layout; Homa is protocol 146 |

Standing services on every host: `homa-prio` (HomaModule's priority-cutoff daemon), `homa-echo` / `homa-echo6` (echo
servers for `homa_test`, ports 4100/4101, contents validated), `cp-homa` / `cp-tcp` (cp_node servers 4000/5000), and
`cp-homa-probe` / `cp-tcp-probe` (4010/5010). The probe servers are separate processes, so a latency probe never queues
behind bulk messages in the same server thread.

## Commands
```bash
./lab.sh status | inventory
./lab.sh homa status|load|unload|reload|sysctl [k[=v]..]|metrics [host]
./lab.sh qos show | apply prio|fifo|off [RATE] [LIMIT] | loss eth1 50 | loss eth1 off | stats
./lab.sh exec hosts 'uname -r'                 # in parallel on h1-h4 (or one node, or all)
./lab.sh bench rtt h1 h2 --length 100000       # homa_test against the echo server
./lab.sh bench compare                          # Homa vs TCP, W3 workload, 0.3 Gbit/s
./lab.sh bench incast                           # bulk h2,h3 -> h1 + probes h4 -> h1; sw1 prio vs fifo; Homa and TCP
./lab.sh bench loss --n 50                      # 1/50 dropped towards h1
./lab.sh bench capture                          # decoded capture at h1: packet types, priorities on the wire
./lab.sh bench metrics h1                       # /proc/net/homa_metrics summed over cores
```
To read a capture with tshark on a host, pipe it in (`sudo cat x.pcap | tshark -r -`). Ubuntu's tshark AppArmor profile
does not let it open files in /tmp or a home directory, or load plugins from `~/.local`. The dissector is installed in
the global plugin directory for the same reason.

## Test suites (`tests/suites`)
| Suite | What it checks |
|---|---|
| 01 platform | pinned kernel; the loaded module is the installed build at the pinned commit; unit tests passed in the image build; sysctls, metrics, protocol-146 sockets (v4/v6); services; sw1's bridge and policy |
| 02 function | jumbo frames v4/v6 between all pairs; a Homa RTT between all 12 ordered pairs × v4/v6 × 100 B/100 KB; message sizes 8 B to 1 MB intact; the module refuses to unload with sockets open, unloads, and the first protocol-146 socket loads it again |
| 03 wire | decoded capture: DATA/GRANT/START_MSG/ACK on the wire; short messages and control at priority 7; scheduled data at lower, grant-assigned priorities; sw1 sorted traffic into several queues |
| 04 compare | Homa vs TCP on the same W3 workload; recorded, and Homa's short-message p99 must not be worse than TCP's by more than 50% |
| 05 incast | two bulk senders saturate h1's port; with priority queues Homa's short-message p99 is below FIFO's (and p50 3× below), and below TCP's by 10× at p50 and 3× at p99 |
| 06 loss | 1/50 random loss towards h1: every RPC completes; RESENDs sent and data retransmitted; no RPC timeouts |
| 07 timers | the timer finding below: default timers cause spurious RESENDs; timers scaled ×10 give no drops, no timeouts and 3× fewer RESENDs |

## Findings so far (2026-10-13)
1. **Priority queues work as Homa's design says.** In the incast run, with h1's 1 Gbit/s port at sw1 saturated
   (~900–970 Mbit/s of 500 KB messages), Homa's 100 B probes measured p50 0.34–0.42 ms (idle: 0.14 ms) with strict
   priority queues, against p50 3.0 ms with one FIFO. TCP probes in the same situation measured p50 13–30 ms. TCP marks
   everything priority 0, so the priority queues don't help it. Homa's p99 under priority queues varies from 1.5 to
   4.4 ms between runs (finding 2); FIFO gives 4.6–5.7 ms and TCP 20–37 ms.
2. **Homa's timers assume a fast network.** Under the same incast, SRPT grants park all but the leading message at low
   priorities, and strict priority starves those for more than the 5 ms `resend_ticks`. The receiver then asks for data
   that is queued, not lost; the copies land in the same starved queue, sw1 overflows, and RPCs time out (about 5,000
   drops and 60 timeouts in 8 s). With `resend_ticks=50 resend_interval=20 timeout_ticks=1000` there were no drops and no
   timeouts, and a tenth of the RESENDs. At 25–100 Gbit/s the same bytes drain 25–100× faster, so the defaults suit
   that speed.
3. **On a light mixed workload (W3, 0.3 Gbit/s)** Homa's short-message p99 is about 2.3 ms against TCP's 3.9 ms, while
   TCP's median is slightly lower. TCP is faster for long messages here because it gets TSO on the virtio NICs and Homa
   does not (software GSO in the module is "temporarily broken", per its INSTALL.md).
4. **Offload settings:** `max_gso_size=100000` (GSO) makes 1 MB RPCs time out in this setup, which matches the module's
   note. With `hijack_tcp=1` (TCP hijacking for TSO), small RPCs work and are faster (p50 141 µs vs ~520 µs on the old
   tunnel links), but 1 MB RPCs time out. The defaults (`hijack_tcp=0`, `max_gso_size=1000`) are kept. Not investigated
   further.
5. **Unit tests vs distro headers:** HomaModule's user-space unit-test harness does not compile against the Ubuntu mainline
   headers as-is. `mock.h` redeclares `current_task` without the `__seg_gs` address space, and `mock.c` defines
   `preempt_count_add/sub`. The build adds a header that undefines `CONFIG_USE_X86_SEG_SUPPORT` and defines
   `CONFIG_TRACE_PREEMPT_TOGGLE`. With that, all 840 tests pass.
6. **Lab plumbing:** QEMU's UDP-socket links lost Homa's bursts of 9 KB frames in the host's default socket buffer.
   Homa showed only RESENDs and timeouts, nothing visible inside the lab, until the host's `UdpRcvbufErrors` counter
   gave it away. Bridges fixed it. A malformed request (under the echo protocol's 8-byte header) leaves the client and
   server trading RESEND/BUSY indefinitely. That is by design (the server is "busy"), but every remote command in the lab
   now carries its own timeout so nothing is left running.

## Layout
`lab.conf` (source of truth) · `lab.sh` · `networks/` · `image/` (builder script, sw-qos, services, dissector) ·
`tools/build_image.sh`, `tools/homalab.py` (all measurements; JSON out) · `tests/` (Robot; `tests/resources/HomaLab.py`
wraps homalab.py) · `results/` (per run: Robot output and `state/`, the sysctls / module / sw1 policy before the run).

## Not yet
A portal, Lab Hub card, NMS metrics (a `/proc/net/homa_metrics` exporter), a walkthrough PDF, the upstream patch-series
kernel as a second track, the hijack/GSO investigation.
