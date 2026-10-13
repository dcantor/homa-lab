*** Settings ***
Documentation     Homa works end to end: jumbo frames through sw1, a Homa round trip between every pair of hosts over IPv4
...               and IPv6 (contents validated by the echo servers), message sizes from 8 bytes (the echo protocol's own
...               header: the second word is the reply length) to Homa's 1 MB maximum, and the module's lifecycle (it
...               refuses to unload while sockets are open, unloads, and the kernel loads it again on the first
...               IPPROTO 146 socket).
Resource          ../resources/common.resource
Suite Setup       Lab Setup

*** Test Cases ***
Jumbo frames cross sw1 unfragmented between every pair, IPv4 and IPv6
    FOR    ${a}    IN    @{HOSTS}
        FOR    ${b}    IN    @{HOSTS}
            IF    '${a}' == '${b}'    CONTINUE
            ${ip}=    Data Ip    ${b}
            ${ip6}=    Data Ip    ${b}    ipv6=${True}
            Run On    ${a}    ping -q -c2 -i0.2 -W1 -M do -s 8972 ${ip}
            Run On    ${a}    ping -6 -q -c2 -i0.2 -W1 -M do -s 8952 ${ip6}
        END
    END

A Homa round trip succeeds between every pair of hosts, IPv4 and IPv6, 100 B and 100 KB
    ${r}    ${bad}=    Homa Rtt Matrix    count=20
    Should Be Empty    ${bad}    msg=failed: ${bad}
    Should Be Equal As Integers    ${r}[total]    48

Message sizes from 8 bytes to the 1 MB maximum arrive intact
    FOR    ${len}    IN    8    1400    8900    9000    40000    100000    500000    1000000
        ${r}=    Homa Rtt    h1    h3    length=${len}    count=10
        Should Be True    ${r}[ok]    msg=${len} B: ${r}
    END
    ${errors}=    Run On    h3    sudo journalctl -q -u homa-echo --since -5min --no-pager | grep -ci -E 'error|mismatch|invalid' || true
    Should Be Equal    ${errors}    0    msg=the echo server on h3 reported content errors

The module refuses to unload while Homa sockets are open
    ${rc}    ${out}=    Run On Rc    h4    sudo modprobe -r homa
    Should Not Be Equal As Integers    ${rc}    0
    Should Contain    ${out}    in use

The module unloads cleanly, and the first Homa socket loads it again
    Run On    h4    sudo systemctl stop ${SERVICES}[0] ${SERVICES}[1] ${SERVICES}[2] ${SERVICES}[3] ${SERVICES}[4] ${SERVICES}[5] ${SERVICES}[6]
    Run On    h4    sudo modprobe -r homa
    Run On    h4    ! test -e /proc/net/homa_metrics && ! lsmod | grep -q '^homa '
    ${r}=    Homa Rtt    h1    h4    count=3
    Should Not Be True    ${r}[ok]    msg=h4 answered Homa with the module unloaded
    # the module declares MODULE_ALIAS_NET_PF_PROTO_TYPE: socket(AF_INET, SOCK_DGRAM, 146) makes the kernel load it
    Run On    h4    python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 146).close()"
    Run On    h4    lsmod | grep -q '^homa '
    Run On    h4    sudo sysctl -q -p /etc/sysctl.d/90-homa.conf
    Run On    h4    sudo systemctl start ${SERVICES}[0] ${SERVICES}[1] ${SERVICES}[2] ${SERVICES}[3] ${SERVICES}[4] ${SERVICES}[5] ${SERVICES}[6]
    Sleep    2s
    Host Services Should Be Active    h4
    ${r}=    Homa Rtt    h1    h4    count=20
    Should Be True    ${r}[ok]    msg=${r}
    [Teardown]    Run On    h4    sudo modprobe homa; sudo sysctl -q -p /etc/sysctl.d/90-homa.conf; sudo systemctl start ${SERVICES}[0] ${SERVICES}[1] ${SERVICES}[2] ${SERVICES}[3] ${SERVICES}[4] ${SERVICES}[5] ${SERVICES}[6]    expect_rc=any
