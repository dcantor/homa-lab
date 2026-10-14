#!/usr/bin/env bash
# Run the Robot Framework suites against the lab.   tests/run.sh [robot options...]   e.g. tests/run.sh suites/05_incast.robot
# Each run gets tests/results_YYYY-MM-DD_HH-MM-SS/ (tests/results_latest links the newest): log.html, report.html, output.xml, and state/ — the hosts' Homa sysctls and
# module versions and sw1's policy, before the run (the suites change sysctls and sw1 and put them back).
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ROBOT="$PWD/.venv/bin/robot"
[[ -x "$ROBOT" ]] || { echo "error: run tests/setup.sh first" >&2; exit 1; }
exec 9>/tmp/homa-lab-test.lock          # one run at a time: the suites load the network and change sw1
flock -n 9 || { echo "==> another test run holds /tmp/homa-lab-test.lock — waiting for it"; flock 9; }
unset FORCE_COLOR

ts="$(date +%Y-%m-%d_%H-%M-%S)"; out="$PWD/results_$ts"; mkdir -p "$out/state"
echo "==> results: $out"
../lab.sh inventory > "$out/state/inventory.json"
for h in h1 h2 h3 h4; do ../lab.sh exec "$h" 'uname -r; modinfo -F srcversion homa; sysctl net.homa' > "$out/state/$h.txt" 2>&1; done
../lab.sh qos show > "$out/state/sw1.txt" 2>&1

args=("$@"); explicit=0; for x in "$@"; do [[ "$x" == *.robot ]] && explicit=1; done; [[ $explicit -eq 1 ]] || args+=(suites/)
"$ROBOT" --outputdir "$out" --name "homa lab" --loglevel INFO "${args[@]}"
rc=$?
ln -sfn "$(basename "$out")" results_latest
mkdir -p ../results; ln -sfn "../tests/$(basename "$out")" ../results/latest   # where Lab Hub reads a lab's last run
echo "==> report: $out/report.html  (rc=$rc)"
exit $rc
