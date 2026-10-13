*** Settings ***
Library           Collections
Library           String
Library           HomaLab.py

*** Variables ***
${KERNEL}         6.17.8-061708-generic
${SWITCH}         sw1
@{SERVICES}       homa-prio    homa-echo    homa-echo6    cp-homa    cp-tcp    cp-homa-probe    cp-tcp-probe

*** Keywords ***
Host Services Should Be Active
    [Arguments]    ${host}
    FOR    ${s}    IN    @{SERVICES}
        ${st}=    Run On    ${host}    systemctl is-active ${s}    expect_rc=any
        Should Be Equal    ${st}    active    msg=${host}: ${s} is ${st}
    END

Start Host Services
    FOR    ${h}    IN    @{HOSTS}
        Run On    ${h}    sudo systemctl start ${SERVICES}[0] ${SERVICES}[1] ${SERVICES}[2] ${SERVICES}[3] ${SERVICES}[4] ${SERVICES}[5] ${SERVICES}[6]
    END

Load Homa Everywhere
    FOR    ${h}    IN    @{HOSTS}
        Run On    ${h}    sudo modprobe homa && sudo sysctl -q -p /etc/sysctl.d/90-homa.conf
    END
    Start Host Services

Lab Setup
    ${hosts}=    Homa Hosts
    Set Global Variable    @{HOSTS}    @{hosts}
