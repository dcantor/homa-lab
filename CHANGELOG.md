# Changelog
All notable changes to this lab. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] - 2026-10-13
### Added
- Lab walkthrough PDF (`docs/homa-lab-walkthrough.pdf`), built from the live lab by `tools/build_walkthrough.py`
  (`--refresh` re-collects `docs/data/`).
### Fixed
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
