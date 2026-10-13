*** Settings ***
Documentation     Incast at h1: h2 and h3 stream 500 KB messages to h1 (twice what h1's 1 Gbit/s port at sw1 can take)
...               while h4 sends 100 B probes to h1, one at a time, to separate server processes. Once with sw1's strict
...               priority queues, once with one FIFO queue; Homa, then TCP. Homa's short messages go at the top
...               priority, so with priority queues they pass the bulk data queued at the bottleneck — the effect Homa is
...               designed around. TCP marks everything priority 0 and gets no such help.
Resource          ../resources/common.resource
Suite Setup       Run Keywords    Lab Setup    AND    Incast
Suite Teardown    Restore Switch Default

*** Keywords ***
Incast
    ${r}=    Run Incast    modes=prio,fifo    protocols=homa,tcp    seconds=10    rate_mbit=1000
    Set Suite Variable    ${R}    ${r}

*** Test Cases ***
The bulk senders saturate h1's port in every run
    FOR    ${k}    IN    prio_homa    fifo_homa    prio_tcp    fifo_tcp
        Should Be True    ${R}[${k}][bulk_mbit] > 600    msg=${k}: bulk only ${R}[${k}][bulk_mbit] Mbit/s
        Should Be True    ${R}[${k}][probe_loaded][n] > 50    msg=${k}: too few probe samples
    END

With priority queues, Homa's short messages pass the queued bulk data
    ${prio}=    Set Variable    ${R}[prio_homa][probe_loaded][p99]
    ${fifo}=    Set Variable    ${R}[fifo_homa][probe_loaded][p99]
    Log    Homa probe p99 under incast: priority queues ${prio} us, one FIFO ${fifo} us
    Should Be True    ${prio} < ${fifo}    msg=priority queues did not help Homa: ${prio} us vs ${fifo} us
    Should Be True    ${R}[prio_homa][probe_loaded][p50] < ${R}[fifo_homa][probe_loaded][p50] / 3

Under incast Homa's short messages beat TCP's: 10x at the median, 3x at p99
    # Homa's p99 here varies run to run (1.5-4.5 ms): it includes the spurious-RESEND episodes suite 07 documents
    ${h50}=    Set Variable    ${R}[prio_homa][probe_loaded][p50]
    ${t50}=    Set Variable    ${R}[prio_tcp][probe_loaded][p50]
    ${h99}=    Set Variable    ${R}[prio_homa][probe_loaded][p99]
    ${t99}=    Set Variable    ${R}[prio_tcp][probe_loaded][p99]
    Log    probe RTT under incast with priority queues: Homa p50 ${h50} / p99 ${h99} us, TCP p50 ${t50} / p99 ${t99} us
    Should Be True    ${h50} * 10 < ${t50}    msg=median: Homa ${h50} us vs TCP ${t50} us
    Should Be True    ${h99} * 3 < ${t99}    msg=p99: Homa ${h99} us vs TCP ${t99} us

Homa's packets used several of sw1's priority queues, TCP's only the lowest
    ${homa}=    Get Dictionary Keys    ${R}[prio_homa][sw_band_packets]
    ${n}=    Get Length    ${homa}
    Should Be True    ${n} >= 3    msg=Homa used ${homa}
    ${b}=    Set Variable    ${R}[prio_tcp][sw_band_packets]
    ${total}=    Evaluate    sum(${b}.values())
    ${low}=    Evaluate    ${b}.get('0', 0)
    Should Be True    ${low} >= ${total} * 0.99    msg=TCP outside the lowest queue: ${b}
