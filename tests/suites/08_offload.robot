*** Settings ***
Documentation     Segmentation offload, the investigation of 2026-10-14 kept as tests (round trips h2 -> h1, 1 KB / 10 KB /
...               1 MB). Homa can hand its NIC frames larger than the MTU two ways: as native GSO frames (max_gso_size),
...               or disguised as TCP so the NIC's TSO cuts them (hijack_tcp). In this lab the "NIC" is virtio, and:
...               - a native GSO frame given to the virtio NIC reaches the lab host, which must segment it for sw1 and
...               cannot (it has no Homa): the frame is dropped there. With the guests' TSO off, the guest kernel
...               segments it with Homa's own homa_gso_segment, and every size works.
...               - TCP hijacking loses every full-size packet at the receiver: the module's GRO hook reads the TCP
...               header with skb_transport_header() before the header is in the linear part of the skb (virtio puts it
...               in a page fragment), misreads it, and hands the packet to TCP, which drops it (reason TCP_RESET). A
...               fix is in patches/0001-hijack-gro-read-header-from-frag0.patch. The hijack test below expects the
...               bug: when it fails, the pinned module no longer has it.
Resource          ../resources/common.resource
Suite Setup       Lab Setup
Force Tags        offload

*** Test Cases ***
Default settings: every size works, one frame per packet
    ${r}=    Run Offload    default
    FOR    ${size}    IN    1000    10000    1000000
        Should Be True    ${r}[default][${size}][ok]    msg=${size} B: ${r}[default][${size}]
    END
    Should Be Equal As Integers    ${r}[default][1000000][frames_sent]    ${r}[default][1000000][packets_received]

Native GSO works when the guest segments (TSO off on the virtio NIC)
    ${r}=    Run Offload    gso_guest
    FOR    ${size}    IN    1000    10000    1000000
        Should Be True    ${r}[gso_guest][${size}][ok]    msg=${size} B: ${r}[gso_guest][${size}]
    END
    Should Be True    ${r}[gso_guest][1000000][frames_sent] * 4 < ${r}[gso_guest][1000000][packets_received]
    ...    msg=expected GSO frames of several packets: ${r}[gso_guest][1000000]

Native GSO through the virtio NIC's TSO is lost on the lab host
    ${r}=    Run Offload    gso    sizes=1000,10000
    Should Be True    ${r}[gso][1000][ok]    msg=one-packet messages need no segmentation: ${r}[gso][1000]
    Should Not Be True    ${r}[gso][10000][ok]    msg=a GSO frame got through the lab host: ${r}[gso][10000]
    Should Be Equal As Integers    ${r}[gso][10000][packets_received]    0

Known module bug: TCP hijacking loses full-size packets on a virtio receiver
    [Tags]    known-bug
    ${r}=    Run Offload    hijack    sizes=1000,10000
    Should Be True    ${r}[hijack][1000][ok]    msg=short hijacked messages should work: ${r}[hijack][1000]
    Should Not Be True    ${r}[hijack][10000][ok]
    ...    msg=hijacked 10 KB messages work now: the pinned module may have the GRO fix; update this test and the README
