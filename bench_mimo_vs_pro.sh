#!/bin/bash
cd "$(dirname "$0")"

echo "=== mimo-v2.5 vs mimo-v2.5-pro | hard | reasoning off ==="
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"

echo ""
echo ">> Running both models in parallel..."
py m2bench.py run --provider xiaomi --models mimo-v2.5 --set hard --name mimo25-hard-vsoff --reasoning none --workers 2 > /dev/null 2>&1 &
PID1=$!
py m2bench.py run --provider xiaomi --models mimo-v2.5-pro --set hard --name mimo25pro-hard-vsoff --reasoning none --workers 2 > /dev/null 2>&1 &
PID2=$!

echo "PIDs: $PID1, $PID2"
wait $PID1
echo "mimo-v2.5 done (exit: $?)"
wait $PID2
echo "mimo-v2.5-pro done (exit: $?)"

echo ""
echo ">> Grading mimo-v2.5 ..."
py m2bench.py grade --run mimo25-hard-vsoff --provider openrouter --models mimo-v2.5 2>&1 | tail -3

echo ""
echo ">> Grading mimo-v2.5-pro ..."
py m2bench.py grade --run mimo25pro-hard-vsoff --provider openrouter --models mimo-v2.5-pro 2>&1 | tail -3

echo ""
echo "=== Reports ==="
py m2bench.py report --run mimo25-hard-vsoff > /dev/null 2>&1
py m2bench.py report --run mimo25pro-hard-vsoff > /dev/null 2>&1

for name in mimo25-hard-vsoff mimo25pro-hard-vsoff; do
    echo ""
    echo "--- $name ---"
    head -8 "C:/Users/athai/Hermes-Output/data/m2bench/runs/$name/report.md"
done

echo ""
echo "=== ALL DONE ==="
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
