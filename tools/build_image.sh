#!/usr/bin/env bash
# Build images/homa-base.qcow2: the Ubuntu 26.04 cloud image, booted once as a builder VM (libvirt NAT network for the
# internet) that installs the mainline kernel, builds homa.ko + HomaModule's util/ against it, runs the unit tests and
# powers off (image/homa-build.sh). Every lab VM is an overlay on the result.   tools/build_image.sh [--force]
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/../lab.conf"
V() { virsh -q -c "$LIBVIRT_URI" "$@"; }
B=homa-builder; D="$LAB_DIR/images/builder"; CLOUD="$LAB_DIR/images/$(basename "$UBUNTU_IMAGE_URL")"
[[ -f "$BASE_IMAGE" && "${1:-}" != "--force" ]] && { echo "$BASE_IMAGE exists (--force to rebuild)"; exit 0; }
V dominfo "$B" &>/dev/null && { V destroy "$B" &>/dev/null || true; V undefine "$B" >/dev/null; }
mkdir -p "$D"

if [[ ! -f "$CLOUD" ]]; then echo "==> downloading $UBUNTU_IMAGE_URL"; curl -fL --progress-bar -o "$CLOUD.part" "$UBUNTU_IMAGE_URL"; mv "$CLOUD.part" "$CLOUD"; fi
echo "==> base disk ($BASE_DISK_GB GB)"
qemu-img convert -q -O qcow2 "$CLOUD" "$D/disk.qcow2"
qemu-img resize -q "$D/disk.qcow2" "${BASE_DISK_GB}G"

b64() { base64 -w0 "$1"; }
printf 'instance-id: homa-builder-%s\nlocal-hostname: homa-builder\n' "$(date +%s)" > "$D/meta-data"
cat > "$D/user-data" <<U
#cloud-config
hostname: homa-builder
users:
  - name: lab
    plain_text_passwd: lab
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
ssh_pwauth: true
write_files:
  - { path: /root/homa-build.sh,     permissions: '0755', encoding: b64, content: $(b64 "$LAB_DIR/image/homa-build.sh") }
  - { path: /root/sw-qos,            permissions: '0755', encoding: b64, content: $(b64 "$LAB_DIR/image/sw-qos") }
  - { path: /root/homa-prio.service, permissions: '0644', encoding: b64, content: $(b64 "$LAB_DIR/image/homa-prio.service") }
  - { path: /root/sw-qos.service,    permissions: '0644', encoding: b64, content: $(b64 "$LAB_DIR/image/sw-qos.service") }
  - { path: /root/homa.lua,          permissions: '0644', encoding: b64, content: $(b64 "$LAB_DIR/image/homa.lua") }
  - path: /root/homa-build.env
    content: |
      KERNEL_MAINLINE=$KERNEL_MAINLINE
      KERNEL_RELEASE=$KERNEL_RELEASE
      HOMA_REPO=$HOMA_REPO
      HOMA_COMMIT=$HOMA_COMMIT
runcmd:
  - [bash, -c, "/root/homa-build.sh > /var/log/homa-build.log 2>&1; rc=\$?; tail -60 /var/log/homa-build.log > /dev/ttyS0; echo HOMA-BUILD-RC=\$rc > /dev/ttyS0"]
power_state: { mode: poweroff, timeout: 60, condition: true }
U
genisoimage -quiet -o "$D/seed.iso" -V cidata -J -r "$D/user-data" "$D/meta-data"
: > "$D/console.log"; chmod 644 "$D/console.log"

cat > "$D/domain.xml" <<X
<domain type='kvm'>
  <name>$B</name>
  <title>homa-lab image builder</title>
  <memory unit='MiB'>$BUILDER_RAM_MIB</memory>
  <vcpu placement='static'>$BUILDER_VCPU</vcpu>
  <cpu mode='host-passthrough' check='none'/>
  <os><type arch='x86_64' machine='pc'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff><on_reboot>restart</on_reboot><on_crash>destroy</on_crash>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='$D/disk.qcow2'/><target dev='vda' bus='virtio'/></disk>
    <disk type='file' device='cdrom'><driver name='qemu' type='raw'/><source file='$D/seed.iso'/><target dev='hda' bus='ide'/><readonly/></disk>
    <interface type='network'><source network='$BUILDER_NET'/><model type='virtio'/></interface>
    <serial type='tcp'>
      <source mode='bind' host='127.0.0.1' service='$BUILDER_CONSOLE'/>
      <protocol type='raw'/>
      <log file='$D/console.log' append='on'/>
      <target port='0'/>
    </serial>
    <memballoon model='none'/>
  </devices>
</domain>
X
V define "$D/domain.xml" >/dev/null
V start "$B" >/dev/null
echo "==> builder running (console log: $D/console.log, console 127.0.0.1:$BUILDER_CONSOLE); waiting for it to power off (up to 60 min)"
for i in $(seq 720); do [[ "$(V domstate "$B" 2>/dev/null)" == "shut off" ]] && break; sleep 5; done
[[ "$(V domstate "$B")" == "shut off" ]] || { echo "error: builder still running after 60 min" >&2; exit 1; }
V undefine "$B" >/dev/null
grep -a -E 'HOMA-BUILD-OK|unit tests:|dissector:|HOMA-BUILD-RC' "$D/console.log" | tr -d '\r' | tail -6
grep -aq 'HOMA-BUILD-RC=0' "$D/console.log" || { echo "error: the build failed, see $D/console.log" >&2; exit 1; }
mv -f "$D/disk.qcow2" "$BASE_IMAGE"
cp -f "$D/console.log" "$LAB_DIR/images/build.log"
echo "==> $BASE_IMAGE ready (log: images/build.log)"
