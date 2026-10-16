# Patches

Fixes found while testing HomaModule in this lab. The lab builds and runs the **unpatched** pinned commit
(`HOMA_COMMIT` in `lab.conf`); these are kept here to test by hand and to report upstream.

| Patch | Against | Status |
|---|---|---|
| `0001-hijack-gro-read-header-from-frag0.patch` | PlatformLab/HomaModule `65cecd7` (main, 2026-10-08) | Tested in this lab (sizes 1 KB–1 MB, with and without GSO). **Not reported upstream yet.** |

To try one: build the module from the pinned source with the patch applied (`patch -p1 < …` in the HomaModule tree,
then `make`), and load it in place of the installed one on every host. Suite 08's `known-bug` test then fails, which is
how it notices a fixed module.

---

## Bug report draft (for github.com/PlatformLab/HomaModule/issues)

**Title:** TCP hijacking: full-size packets are delivered to TCP and dropped when the receiving NIC leaves headers in frag0 (virtio_net)

**Summary.** With `hijack_tcp=1`, every message larger than one packet times out when the receiver uses virtio_net.
Control packets and one-packet messages work. The receiver hands each full-size hijacked DATA packet to TCP, which drops
it.

**Environment.**
- HomaModule `main` at `65cecd7831e8b24ba7bcd967288bb7ce26fe8eba`.
- Linux 6.17.8 (Ubuntu mainline build `6.17.8-061708-generic`).
- KVM guests with virtio_net (mergeable RX buffers), MTU 9000, `net.homa.link_mbps=1000`.
- Hosts joined through a Linux bridge VM.

**Steps to reproduce.**
1. On every host: `sysctl -w net.homa.hijack_tcp=1`, then restart the servers. `hijack_tcp` is read when a socket is
   created.
2. `homa_test <peer>:4100 --count 5 --length 1000 rtt` works.
3. `homa_test <peer>:4100 --count 5 --length 10000 rtt` times out. The sender keeps retransmitting after RESENDs, and the
   receiver's `packets_rcvd_DATA` doesn't grow for the full-size packets.

**What happens.** A `kfree_skb` trace on the receiver shows the packets dropped by TCP with
`SKB_DROP_REASON_TCP_RESET` (1,701 drops in one test). An ftrace function profile showed 2,327 calls to
`homa_hijack_gro_receive`, of which 1,722 went on to `tcp4_gro_receive` and `tcp_v4_rcv`. So the GRO hook decided they
were not Homa packets.

**Cause.** `homa_hijack_gro_receive()` calls `homa_skb_hijacked()`, which reads `flags` and `urgent` through
`skb_transport_header()`. In the GRO path, the headers of a large packet may still be in a page fragment (frag0), not
in the skb's linear area. virtio_net with mergeable buffers copies only `GOOD_COPY_LEN` bytes into the linear part
(enough for the Ethernet header), and GRO reads the rest through `skb_gro_header()`. So the check reads bytes past the
linear data and the comparison fails. The packet then takes the TCP path, and because the hijack flag pattern includes
RST, TCP drops it. Short packets fit in the copied part, which is why control packets and one-packet messages work.
`homa_gro_receive()` doesn't have this problem because it calls `homa_make_header_avl()` before touching the header.

**Fix (patch attached, `0001-hijack-gro-read-header-from-frag0.patch`).** In `homa_hijack_gro_receive()`, read the
header with `skb_gro_header(skb, off + offsetofend(struct homa_common_hdr, urgent), off)` for the decision. Then, for
a Homa packet, call `homa_make_header_avl()` before `ip_hdr()` is modified, as `homa_gro_receive()` does.

**Result with the patch.** `hijack_tcp=1` works for every size tried (1 KB, 10 KB, 30 KB, 60 KB, 100 KB, 300 KB, 1 MB),
alone and together with `max_gso_size=100000`. A 1 MB message then leaves the sender as 510 TSO frames. No TCP_RESET
drops.

**Related, not a module bug.** With native GSO (`max_gso_size` > MTU, `hijack_tcp=0`) on a virtio guest that advertises
TSO, the GSO frames go to the hypervisor, which can't segment IP protocol 146 and drops them (the host tap's
`tx_dropped` counts them). With the guest's TSO off, `homa_gso_segment` segments in the guest and every size works,
although INSTALL.md says software GSO is "temporarily broken". The note in INSTALL.md may be out of date.
