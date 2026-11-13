#!/bin/bash
# Run m2bench for mimo-v2.5, all levels, thinking off vs on - SEQUENTIAL
cd "$(dirname "$0")"

echo "=== Starting mimo-v2.5 benchmark runs ==="
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"

for level in easy medium hard; do
    for mode in off on; do
        name="mimo25-${level}-${mode}"
        if [ "$mode" = "off" ]; then
            reasoning="none"
        else
            reasoning="high"
        fi
        echo ""
        echo ">> $name (reasoning=$reasoning) ..."
        py m2bench.py run --provider xiaomi --models mimo-v2.5 --set "$level" --name "$name" --reasoning "$reasoning" --workers 2 2>&1 | tail -5
    done
done

echo ""
echo "=== All runs done ==="
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
