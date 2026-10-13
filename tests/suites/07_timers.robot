*** Settings ***
Documentation     A finding of this lab, kept as a test. Two senders push 500 KB messages into h1's 1 Gbit/s port. Homa's
...               SRPT grants put the message nearest completion at the top scheduled priority and park the others at
...               lower ones, which strict priority queues then starve for many milliseconds. Homa's resend timer
...               (resend_ticks = 5 ms of silence) assumes a 25-100 Gbit/s network where that never lasts so long: the
...               receiver asks for data that is only queued, the sender sends it again into the same starved queue, and
...               sw1 overflows and RPCs time out. Scaled to this link speed (x10) the spurious RESENDs mostly vanish.
Resource          ../resources/common.resource
Suite Setup       Lab Setup
Suite Teardown    Set Homa Sysctls    resend_ticks=5    resend_interval=5    timeout_ticks=100

*** Test Cases ***
Default timers: starved messages trigger spurious RESENDs
    Set Homa Sysctls    resend_ticks=5    resend_interval=5    timeout_ticks=100
    ${d}=    Incast Bulk    seconds=8
    Set Suite Variable    ${DEF}    ${d}
    Log    defaults: ${d}
    Should Be True    ${d}[resends] > 100    msg=expected spurious RESENDs with the default timers: ${d}

Timers scaled to the link speed: no drops, no timeouts, far fewer RESENDs
    Set Homa Sysctls    resend_ticks=50    resend_interval=20    timeout_ticks=1000
    ${s}=    Incast Bulk    seconds=8
    Log    scaled timers: ${s} (defaults: ${DEF})
    Should Be Equal As Integers    ${s}[rpc_timeouts]    0
    Should Be Equal As Integers    ${s}[sw_drops]    0
    Should Be True    ${s}[resends] * 3 < ${DEF}[resends]    msg=scaled ${s}[resends] vs default ${DEF}[resends] RESENDs
