#!/bin/bash
# Runs once inside the image builder VM (tools/build_image.sh): mainline kernel, build tools, homa.ko + util/ built against
# that kernel, HomaModule's unit tests run, everything installed. Arguments come from /root/homa-build.env.
set -euxo pipefail
source /root/homa-build.env      # KERNEL_MAINLINE KERNEL_RELEASE HOMA_REPO HOMA_COMMIT
export DEBIAN_FRONTEND=noninteractive
KR="$KERNEL_RELEASE"

# --- no background upgrades: the kernel is pinned and the lab must not change under the tests
systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer || true
apt-get -y purge unattended-upgrades || true

apt-get update
echo "wireshark-common wireshark-common/install-setuid boolean true" | debconf-set-selections
apt-get install -y --no-install-recommends build-essential g++ git make bc flex bison libelf-dev libssl-dev dwarves zstd \
  ethtool tcpdump tshark iperf3 jq python3 iproute2 netcat-openbsd sysstat linux-tools-common kmod bridge-utils

# --- the mainline kernel HomaModule's main branch is developed against
mkdir -p /root/kernel && cd /root/kernel
base="https://kernel.ubuntu.com/mainline/$KERNEL_MAINLINE/amd64"
for f in $(curl -fsSL "$base/" | grep -oE 'href="[^"]+\.deb"' | sed 's/^href="//; s/"$//' | grep -E 'generic|_all\.deb' | sort -u); do
  curl -fsSLO "$base/$f"
done
ls -l
dpkg -i ./*.deb
[[ -d /lib/modules/$KR/build ]]
# boot it by name; keep the distro kernel installed (fallback) but stop it from being upgraded
cat > /etc/default/grub.d/99-homa-kernel.cfg <<G
GRUB_DEFAULT="Advanced options for Ubuntu>Ubuntu, with Linux $KR"
GRUB_TIMEOUT=1
GRUB_TIMEOUT_STYLE=menu
G
update-grub
grep -q "Ubuntu, with Linux $KR'" /boot/grub/grub.cfg
apt-mark hold $(dpkg-query -W -f '${Package}\n' 'linux-image-*' 'linux-modules-*' 'linux-headers-*' 'linux-virtual' 'linux-generic' 'linux-kvm' 2>/dev/null | sort -u) || true

# --- HomaModule at the pinned commit
git clone "$HOMA_REPO" /opt/HomaModule
cd /opt/HomaModule && git checkout -q "$HOMA_COMMIT" && git log -1 --format='%H %ci %s'
make -j"$(nproc)" LINUX_VERSION="$KR" KDIR="/lib/modules/$KR/build" all
modinfo ./homa.ko
install -D -m 0644 homa.ko "/lib/modules/$KR/updates/homa.ko"
depmod -a "$KR"

make -C util -j"$(nproc)"
for f in util/*; do [[ -f "$f" && -x "$f" ]] && install -m 0755 "$f" /usr/local/bin/; done
install -d /usr/local/share/man/man7 /usr/local/share/man/man2
install -m 0644 man/homa.7 /usr/local/share/man/man7/; install -m 0644 man/sendmsg.2 man/recvmsg.2 /usr/local/share/man/man2/
install -D -m 0644 homa.h /usr/local/include/homa.h

# unit tests: HomaModule's user-space harness over the module's sources (840 tests). Against the Ubuntu mainline headers it
# needs two adjustments the author's own kernel config doesn't: no __seg_gs per-cpu address space (mock.h redeclares
# current_task as a plain pointer) and CONFIG_TRACE_PREEMPT_TOGGLE (mock.c defines preempt_count_add/sub as functions).
cat > /opt/HomaModule/test/lab-kconfig.h <<'H'
#undef CONFIG_USE_X86_SEG_SUPPORT
#undef CONFIG_CC_HAS_NAMED_AS
#define CONFIG_TRACE_PREEMPT_TOGGLE 1
H
( cd test && make -j"$(nproc)" LINUX_VERSION="$KR" KDIR="/lib/modules/$KR/build" \
    CINCLUDES='-I. -I.. $(KERN_INCLUDES) -include $(KDIR)/include/linux/kconfig.h -include lab-kconfig.h' > /var/log/homa-unit-build.log 2>&1 \
  && ./unit > /var/log/homa-unit.log 2>&1 ) \
  && echo "unit tests: PASS ($(grep -oE '[0-9]+ / [0-9]+ tests passed' /var/log/homa-unit.log))" > /var/log/homa-unit.result \
  || echo "unit tests: FAIL" > /var/log/homa-unit.result
tail -5 /var/log/homa-unit.log || true

# Wireshark: HomaModule's dissector/ targets IP protocol 253 and the old header layout, so the lab ships its own Lua one
# (global plugin directory: the tshark AppArmor profile does not let it read ~/.local)
install -D -m 0644 /root/homa.lua /usr/lib/x86_64-linux-gnu/wireshark/plugins/homa.lua
tshark -G protocols 2>/dev/null | grep -qP '\thoma\t' && echo "dissector: homa.lua loaded"

# --- lab tools
install -m 0755 /root/sw-qos /usr/local/sbin/sw-qos
install -m 0644 /root/homa-prio.service /etc/systemd/system/homa-prio.service
install -m 0644 /root/sw-qos.service /etc/systemd/system/sw-qos.service
# the hosts' standing test servers (enabled by the host seed): Homa echo servers for homa_test (v4 :4100, v6 :4101,
# contents validated) and cp_node servers for the cluster workloads (Homa :4000, TCP :5000)
unit() {   # name description command
  cat > "/etc/systemd/system/$1.service" <<U
[Unit]
Description=$2
After=systemd-modules-load.service systemd-sysctl.service network-online.target
ConditionPathExists=/proc/sys/net/homa

[Service]
WorkingDirectory=/tmp
ExecStart=$3
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
U
}
unit homa-echo  "Homa echo server, IPv4 port 4100 (HomaModule util/server)" "/usr/local/bin/server --port 4100 --validate"
unit homa-echo6 "Homa echo server, IPv6 port 4101 (HomaModule util/server)" "/usr/local/bin/server --ipv6 --port 4101 --validate"
unit cp-homa    "cp_node server, Homa port 4000" "/usr/local/bin/cp_node server --protocol homa"
unit cp-tcp     "cp_node server, TCP port 5000" "/usr/local/bin/cp_node server --protocol tcp"
# separate server processes for latency probes, so a probe never waits behind bulk messages in the same server thread
unit cp-homa-probe "cp_node server for probes, Homa port 4010" "/usr/local/bin/cp_node server --protocol homa --first-port 4010"
unit cp-tcp-probe  "cp_node server for probes, TCP port 5010" "/usr/local/bin/cp_node server --protocol tcp --first-port 5010"
systemctl daemon-reload

# --- generalise: every overlay gets its own machine-id and runs cloud-init from its own seed
apt-get clean
cloud-init clean --logs
truncate -s 0 /etc/machine-id
rm -f /etc/ssh/ssh_host_*
echo "HOMA-BUILD-OK kernel=$KR homa=$HOMA_COMMIT $(cat /var/log/homa-unit.result)"
