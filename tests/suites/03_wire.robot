*** Settings ***
Documentation     What Homa puts on the wire, captured at h1 while it serves short messages and 500 KB messages at once and
...               decoded with the lab's dissector (image/homa.lua): the protocol's packet types, and the priorities in the
...               IP header that sw1 queues by — short messages and control packets at the top priority, scheduled data at
...               the priorities the receiver's grants assign (below the top).
Resource          ../resources/common.resource
Suite Setup       Run Keywords    Lab Setup    AND    Capture

*** Variables ***
${CAP}            ${None}

*** Keywords ***
Capture
    ${c}=    Capture Homa    seconds=4
    Set Suite Variable    ${CAP}    ${c}

*** Test Cases ***
The capture decodes as Homa with the lab dissector
    Should Be True    ${CAP}[packets] > 1000    msg=only ${CAP}[packets] Homa packets captured
    Dictionary Should Contain Key    ${CAP}[types]    DATA

Receiver-driven transfers: GRANTs and START_MSG appear, and the RPCs are acknowledged
    FOR    ${t}    IN    GRANT    START_MSG
        Dictionary Should Contain Key    ${CAP}[types]    ${t}    msg=no ${t} packets: ${CAP}[types]
    END
    ${acks}=    Evaluate    ${CAP}[types].get('ACK', 0) + ${CAP}[types].get('NEED_ACK', 0)
    Should Be True    ${acks} > 0    msg=no ACK / NEED_ACK packets: ${CAP}[types]

Short messages travel at the highest priority
    Should Be Equal    ${CAP}[priorities][short_data]    ${{[7]}}

Scheduled data uses the priorities the grants assign, below the top one
    ${sched}=    Set Variable    ${CAP}[priorities][long_scheduled_data]
    Should Not Be Empty    ${sched}
    Should Be True    min(${sched}) < 7    msg=scheduled data only at priority 7: ${sched}
    ${g}=    Set Variable    ${CAP}[priorities][grants_carry]
    Should Not Be Empty    ${g}
    Should Be True    max(${g}) <= 6    msg=grants assign priorities above max_sched_prio: ${g}

Control packets travel at the highest priority
    Should Be Equal    ${CAP}[priorities][control]    ${{[7]}}

sw1 sorted the traffic into more than one priority queue
    ${s}=    Switch Qos Stats
    ${used}=    Evaluate    [k for k, v in ${s}[eth1][prio].items() if v['packets'] > 0]
    ${n}=    Get Length    ${used}
    Should Be True    ${n} >= 3    msg=sw1 eth1 used queues ${used}
