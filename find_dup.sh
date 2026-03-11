#!/usr/bin/env bash

# Usage: ./find_playlist_duplicates.sh your_playlist.json

if [ $# -ne 1 ]; then
    echo "Usage: $0 <json_file>"
    exit 1
fi

JSON_FILE="$1"

if [ ! -f "$JSON_FILE" ]; then
    echo "File not found: $JSON_FILE"
    exit 1
fi

echo "=== Processing playlist: $JSON_FILE ==="
echo "Total videos found: $(jq '.videos | length' "$JSON_FILE")"
echo

# ───────────────────────────────────────────────
# 1. Exact duplicates by video ID (fast & reliable)
# ───────────────────────────────────────────────

echo "=== Exact duplicates by video ID ==="

jq -r '.videos[] | [.id, .titleLong] | @tsv' "$JSON_FILE" |
awk -F'\t' '
    {
        id = $1
        title = $2
        if (seen[id]++) {
            print "DUPLICATE ID: " id " → " title
        }
    }
' | sort | uniq -c | sed 's/^ *[0-9]\+ //'

echo

# ───────────────────────────────────────────────
# 2. Near-duplicate titles (≥70% similarity)
# ───────────────────────────────────────────────

echo "=== Near-duplicate titles (≥70% similarity) ==="
echo "(basic char overlap method – may give some false positives)"

# Extract index + title
jq -r '.videos | keys[] as $k | [$k, .[$k].titleLong] | @tsv' "$JSON_FILE" > /tmp/titles.tsv

awk -F'\t' '
    function min(a,b) { return a<b ? a : b }
    function max(a,b) { return a>b ? a : b }

    function similarity(s1, s2,    l1,l2,common,i,j) {
        l1 = length(s1); l2 = length(s2)
        if (l1 == 0 && l2 == 0) return 100
        if (l1 == 0 || l2 == 0) return 0

        common = 0
        split(tolower(s1), a, "")
        split(tolower(s2), b, "")
        for (i=1; i<=l1; i++)
            for (j=1; j<=l2; j++)
                if (a[i] == b[j]) common++

        return (common * 200) / (l1 + l2)
    }

    NR==FNR {
        idx[NR] = $1      # original array index in .videos[]
        titles[NR] = $2
        next
    }

    {
        line = FNR
        title1 = $2
        if (length(title1) < 5) next   # skip very short/empty

        for (i=1; i<line; i++) {
            title2 = titles[i]
            if (length(title2) < 5) continue
            if (title1 == title2) continue

            sim = similarity(title1, title2)
            if (sim >= 70) {
                printf "SIMILAR (%.0f%%)  [idx %3s vs %3s]\n  %s\n  %s\n\n", \
                    sim, idx[line], idx[i], title1, title2
            }
        }
    }
' /tmp/titles.tsv /tmp/titles.tsv | sort -u

echo "Done."

rm -f /tmp/titles.tsv
