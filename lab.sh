#!/usr/bin/env bash
# Homa lab controller (libvirt/KVM): four Linux hosts with the Homa kernel module and a Linux switch, see lab.conf
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lab.conf"

# Re-exec under the libvirt group if this login session doesn't have it yet.
if ! id -nG | tr ' ' '\n' | grep -qx libvirt && getent group libvirt | grep -qw "${USER:-$(id -un)}"; then
  exec sg libvirt -c "$(printf '%q ' "$0" "$@")"
fi

V() { virsh -q -c "$LIBVIRT_URI" "$@"; }
die() { echo "error: $*" >&2; exit 1; }
dom() { echo "homa-$1"; }                       # libvirt domain names are host-global (another lab has a sw1)
node_dir() { echo "$LAB_DIR/nodes/$1"; }
defined() { V dominfo "$(dom "$1")" &>/dev/null; }
running() { [[ "$(V domstate "$(dom "$1")" 2>/dev/null)" == "running" ]]; }
known() { [[ -n "${ROLE[$1]:-}" ]] || die "unknown node $1 (nodes: ${ALL_NODES[*]})"; }
nodes_or_all() { local n; if [[ $# -gt 0 ]]; then for n in "$@"; do known "$n"; done; echo "$*"; else echo "${ALL_NODES[*]}"; fi; }
hosts_or_all() { [[ $# -gt 0 ]] && echo "$*" || echo "${HOSTS[*]}"; }
mac() { printf '%s:%02x:%02x' "$MAC_OUI" "${NODE_IDX[$1]}" "$2"; }
host_on_port() { local h; for h in "${HOSTS[@]}"; do [[ "${SW_PORT[$h]}" == "$1" ]] && { echo "$h"; return; }; done; }
PUBKEY="$(cat "${HOMA_LAB_PUBKEY:-$HOME/.ssh/id_ed25519.pub}" 2>/dev/null || true)"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5)
S() { local n="$1"; shift; ssh "${SSH_OPTS[@]}" "lab@${MGMT_IP[$n]}" "$@"; }   # run a command on a node (key auth)
ssh_ready() { timeout 8 bash -c "exec 3<>/dev/tcp/${MGMT_IP[$1]}/22" 2>/dev/null; }
PY="$LAB_DIR/tests/.venv/bin/python"; [[ -x "$PY" ]] || PY=python3
need_python() { [[ -x "$LAB_DIR/tests/.venv/bin/python" ]] || "$LAB_DIR/tests/setup.sh"; PY="$LAB_DIR/tests/.venv/bin/python"; }

ensure_network() {   # the OOB network and one isolated bridge per host <-> sw1 link (networks/*.xml)
  local n; for n in "$OOB_NET" $(link_nets); do
    V net-info "$n" &>/dev/null || { V net-define "$LAB_DIR/networks/$n.xml" >/dev/null; V net-autostart "$n" >/dev/null; }
    [[ "$(V net-info "$n" | awk '/Active/{print $2}')" == "yes" ]] || V net-start "$n" >/dev/null
  done
}
link_net() { echo "homa-link${SW_PORT[$1]}"; }        # host -> its link network (= its sw1 port number)
link_nets() { local h; for h in "${HOSTS[@]}"; do link_net "$h"; done; }

# ---- XML ------------------------------------------------------------------------------------------------------------
link_nic_xml() {   # slot mac network comment
  cat <<X
    <!-- $4 -->
    <interface type='network'>
      <mac address='$2'/>
      <source network='$3'/>
      <model type='virtio'/>
      <mtu size='$DATA_MTU'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='$(printf '0x%02x' "$1")' function='0x0'/>
    </interface>
X
}

domain_xml() {
  local n="$1" d p h; d="$(node_dir "$n")"
  cat <<X
<domain type='kvm'>
  <name>$(dom "$n")</name>
  <uuid>$(uuidgen --sha1 --namespace @dns --name "homa-lab.${MGMT_IP[$n]}")</uuid>
  <title>homa-lab ${ROLE[$n]} $n</title>
  <memory unit='MiB'>${RAM_MIB[$n]}</memory>
  <vcpu placement='static'>${VCPU[$n]}</vcpu>
  <cpu mode='host-passthrough' check='none'/>
  <os><type arch='x86_64' machine='pc'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff><on_reboot>restart</on_reboot><on_crash>restart</on_crash>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'><driver name='qemu' type='qcow2'/><source file='$d/disk.qcow2'/><target dev='vda' bus='virtio'/></disk>
    <disk type='file' device='cdrom'><driver name='qemu' type='raw'/><source file='$d/seed.iso'/><target dev='hda' bus='ide'/><readonly/></disk>
    <!-- eth0: OOB ${MGMT_IP[$n]} -->
    <interface type='network'>
      <mac address='$(mac "$n" 0)'/>
      <source network='$OOB_NET'/>
      <model type='virtio'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x03' function='0x0'/>
    </interface>
X
  if [[ "${ROLE[$n]}" == host ]]; then
    link_nic_xml 4 "$(mac "$n" 1)" "$(link_net "$n")" "eth1: ${DATA_IP[$n]} <-> $SWITCH eth${SW_PORT[$n]} over $(link_net "$n")"
  else
    for p in $(seq 1 "$SW_PORTS"); do
      h="$(host_on_port "$p")"; [[ -n "$h" ]] || die "sw1 eth$p has no host (SW_PORT)"
      link_nic_xml $((3 + p)) "$(mac "$n" "$p")" "$(link_net "$h")" "eth$p: <-> $h eth1 over $(link_net "$h")"
    done
  fi
  cat <<X
    <serial type='tcp'>
      <source mode='bind' host='127.0.0.1' service='${CONSOLE_PORT[$n]}'/>
      <protocol type='raw'/>
      <log file='$d/console.log' append='on'/>
      <target port='0'/>
    </serial>
    <memballoon model='none'/>
  </devices>
</domain>
X
}

# ---- cloud-init seeds -------------------------------------------------------------------------------------------------
user_head() {   # node: the user-data common to every node
  cat <<U
#cloud-config
hostname: $1
manage_etc_hosts: false
users:
  - name: lab
    plain_text_passwd: lab
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys: ["$PUBKEY"]
ssh_pwauth: true
U
}

etc_hosts() {   # every node knows the hosts by name on the data network (h1..h4, and nodeN for HomaModule's cp_node)
  local h; echo "127.0.0.1 localhost"; echo "127.0.1.1 $1"
  for h in "${HOSTS[@]}"; do echo "${DATA_IP[$h]} $h node${NODE_IDX[$h]}"; echo "${DATA_IP6[$h]} $h-v6"; done
  for h in "${ALL_NODES[@]}"; do echo "${MGMT_IP[$h]} $h-oob"; done
}

host_seed() {
  local n="$1" d; d="$(node_dir "$n")"
  cat > "$d/network-config" <<U
version: 2
ethernets:
  oob:
    match: { macaddress: "$(mac "$n" 0)" }
    set-name: eth0
    addresses: [${MGMT_IP[$n]}/24]
    routes: [{ to: 10.0.0.0/8, via: $OOB_GATEWAY }]
  data:
    match: { macaddress: "$(mac "$n" 1)" }
    set-name: eth1
    mtu: $DATA_MTU
    addresses: [${DATA_IP[$n]}/${DATA_PREFIX4#*/}, "${DATA_IP6[$n]}/${DATA_PREFIX6#*/}"]
    accept-ra: false
U
  { user_head "$n"; cat <<U
write_files:
  - path: /etc/hosts
    content: |
$(etc_hosts "$n" | sed 's/^/      /')
  - path: /etc/modules-load.d/homa.conf
    content: "homa\n"
  - path: /etc/sysctl.d/90-homa.conf
    content: |
$(for kv in "${HOMA_SYSCTL[@]}"; do echo "      net.homa.${kv%%=*} = ${kv#*=}"; done)
  - path: /etc/motd
    content: "$n: Homa host. eth1 ${DATA_IP[$n]} / ${DATA_IP6[$n]} (sw1 eth${SW_PORT[$n]}), OOB eth0 ${MGMT_IP[$n]}. Kernel $KERNEL_RELEASE, homa.ko from HomaModule ${HOMA_COMMIT:0:7}; cp_node, homa_test, homa_prio in /usr/local/bin; sources in /opt/HomaModule.\n"
runcmd:
  - [modprobe, homa]
  - [sysctl, -p, /etc/sysctl.d/90-homa.conf]
  - [systemctl, enable, --now, $(IFS=,; echo "${HOST_SERVICES[*]}" | sed "s/,/, /g")]
  - [bash, -c, "$([[ "$HOMA_PRIO" == 1 ]] && echo 'systemctl enable --now homa-prio' || echo 'systemctl disable --now homa-prio || true')"]
U
  } > "$d/user-data"
}

switch_seed() {
  local n="$1" d p ifs=""; d="$(node_dir "$n")"
  {
    cat <<U
version: 2
ethernets:
  oob:
    match: { macaddress: "$(mac "$n" 0)" }
    set-name: eth0
    addresses: [${MGMT_IP[$n]}/24]
    routes: [{ to: 10.0.0.0/8, via: $OOB_GATEWAY }]
U
    for p in $(seq 1 "$SW_PORTS"); do
      printf '  eth%s:\n    match: { macaddress: "%s" }\n    set-name: eth%s\n    mtu: %s\n    optional: true\n' "$p" "$(mac "$n" "$p")" "$p" "$DATA_MTU"
      ifs+="${ifs:+, }eth$p"
    done
    cat <<U
bridges:
  br0:
    interfaces: [$ifs]
    mtu: $DATA_MTU
    parameters: { stp: false, forward-delay: 0 }
    link-local: []
    accept-ra: false
U
  } > "$d/network-config"
  { user_head "$n"; cat <<U
write_files:
  - path: /etc/hosts
    content: |
$(etc_hosts "$n" | sed 's/^/      /')
  - path: /etc/default/sw-qos
    content: |
      SW_QOS_MODE=$SW_QOS_MODE
      SW_QOS_RATE=$SW_QOS_RATE
      SW_QOS_LIMIT=$SW_QOS_LIMIT
  - path: /etc/motd
    content: "sw1: Linux bridge br0 over eth1-eth$SW_PORTS (h1-h4). Egress policy: sudo sw-qos show | apply prio|fifo|off RATE LIMIT | loss PORT N|off | stats\n"
runcmd:
  - [systemctl, disable, --now, homa-prio]
  - [systemctl, enable, --now, sw-qos]
U
  } > "$d/user-data"
}

build() {
  local n="$1" d; d="$(node_dir "$n")"
  [[ -f "$BASE_IMAGE" ]] || die "base image missing: $BASE_IMAGE (lab.sh image)"
  [[ -n "$PUBKEY" ]] || die "no SSH public key (~/.ssh/id_ed25519.pub or HOMA_LAB_PUBKEY)"
  mkdir -p "$d"
  [[ -f "$d/disk.qcow2" ]] || { echo "[$n] creating overlay disk"; qemu-img create -q -f qcow2 -b "$BASE_IMAGE" -F qcow2 "$d/disk.qcow2"; }
  printf 'instance-id: %s-%s\nlocal-hostname: %s\n' "$n" "$(md5sum <<<"$HOMA_COMMIT$KERNEL_RELEASE" | cut -c1-8)" "$n" > "$d/meta-data"
  if [[ "${ROLE[$n]}" == host ]]; then host_seed "$n"; else switch_seed "$n"; fi
  genisoimage -quiet -o "$d/seed.iso.tmp" -V cidata -J -r "$d/user-data" "$d/meta-data" "$d/network-config" && mv -f "$d/seed.iso.tmp" "$d/seed.iso"
  domain_xml "$n" > "$d/domain.xml"
  V define "$d/domain.xml" >/dev/null
}

# ---- commands ---------------------------------------------------------------------------------------------------------
cmd_image() { "$LAB_DIR/tools/build_image.sh" "$@"; }

cmd_up() {
  ensure_network
  local n; for n in $(nodes_or_all "$@"); do
    defined "$n" || build "$n"
    [[ -f "$(node_dir "$n")/console.log" ]] || { touch "$(node_dir "$n")/console.log"; chmod 644 "$(node_dir "$n")/console.log"; }
    if running "$n"; then echo "[$n] already running"; else V start "$(dom "$n")" >/dev/null; echo "[$n] started (console: 127.0.0.1:${CONSOLE_PORT[$n]})"; fi
  done
}

cmd_down() {
  local n; for n in $(nodes_or_all "$@"); do
    running "$n" || { echo "[$n] not running"; continue; }
    V shutdown "$(dom "$n")" >/dev/null 2>&1 || true
    for _ in $(seq 30); do running "$n" || break; sleep 2; done
    running "$n" && V destroy "$(dom "$n")" >/dev/null; echo "[$n] stopped"
  done
}

cmd_wait() {   # SSH answering and cloud-init finished
  local n; for n in $(nodes_or_all "$@"); do
    for _ in $(seq 90); do ssh_ready "$n" && S "$n" true 2>/dev/null && break; sleep 4; done   # login refused until boot ends (pam_nologin)
    if S "$n" "cloud-init status --wait >/dev/null 2>&1; true" 2>/dev/null; then echo "[$n] ready"; else echo "[$n] NOT ready"; fi
  done
}

cmd_rebuild() {   # re-define domains and seeds from lab.conf (keeps disks)
  local n; for n in $(nodes_or_all "$@"); do running "$n" && die "$n is running; stop it first"
    defined "$n" && V undefine "$(dom "$n")" >/dev/null; build "$n"; echo "[$n] redefined"; done
}

cmd_clean() {     # stop, undefine, delete overlays (the base image stays)
  local n; for n in $(nodes_or_all "$@"); do
    running "$n" && V destroy "$(dom "$n")" >/dev/null; defined "$n" && V undefine "$(dom "$n")" >/dev/null
    rm -f "$(node_dir "$n")"/{disk.qcow2,seed.iso,seed.iso.tmp,meta-data,user-data,network-config,domain.xml,console.log}; echo "[$n] removed"
  done
}

cmd_status() {
  printf '%-4s %-7s %-10s %-11s %-15s %-15s %-8s %s\n' NODE ROLE STATE MGMT-IP DATA-IP DATA-IP6 CONSOLE VM
  local n st; for n in "${ALL_NODES[@]}"; do
    st="$(V domstate "$(dom "$n")" 2>/dev/null || echo undefined)"
    printf '%-4s %-7s %-10s %-11s %-15s %-15s %-8s %s\n' "$n" "${ROLE[$n]}" "$st" "${MGMT_IP[$n]}" "${DATA_IP[$n]:--}" "${DATA_IP6[$n]:--}" "${CONSOLE_PORT[$n]}" "$(dom "$n")"
  done
  echo; echo "links (isolated libvirt bridges, MTU $DATA_MTU):"
  for n in "${HOSTS[@]}"; do echo "  $n eth1 ${DATA_IP[$n]}  <->  $SWITCH eth${SW_PORT[$n]}   ($(link_net "$n"))"; done
  echo; echo "image: $(basename "$BASE_IMAGE") — kernel $KERNEL_RELEASE, HomaModule ${HOMA_COMMIT:0:7}; sw1 default policy: $SW_QOS_MODE $SW_QOS_RATE"
}

cmd_inventory() {
  local n first=1
  {
    printf '{"lab": "homa-lab", "kernel": "%s", "homa_commit": "%s", "data": {"prefix4": "%s", "prefix6": "%s", "mtu": %s}, "switch": {"name": "%s", "mgmt_ip": "%s", "ports": %s, "qos": {"mode": "%s", "rate": "%s", "limit": %s}}, "hosts": [' \
      "$KERNEL_RELEASE" "$HOMA_COMMIT" "$DATA_PREFIX4" "$DATA_PREFIX6" "$DATA_MTU" "$SWITCH" "${MGMT_IP[$SWITCH]}" "$SW_PORTS" "$SW_QOS_MODE" "$SW_QOS_RATE" "$SW_QOS_LIMIT"
    for n in "${HOSTS[@]}"; do [[ $first -eq 1 ]] || printf ','; first=0
      printf '{"name": "%s", "mgmt_ip": "%s", "ip": "%s", "ip6": "%s", "sw_port": "eth%s", "idx": %s, "domain": "%s"}' "$n" "${MGMT_IP[$n]}" "${DATA_IP[$n]}" "${DATA_IP6[$n]}" "${SW_PORT[$n]}" "${NODE_IDX[$n]}" "$(dom "$n")"
    done
    echo ']}'
  } | python3 -m json.tool
}

cmd_console() { local n="${1:?node}"; known "$n"; running "$n" || die "$n is not running"; echo "console $n (exit: Ctrl-] then q)"; socat -,raw,echo=0,escape=0x1d "tcp:127.0.0.1:${CONSOLE_PORT[$n]}"; }
cmd_ssh() { local n="${1:?node}"; shift; known "$n"; ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "lab@${MGMT_IP[$n]}" "$@"; }
cmd_log() { tail -n "${2:-50}" -f "$(node_dir "${1:?node}")/console.log"; }
cmd_exec() {   # exec <node|all|hosts> <command...>: run on one node or in parallel on several, output prefixed
  local t="${1:?node|all|hosts}"; shift; local ns n
  case "$t" in all) ns="${ALL_NODES[*]}";; hosts) ns="${HOSTS[*]}";; *) known "$t"; S "$t" "$@"; return;; esac
  for n in $ns; do ( S "$n" "$@" 2>&1 | sed "s/^/[$n] /" ) & done; wait
}

cmd_homa() {   # status | load | unload | reload | sysctl [name[=value]..] | metrics [host]
  local sub="${1:-status}"; shift || true; local h
  case "$sub" in
    status)
      for h in $(hosts_or_all "$@"); do
        S "$h" 'printf "%-3s kernel %s  homa %s  homa_prio %s  sockets %s\n" "$(hostname)" "$(uname -r)" "$(lsmod | awk "/^homa /{print \"loaded (\" \$2 \" B)\"}" | grep . || echo "NOT loaded")" "$(systemctl is-active homa-prio)" "$(grep -c . /proc/net/homa_metrics 2>/dev/null >/dev/null && sudo ss -A all -a 2>/dev/null | grep -ci homa || echo 0)"' 2>/dev/null || echo "$h unreachable"
      done ;;
    load)   cmd_exec hosts 'sudo modprobe homa && sudo systemctl start homa-prio; lsmod | grep -c "^homa "' ;;
    unload) cmd_exec hosts 'sudo systemctl stop homa-prio; sudo modprobe -r homa && echo unloaded' ;;
    reload) cmd_homa unload; cmd_homa load ;;
    sysctl)
      if [[ $# -eq 0 ]]; then S h1 'sudo sysctl net.homa' ; else local kv; for kv in "$@"; do cmd_exec hosts "sudo sysctl -w net.homa.${kv#net.homa.}"; done; fi ;;
    metrics) S "${1:-h1}" 'cat /proc/net/homa_metrics' ;;
    *) die "usage: lab.sh homa status | load | unload | reload | sysctl [name[=value]..] | metrics [host]" ;;
  esac
}

cmd_qos() { S "$SWITCH" sudo sw-qos "$@"; }

cmd_verify() {   # quick end-to-end look: kernel + module, sw1 policy, jumbo reachability v4/v6, one Homa RPC per pair
  echo "== hosts"; cmd_homa status
  echo; echo "== sw1 egress policy"; S "$SWITCH" 'cat /run/sw-qos.state 2>/dev/null; bridge link | awk "{print \$2, \$NF}"'
  echo; echo "== data plane: 8972-byte unfragmentable pings (MTU $DATA_MTU), IPv4 and IPv6"
  local a b r4 r6 ok=0 tot=0
  for a in "${HOSTS[@]}"; do for b in "${HOSTS[@]}"; do [[ "$a" == "$b" ]] && continue; tot=$((tot + 1))
    r4="$(S "$a" "ping -c2 -i0.2 -W1 -M do -s 8972 -q ${DATA_IP[$b]} >/dev/null && echo ok || echo FAIL")"
    r6="$(S "$a" "ping -6 -c2 -i0.2 -W1 -M do -s 8952 -q ${DATA_IP6[$b]} >/dev/null && echo ok || echo FAIL")"
    [[ "$r4" == ok && "$r6" == ok ]] && ok=$((ok + 1)); printf '  %s -> %s  v4 %s  v6 %s\n' "$a" "$b" "$r4" "$r6"
  done; done; echo "  $ok/$tot pairs ok"
  echo; echo "== Homa: round trips between every pair, IPv4 and IPv6, 100 B and 100 KB (homa_test -> the echo servers)"
  python3 "$LAB_DIR/tools/homalab.py" matrix > /dev/null
}

cmd_bench() {   # tools/homalab.py: rtt | compare | incast | loss | capture | metrics (JSON on stdout, summary on stderr)
  python3 "$LAB_DIR/tools/homalab.py" "$@"
}

cmd_test() {
  [[ -x "$LAB_DIR/tests/.venv/bin/robot" ]] || "$LAB_DIR/tests/setup.sh"
  exec "$LAB_DIR/tests/run.sh" "$@"
}

usage() {
  cat <<U
usage: $(basename "$0") <command> [node...]
  image [--force]      build images/homa-base.qcow2 (Ubuntu 26.04 + kernel $KERNEL_RELEASE + homa.ko ${HOMA_COMMIT:0:7}), ~20 min
  up [node..]          create (if needed) and start the VMs (default: all)
  wait [node..]        until SSH answers and cloud-init is done
  down [node..]        shut the VMs down
  status | inventory   nodes, addresses, links | the lab as JSON
  homa status|load|unload|reload|sysctl [k[=v]..]|metrics [host]   the module on the hosts
  qos <args>           sw1's egress policy: show | apply prio|fifo|off [RATE] [LIMIT] [PORT..] | loss PORT N|off | stats
  exec <node|hosts|all> <cmd>   run a command (hosts/all: in parallel)
  bench <sub> [opts]   rtt SRC DST | compare | incast | loss | capture | metrics HOST  (tools/homalab.py --help)
  verify               module + kernel, sw1 policy, jumbo ping matrix v4/v6, one Homa RPC per host pair
  test [robot args]    Robot Framework suites, results/<timestamp>/
  ssh <node> [cmd] | console <node> | log <node> [n]
  rebuild [node..]     re-define domains and cloud-init seeds (keeps disks; stop the nodes first)
  clean [node..]       destroy VMs and delete their disks (base image kept)
nodes: ${ALL_NODES[*]}   (libvirt domains homa-<node>; user lab / lab, your SSH key installed)
U
}

cmd="${1:-}"; shift || true
case "$cmd" in
  image|up|down|wait|status|inventory|homa|qos|exec|verify|bench|test|ssh|console|log|rebuild|clean) "cmd_$cmd" "$@" ;;
  *) usage; exit 1 ;;
esac
