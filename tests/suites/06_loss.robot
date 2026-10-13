*** Settings ***
Documentation     Loss recovery: sw1 drops 1 in 50 packets towards h1 (any type: data, grants, acks) while h2 runs 300
...               round trips of 20 KB with h1. Homa has no connection state to rebuild: the receiver notices missing
...               ranges and asks for them (RESEND), the sender retransmits. Every RPC must still complete, intact.
Resource          ../resources/common.resource
Suite Setup       Lab Setup
Suite Teardown    Switch Qos    loss    eth1    off

*** Test Cases ***
Every RPC completes through a lossy link
    ${r}=    Run Loss    n=50    count=300
    Set Suite Variable    ${LOSS}    ${r}
    Should Be True    ${r}[rtt][ok]    msg=${r}[rtt]
    Should Contain    ${r}[sw_filter]    random

The receiver asked for the missing data and the sender retransmitted it
    Should Be True    ${LOSS}[metrics][h1][packets_sent_RESEND] > 0    msg=h1 sent no RESEND: ${LOSS}[metrics]
    Should Be True    ${LOSS}[metrics][h2][resent_packets] > 0    msg=h2 retransmitted nothing: ${LOSS}[metrics]
    Should Be Equal As Integers    ${LOSS}[metrics][h2][rpc_timeouts]    0    msg=an RPC timed out on h2
