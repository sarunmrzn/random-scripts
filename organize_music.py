#!/usr/bin/env python3
"""
organize_music.py - Consolidate YouTube-downloaded music folders by artist.

Phase 1: Fix permissions (chown to current user)
Phase 2: Merge folders with similar names (VEVO, Official, collabs, etc.)
Phase 3: Scan ALL files for known artist names and move them to the right folder
Phase 4: Clean up empty folders

Usage:
    python3 organize_music.py /DATA/Media/Music/Youtube              # Dry run
    python3 organize_music.py /DATA/Media/Music/Youtube --execute    # Apply changes
"""

import os
import sys
import re
import shutil
import subprocess
from pathlib import Path
from collections import defaultdict

MUSIC_EXTS = {
    '.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav',
    '.wma', '.aac', '.webm', '.mp4', '.mkv', '.m4v',
}

# Manual overrides: normalized name -> Display Name
KNOWN_ARTISTS = {
    # "juice wrld": "Juice WRLD",
}

# Words that cause false positive substring merges between unrelated folders.
# These are common words in channel names, NOT artist names.
# Prevents "music" matching "pop music crooners", "lyrical" matching both
# "lyrical lemonade" and "lyrical music", etc.
MERGE_BLOCKLIST_WORDS = {
    'music', 'records', 'lyrical', 'official', 'beats', 'thug',
    'thunder', 'monster', 'trap', 'real', 'best',
}

# Artist names that are common English words — skip these in filename scanning
# to avoid false positives like "Creed" matching "Assassin's Creed" or
# "Future" matching "Future Bass".
FILENAME_SKIP_ARTISTS = {
    'creed', 'future', 'magic', 'marina', 'passenger', 'journey',
    'watt', 'en', 'chara', 'emerge', 'pulse', 'faerie', 'toxic',
    'nisha deshar', 'skepta', 'babymetal',
}


def strip_yt_suffixes(name):
    """Remove common YouTube channel name suffixes."""
    s = name.strip()
    patterns = [
        r"\s*Official\s+YouTube\s+Channel\s*$",
        r"\s*Official\s+YouTube\s*$",
        r"\s*Official\s*$",
        r"\s*VEVO\s*$",
        r"\s+Ch\.\s+.*$",
        r"\s+TV\s*$",
        r"\s+HD\s*$",
        r"\s+HQ\s*$",
        r"[#_]+$",
    ]
    for p in patterns:
        s = re.sub(p, '', s, flags=re.IGNORECASE).strip()
    return s.strip(' -_.,')


def extract_primary(name):
    """Extract primary artist from folder name, handling collabs."""
    s = strip_yt_suffixes(name)
    s = re.sub(r'\s*[-–]\s*\(.*?\)\s*$', '', s)
    s = re.sub(r'\s*\(.*?\)\s*$', '', s)
    if ',' in s:
        s = s.split(',')[0].strip()
    return s.strip()


def normalize(name):
    """Lowercase, only alphanumeric + spaces, collapsed."""
    n = name.lower()
    n = re.sub(r'[^a-z0-9\s]', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def normalize_filename(name):
    """Normalize a filename for artist searching."""
    n = name.lower()
    n = re.sub(r'[^a-z0-9\s]', ' ', n)
    n = re.sub(r'^\d+\s*[-.]?\s*', '', n)  # Strip leading track numbers
    return re.sub(r'\s+', ' ', n).strip()


def pick_canonical(folder_list):
    """Pick the best folder name as the canonical artist name."""
    def score(name):
        s = 0
        low = name.lower()
        if 'vevo' in low:
            s -= 20
        if 'official' in low:
            s -= 10
        if 'music' == low.split()[-1:]:
            s -= 5
        if ',' in name:
            s -= 15
        if '(' in name:
            s -= 5
        if '#' in name or '_' in name:
            s -= 3
        if extract_primary(name) == name:
            s += 10
        if name != name.upper() and name != name.lower():
            s += 3
        if len(name) < 3:
            s -= 10
        if len(name) > 40:
            s -= 5
        return s
    return max(folder_list, key=score)


def main():
    if len(sys.argv) < 2 or '--help' in sys.argv:
        print(__doc__)
        sys.exit(0)

    music_dir = Path(sys.argv[1])
    execute = '--execute' in sys.argv

    if not music_dir.is_dir():
        print(f"Error: {music_dir} is not a directory")
        sys.exit(1)

    folders = sorted([d.name for d in music_dir.iterdir() if d.is_dir()])
    print(f"Found {len(folders)} folders\n")

    # =====================================================================
    #  PHASE 1: Group folders by normalized primary artist name
    # =====================================================================
    norm_groups = defaultdict(list)
    for f in folders:
        primary = extract_primary(f)
        n = normalize(primary)
        if n:
            norm_groups[n].append(f)
        else:
            norm_groups[f].append(f)

    # Merge groups where one normalized name is a WORD-BOUNDED prefix/match
    # of another, but skip common words that cause false merges.
    # Also try matching with spaces stripped for cases like "edubble" vs "e dubble"
    group_keys = sorted(norm_groups.keys(), key=len, reverse=True)
    merge_into = {}

    # Build spaceless variants for fuzzy matching
    spaceless = {k: k.replace(' ', '') for k in group_keys}

    for i, k1 in enumerate(group_keys):
        if k1 in merge_into:
            continue
        for k2 in group_keys[i + 1:]:
            if k2 in merge_into:
                continue
            if len(k2) < 4:
                continue
            if k2 in MERGE_BLOCKLIST_WORDS:
                continue
            # Exact word-boundary match
            if re.search(r'(?:^|\s)' + re.escape(k2) + r'(?:\s|$)', k1):
                merge_into[k2] = k1
            # Spaceless match (e.g. "edubble" == "e dubble")
            elif spaceless[k1] == spaceless[k2]:
                merge_into[k2] = k1

    def resolve(k):
        visited = set()
        while k in merge_into and k not in visited:
            visited.add(k)
            k = merge_into[k]
        return k

    final_groups = defaultdict(list)
    for k, folder_list in norm_groups.items():
        target = resolve(k)
        final_groups[target].extend(folder_list)

    # Build merge plan & canonical name lookup
    merge_plan = []
    canonical_map = {}  # norm_key -> canonical folder name

    for norm_key, folder_list in final_groups.items():
        # Apply manual overrides
        if norm_key in KNOWN_ARTISTS:
            canonical = KNOWN_ARTISTS[norm_key]
        else:
            canonical = pick_canonical(folder_list)
        canonical_map[norm_key] = canonical
        others = [f for f in folder_list if f != canonical]
        if others:
            merge_plan.append((canonical, sorted(others)))

    # Build artist lookup: normalized name -> canonical folder name
    artist_lookup = {}
    for norm_key, canonical in canonical_map.items():
        artist_lookup[norm_key] = canonical
        cn = normalize(canonical)
        if cn and cn != norm_key:
            artist_lookup[cn] = canonical

    # =====================================================================
    #  PHASE 2: Scan ALL files for artist names in filenames
    # =====================================================================
    # Build searchable list: only artists with names >= 5 chars to avoid
    # false positives on short names like "Ado", "DMX", etc.
    # Also skip artists whose names are common English words.
    searchable = []
    for norm_name, canonical in artist_lookup.items():
        if len(norm_name) >= 5 and norm_name not in FILENAME_SKIP_ARTISTS:
            searchable.append((norm_name, canonical))
    searchable.sort(key=lambda x: len(x[0]), reverse=True)

    file_plan = []  # (src_path, dst_folder_name)

    # Scan EVERY folder (not just "single" ones)
    for folder_name in folders:
        folder_path = music_dir / folder_name
        if not folder_path.exists():
            continue

        # What artist does THIS folder belong to after phase 1 merges?
        folder_artist_norm = normalize(extract_primary(folder_name))
        folder_canonical = artist_lookup.get(
            resolve(folder_artist_norm), folder_name
        )

        for f in folder_path.iterdir():
            if not f.is_file() or f.suffix.lower() not in MUSIC_EXTS:
                continue

            fn = normalize_filename(f.stem)

            for artist_norm, artist_canonical in searchable:
                # Don't move files that already belong to the right artist
                if artist_canonical == folder_canonical:
                    continue
                if artist_norm == folder_artist_norm:
                    continue

                # Match artist name with word boundaries in normalized filename
                if re.search(
                    r'(?:^|\s)' + re.escape(artist_norm) + r'(?:\s|$)', fn
                ):
                    file_plan.append((f, artist_canonical))
                    break

    # =====================================================================
    #  PHASE 3: Report
    # =====================================================================
    print("=" * 70)
    print("  PHASE 1: FOLDER MERGES (same artist, different channel names)")
    print("=" * 70)

    if merge_plan:
        for canonical, others in sorted(merge_plan, key=lambda x: x[0].lower()):
            src_dir = music_dir / canonical
            fc = sum(1 for _ in src_dir.iterdir()) if src_dir.exists() else 0
            print(f"\n  → {canonical}/ ({fc} files)")
            for other in others:
                od = music_dir / other
                oc = sum(1 for _ in od.iterdir()) if od.exists() else 0
                print(f"      ← {other}/ ({oc} files)")
    else:
        print("\n  (no folder merges detected)")

    print(f"\n{'=' * 70}")
    print("  PHASE 2: FILE MOVES (files with artist name in wrong folder)")
    print("=" * 70)

    if file_plan:
        by_dst = defaultdict(list)
        for src_file, dst_folder in file_plan:
            by_dst[dst_folder].append(src_file)

        for dst, files in sorted(by_dst.items()):
            print(f"\n  → {dst}/")
            for f in sorted(files, key=lambda x: x.name):
                print(f"      ← {f.parent.name}/{f.name}")
    else:
        print("\n  (no misplaced files detected)")

    # Summary
    total_merge_files = sum(
        sum(1 for _ in (music_dir / o).iterdir())
        for _, others in merge_plan
        for o in others
        if (music_dir / o).exists()
    )
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY:")
    print(f"    Folder merges:  {len(merge_plan)} groups ({total_merge_files} files to move)")
    print(f"    File relocations: {len(file_plan)} files by artist name detection")
    print(f"{'=' * 70}")

    if not execute:
        print("\n  ** DRY RUN ** — Review above, then run with --execute to apply.\n")
        return

    # =====================================================================
    #  EXECUTE
    # =====================================================================
    print("\nApplying changes...\n")

    # Fix permissions first — Pinchflat creates files as root
    user = os.environ.get('USER') or os.environ.get('LOGNAME', 'sarun')
    print(f"  Fixing ownership: chown -R {user}:{user} {music_dir}")
    result = subprocess.run(
        ['sudo', 'chown', '-R', f'{user}:{user}', str(music_dir)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  Warning: chown failed: {result.stderr.strip()}")
        print("  Try running: sudo chown -R $(whoami):$(whoami)", music_dir)
        sys.exit(1)
    print("  Permissions fixed.\n")

    def safe_move(src, dst_dir):
        """Move file to dst_dir, renaming if collision."""
        target = dst_dir / src.name
        if target.exists():
            stem, suffix = src.stem, src.suffix
            i = 1
            while target.exists():
                target = dst_dir / f"{stem}_{i}{suffix}"
                i += 1
        shutil.move(str(src), str(target))
        return target

    # Phase 1: Folder merges
    for canonical, others in merge_plan:
        dst = music_dir / canonical
        dst.mkdir(exist_ok=True)
        for other in others:
            src_dir = music_dir / other
            if not src_dir.exists():
                continue
            for f in list(src_dir.iterdir()):
                safe_move(f, dst)
            try:
                src_dir.rmdir()
                print(f"  Merged: {other}/ → {canonical}/")
            except OSError:
                print(f"  Warning: {other}/ not empty after merge")

    # Phase 2: File moves
    for src_file, dst_folder in file_plan:
        if not src_file.exists():
            continue
        dst = music_dir / dst_folder
        dst.mkdir(exist_ok=True)
        safe_move(src_file, dst)
        print(f"  Moved: {src_file.parent.name}/{src_file.name} → {dst_folder}/")

    # Phase 3: Clean up empty directories
    removed = 0
    for d in sorted(music_dir.iterdir()):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            removed += 1
            print(f"  Removed empty: {d.name}/")

    print(f"\nDone! Cleaned up {removed} empty folders.")


if __name__ == '__main__':
    main()
