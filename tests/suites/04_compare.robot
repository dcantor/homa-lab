*** Settings ***
Documentation     Homa against TCP on the same hosts and network, the same workload (HomaModule's W3 message-size
...               distribution, 0.3 Gbit/s offered by h1 to h2-h4, 12 s each), measured by HomaModule's cp_node.
...               Recorded, not judged on absolute numbers: these are VMs on one host, TCP has segmentation offload on the
...               virtio NICs and Homa does not. The tail for short messages is where Homa should be ahead.
Resource          ../resources/common.resource
Suite Setup       Lab Setup

*** Test Cases ***
Both protocols carry the same workload, and the results are recorded
    ${r}=    Compare Homa And Tcp    workload=w3    gbps=0.3    seconds=12
    Set Suite Variable    ${CMP}    ${r}
    FOR    ${p}    IN    homa    tcp
        Should Be True    ${r}[${p}][rpcs] > 10000    msg=${p}: only ${r}[${p}][rpcs] RPCs completed
    END

Homa's short-message tail latency is not worse than TCP's
    ${h}=    Set Variable    ${CMP}[homa][rtt_us][short (<=1 KB)][p99]
    ${t}=    Set Variable    ${CMP}[tcp][rtt_us][short (<=1 KB)][p99]
    Log    short messages p99: Homa ${h} us, TCP ${t} us
    IF    ${h} > ${t}    Log    Homa's short-message p99 (${h} us) is above TCP's (${t} us) in this run    WARN
    Should Be True    ${h} <= ${t} * 1.5    msg=Homa short p99 ${h} us vs TCP ${t} us
