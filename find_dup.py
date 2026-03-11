# find_playlist_duplicates_improved.py
# Shows WHICH titles were found similar to each other + percentage

import json
import sys
from collections import defaultdict
from fuzzywuzzy import fuzz

# ───────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────

MIN_SIMILARITY = 80     # Adjust: 80–90 is usually good for music titles
OUTPUT_FILE = "duplicates_report.txt"

# ───────────────────────────────────────────────

def main(json_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        sys.exit(1)

    videos = data.get('videos', [])
    if not videos:
        print("No videos found in JSON.")
        return

    print(f"Processing playlist with {len(videos)} videos...\n")

    # ── 1. Exact duplicates by video ID ──
    id_to_entries = defaultdict(list)
    for idx, video in enumerate(videos):
        vid = video.get('id')
        title = video.get('titleLong', '(no title)').strip()
        if vid:
            id_to_entries[vid].append((idx, title, vid))

    exact_dups = {vid: entries for vid, entries in id_to_entries.items() if len(entries) > 1}

    # ── 2. Near-duplicates by title (fuzzy clustering) ──
    clusters = []
    used = set()

    for i in range(len(videos)):
        if i in used:
            continue

        title_i = videos[i].get('titleLong', '').strip()
        if not title_i or len(title_i) < 6:
            continue

        cluster = [(i, title_i, videos[i].get('id', '(no id)'))]
        used.add(i)

        for j in range(i + 1, len(videos)):
            if j in used:
                continue

            title_j = videos[j].get('titleLong', '').strip()
            if not title_j or len(title_j) < 6:
                continue

            # Using token_sort_ratio — good for song titles (ignores order)
            sim = fuzz.token_sort_ratio(title_i.lower(), title_j.lower())

            if sim >= MIN_SIMILARITY:
                cluster.append((j, title_j, videos[j].get('id', '(no id)')))
                used.add(j)

        if len(cluster) > 1:
            clusters.append(cluster)

    # ── Build report ──
    lines = []
    lines.append(f"Playlist: {data.get('title', 'Untitled')}")
    lines.append(f"Total videos: {len(videos)}")
    lines.append(f"Similarity threshold: ≥{MIN_SIMILARITY}% (using token_sort_ratio)")
    lines.append("=" * 70)
    lines.append("")

    if exact_dups:
        lines.append("EXACT DUPLICATES (same video ID)")
        lines.append("-" * 50)
        for vid, entries in sorted(exact_dups.items()):
            lines.append(f"Video ID: {vid}")
            for idx, title, _ in sorted(entries):
                lines.append(f"  [{idx:4d}]  {title}")
            lines.append("")
        lines.append("")
    else:
        lines.append("No exact duplicates by video ID found.\n")

    if clusters:
        lines.append("NEAR-DUPLICATE TITLE CLUSTERS")
        lines.append("-" * 50)
        cluster_num = 1

        for cluster in clusters:
            lines.append(f"Cluster #{cluster_num}  ({len(cluster)} similar items)")
            lines.append("-" * 40)

            # Show every pair's similarity
            for a in range(len(cluster)):
                idx_a, title_a, id_a = cluster[a]
                for b in range(a + 1, len(cluster)):
                    idx_b, title_b, id_b = cluster[b]
                    sim = fuzz.token_sort_ratio(title_a.lower(), title_b.lower())
                    lines.append(f"  {sim:3d}% similar:")
                    lines.append(f"     [{idx_a:4d}]  {title_a}")
                    lines.append(f"     [{idx_b:4d}]  {title_b}")
                    lines.append("")

            # Then full list of items in cluster
            lines.append("All items in this cluster:")
            for idx, title, vid in sorted(cluster):
                lines.append(f"  [{idx:4d}]  id={vid:<12}  {title}")
            lines.append("=" * 60)
            cluster_num += 1
    else:
        lines.append(f"No near-duplicate titles found (≥{MIN_SIMILARITY}%).")

    report = "\n".join(lines)
    print(report)

    # Save to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\nFull report saved to: {OUTPUT_FILE}")
    print("Use the [index] numbers to find and remove duplicates in YouTube.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python find_playlist_duplicates_improved.py <playlist.json>")
        sys.exit(1)

    main(sys.argv[1])
