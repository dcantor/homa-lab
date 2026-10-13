*** Settings ***
Documentation     The build under test: every host boots the pinned mainline kernel and runs the homa.ko built for it, the
...               module's own unit tests passed when the image was built, the lab's settings are in place, and sw1 is a
...               4-port bridge with the configured egress policy.
Resource          ../resources/common.resource
Suite Setup       Lab Setup

*** Test Cases ***
Every host runs the pinned kernel with homa.ko loaded from the lab build
    ${inv}=    Lab Inventory
    FOR    ${h}    IN    @{HOSTS}
        ${k}=    Run On    ${h}    uname -r
        Should Be Equal    ${k}    ${KERNEL}
        ${mod}=    Run On    ${h}    lsmod | awk '$1=="homa"{print $1}'
        Should Be Equal    ${mod}    homa    msg=${h}: homa is not loaded
        ${path}=    Run On    ${h}    modinfo -n homa
        Should Be Equal    ${path}    /lib/modules/${KERNEL}/updates/homa.ko
        ${loaded}=    Run On    ${h}    cat /sys/module/homa/srcversion
        ${built}=    Run On    ${h}    modinfo -F srcversion homa
        Should Be Equal    ${loaded}    ${built}    msg=${h}: the loaded module is not the installed build
        ${commit}=    Run On    ${h}    git -c safe.directory=/opt/HomaModule -C /opt/HomaModule rev-parse HEAD
        Should Be Equal    ${commit}    ${inv}[homa_commit]
    END

The module's unit tests passed in the image build
    ${r}=    Run On    h1    cat /var/log/homa-unit.result
    Should Match Regexp    ${r}    ^unit tests: PASS \\((\\d+) / \\1 tests passed\\)$

Homa's interfaces exist: sysctls, metrics, an IPPROTO 146 socket
    FOR    ${h}    IN    @{HOSTS}
        Run On    ${h}    test -d /proc/sys/net/homa && test -r /proc/net/homa_metrics
        ${mbps}=    Homa Sysctl    ${h}    link_mbps
        Should Be Equal    ${mbps}    1000    msg=${h}: link_mbps must match sw1's 1 Gbit/s ports
        ${n}=    Homa Sysctl    ${h}    num_priorities
        Should Be Equal    ${n}    8
        Run On    ${h}    python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 146); s.close()"
        Run On    ${h}    python3 -c "import socket; s=socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, 146); s.close()"
    END

The standing test servers and homa_prio run on every host
    FOR    ${h}    IN    @{HOSTS}
        Host Services Should Be Active    ${h}
    END

sw1 bridges its four ports at MTU 9000 with the configured egress policy
    ${inv}=    Lab Inventory
    ${ports}=    Run On    ${SWITCH}    bridge link show master br0 | grep -c 'state forwarding'
    Should Be Equal    ${ports}    4
    ${mtu}=    Run On    ${SWITCH}    cat /sys/class/net/br0/mtu
    Should Be Equal    ${mtu}    9000
    ${state}=    Run On    ${SWITCH}    cat /run/sw-qos.state
    Should Contain    ${state}    SW_QOS_MODE=${inv}[switch][qos][mode]
    Should Contain    ${state}    SW_QOS_RATE=${inv}[switch][qos][rate]
    ${stats}=    Switch Qos Stats
    FOR    ${p}    IN    eth1    eth2    eth3    eth4
        Should Be Equal    ${stats}[${p}][mode]    ${inv}[switch][qos][mode]
    END
