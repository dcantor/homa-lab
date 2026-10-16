# Changelog
All notable changes to this lab. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-10-15
### Added
- The segmentation offload investigation (2026-10-14), kept as a measurement and tests: `./lab.sh bench offload`
  (`tools/homalab.py offload`: round trips per configuration — default, gso, gso_guest, hijack, hijack_gso — and size,
  with frames sent against packets received), Robot suite 08 (4 tests; the hijack bug test is tagged `known-bug` and
  fails once the pinned module is fixed), and walkthrough section 14.
- `patches/0001-hijack-gro-read-header-from-frag0.patch`: fixes TCP hijacking on receivers that leave headers in
  frag0 (virtio_net). `patches/README.md` has the bug report draft for HomaModule.
### Changed
- README findings 3 and 4 rewritten. Native GSO is lost on the lab host when the guest NIC does TSO, and works when the
  guest segments. TCP hijacking loses full-size packets because of a GRO bug in the module. TCP's lead on long messages
  is not TSO (it stayed with offload working for Homa); the cause is open.
### Fixed
- The walkthrough's Tests section had a garbled sentence about the results folder.

## [0.2.1] - 2026-10-14
### Added
- NMS: Prometheus scrapes the portal (job `homa-lab`, lab-portal 0.39.0), alert group `homa-lab`, Grafana dashboard
  **homa-lab: overview (Homa kernel module)**.
- Portal `/metrics`: `sw1_port_bytes_total` / `sw1_port_drops_total` (per port, any policy), `sw1_queue_bytes_total`,
  `sw1_qos_mode`, `homa_link_mbps`, `homa_lab_run_active`; sw1 series carry the `host` the port faces.

## [0.2.0] - 2026-10-14
### Added
- Portal (`webapp/`, port 8108, user unit `homa-lab-webapp`, `./lab.sh webapp`): the topology with live traffic and
  drops per sw1 port, sw1's eight queues per port (packets/s, drops), Homa's counters per host (DATA, GRANT, RESEND,
  retransmissions, timeouts, packets by priority), sw1's policy (prio / FIFO / off) and Homa's resend timers (module
  default / ×10) switchable, the five measurements and the Robot suites (all or one) as runs with their results, and the
  last test report. `/metrics` exports the same counters for Prometheus; sign-in is the Lab Hub's.
- `tests/results_<date>_<time>/` keeps one folder per Robot run (`tests/results_latest` links the newest); the run of
  2026-10-14 (26/26) is committed.
### Changed
- Robot results moved from `results/<timestamp>/` to `tests/results_<date>_<time>/`; `results/latest` still links the
  newest run, where Lab Hub reads it.

## [0.1.1] - 2026-10-13
### Added
- Lab walkthrough PDF (`docs/homa-lab-walkthrough.pdf`), built from the live lab by `tools/build_walkthrough.py`
  (`--refresh` re-collects `docs/data/`).
- Slide deck `docs/homa-lab.pptx` (22 slides, speaker notes, native charts and tables from `docs/data/`), built by
  `docs/build_deck.py` with `docs/decklib.py` (from srv6-core); `docs/homa-lab-deck-preview.html` is its HTML replica.
- Walkthrough section 2, "Homa for dummies": the protocol in plain language, its benefits and drawbacks, TCP vs Homa.
### Fixed
- Walkthrough: unscheduled data described as in the current module (only messages up to unsched_bytes; longer ones
  are fully scheduled since September 2026).
- Captures are taken on sw1's port, not on the receiving host: Homa's GRO handler consumes many arriving GRANT/DATA
  packets before tcpdump's tap (`gro_*_bypasses`).
- Dissector: segment length from the reported packet length (was the snaplen); clearer label for the `urgent` marker.
- `lab.sh verify` shows sw1's bridge port states; `lab.sh homa status` shows link_mbps (the socket count was broken).
- README: TCP hijacking does not make small RPCs faster (the earlier comparison mixed link types).

## [0.1.0] - 2026-10-13
### Added
- Four Ubuntu 26.04 hosts on the mainline 6.17.8 kernel with HomaModule `main` @ 65cecd7 (`homa.ko` + `util/`), built
  and unit-tested (840/840) by `tools/build_image.sh` in a builder VM.
- sw1: a Linux bridge whose host ports model a top-of-rack switch (`sw-qos`: 1 Gbit/s shaper, 8 strict priority queues
  by DSCP / traffic class, FIFO and off modes, random loss per port, JSON stats).
- Links as isolated libvirt bridges, MTU 9000; OOB network 10.8.0.0/24.
- Standing services: homa_prio, Homa echo servers (v4/v6), cp_node servers for Homa and TCP (bulk and probe).
- A Homa dissector for tshark/Wireshark (`image/homa.lua`), from the current wire format (protocol 146).
- `lab.sh`: image, up/down/wait, status/inventory, homa, qos, exec, verify, bench, test, ssh/console/log, rebuild/clean.
- `tools/homalab.py`: RTT matrix, Homa vs TCP, incast (prio vs FIFO), loss, capture, metrics.
- Robot suites 01-07: platform, function, wire, compare, incast, loss, timers.
