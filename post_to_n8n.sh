#!/bin/bash
# Post stock analysis to n8n and Hostinger website
# Usage: ./post_to_n8n.sh

# Secure: webhook URLs from environment variables
WEBHOOK_URL="${N8N_WEBHOOK_URL}"
HOSTINGER_URL="${HOSTINGER_URL}"
HOSTINGER_SECRET="${HOSTINGER_SECRET}"

# Run analysis and capture JSON output
RESULT=$(python3 stock_analysis.py us --json 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "Error running analysis"
    exit 1
fi

# Extract BUY signals and post to Hostinger
if [ -n "$HOSTINGER_URL" ] && [ -n "$HOSTINGER_SECRET" ]; then
    echo "Posting to Hostinger..."

    # Get BUY signals from result
    BUY_SIGNALS=$(echo "$RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
buys = [r for r in data if r.get('recommendation') == 'BUY']
for b in buys:
    print(json.dumps(b))
" 2>/dev/null)

    # Post each BUY signal
    echo "$BUY_SIGNALS" | while read -r signal; do
        if [ -n "$signal" ]; then
            curl -s -X POST "$HOSTINGER_URL" \
                -H "Content-Type: application/json" \
                -H "X-Secret: $HOSTINGER_SECRET" \
                -d "$signal" > /dev/null
            echo "Posted: $(echo $signal | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(\"code\",\"\"), d.get(\"recommendation\",\"\"))')"
        fi
    done
fi

# Post to n8n
if [ -n "$WEBHOOK_URL" ]; then
    echo "Posting to n8n..."
    curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "$RESULT"
    echo "Posted to n8n"
fi

echo "Done!"
