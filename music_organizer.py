#!/usr/bin/env python3
"""
music_organizer.py - All-in-one YouTube music library organizer.

Designed to run periodically (e.g. via cron) to keep your library clean
as new songs are added by Pinchflat.

Steps:
  1. Fix permissions (chown to current user)
  2. Merge folders with similar names (VEVO, Official, collabs, etc.)
  3. Move misplaced files to correct artist folder based on filename
  4. Set artist metadata tag to the folder name
  5. Clean artist metadata (strip VEVO, collabs, suffixes)
  6. Remove empty folders

Usage:
    python3 music_organizer.py /DATA/Media/Music/Youtube              # Dry run
    python3 music_organizer.py /DATA/Media/Music/Youtube --execute    # Apply

Cron example (every 30 min):
    */30 * * * * /usr/bin/python3 /home/sarun/music_organizer.py /DATA/Media/Music/Youtube --execute >> /home/sarun/music_organizer.log 2>&1
"""

import os
import sys
import re
import shutil
import subprocess
from pathlib import Path
from collections import defaultdict

try:
    import mutagen
    from mutagen.mp4 import MP4
    from mutagen.mp3 import MP3
    from mutagen.id3 import TPE1
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

# Extensions to treat as music files
MUSIC_EXTS = {
    '.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav',
    '.wma', '.aac', '.webm', '.mp4', '.mkv', '.m4v',
}

# Extensions mutagen can tag
TAGGABLE_EXTS = {'.mp3', '.m4a', '.flac', '.ogg', '.opus'}

# Manual overrides: normalized name -> Display Name
KNOWN_ARTISTS = {
    # "juice wrld": "Juice WRLD",
}

# Words that cause false positive folder merges
MERGE_BLOCKLIST_WORDS = {
    'music', 'records', 'lyrical', 'official', 'beats', 'thug',
    'thunder', 'monster', 'trap', 'real', 'best',
}

# Artist names that are common English words — skip in filename scanning
FILENAME_SKIP_ARTISTS = {
    'creed', 'future', 'magic', 'marina', 'passenger', 'journey',
    'watt', 'en', 'chara', 'emerge', 'pulse', 'faerie', 'toxic',
    'nisha deshar', 'skepta', 'babymetal',
}


# =========================================================================
#  Helpers
# =========================================================================

def strip_yt_suffixes(name):
    s = name.strip()
    for p in [
        r"\s*Official\s+YouTube\s+Channel\s*$",
        r"\s*Official\s+YouTube\s*$",
        r"\s*Official\s*$",
        r"\s*VEVO\s*$",
        r"\s+Ch\.\s+.*$",
        r"\s+TV\s*$",
        r"\s+HD\s*$",
        r"\s+HQ\s*$",
        r"[#_]+$",
    ]:
        s = re.sub(p, '', s, flags=re.IGNORECASE).strip()
    return s.strip(' -_.,')


def extract_primary(name):
    s = strip_yt_suffixes(name)
    s = re.sub(r'\s*[-–]\s*\(.*?\)\s*$', '', s)
    s = re.sub(r'\s*\(.*?\)\s*$', '', s)
    if ',' in s:
        s = s.split(',')[0].strip()
    return s.strip()


def normalize(name):
    n = name.lower()
    n = re.sub(r'[^a-z0-9\s]', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def normalize_filename(name):
    n = name.lower()
    n = re.sub(r'[^a-z0-9\s]', ' ', n)
    n = re.sub(r'^\d+\s*[-.]?\s*', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def clean_artist_name(name):
    """Clean an artist tag: strip VEVO, Official, collabs, etc."""
    s = name.strip()
    s = re.sub(r'VEVO$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*Official\s+YouTube\s+Channel\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*Official\s+YouTube\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*Official\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+Ch\.\s+.*$', '', s).strip()
    s = re.sub(r'\s+TV\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+HD\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+HQ\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+Music\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'[#_]+$', '', s).strip()
    s = re.sub(r'\s*\(.*?\)\s*$', '', s).strip()
    s = re.sub(r'\s*[-–]\s*\(.*?\)\s*$', '', s).strip()
    if ',' in s:
        s = s.split(',')[0].strip()
    return s.strip(' -_.,')


def pick_canonical(folder_list):
    def score(name):
        s = 0
        low = name.lower()
        if 'vevo' in low: s -= 20
        if 'official' in low: s -= 10
        if ',' in name: s -= 15
        if '(' in name: s -= 5
        if '#' in name or '_' in name: s -= 3
        if extract_primary(name) == name: s += 10
        if name != name.upper() and name != name.lower(): s += 3
        if len(name) < 3: s -= 10
        if len(name) > 40: s -= 5
        return s
    return max(folder_list, key=score)


# =========================================================================
#  Metadata helpers
# =========================================================================

def get_artist(filepath):
    if not HAS_MUTAGEN:
        return ''
    try:
        ext = filepath.suffix.lower()
        if ext == '.m4a':
            t = MP4(str(filepath))
            return t.get('\xa9ART', [''])[0] if t.get('\xa9ART') else ''
        elif ext == '.mp3':
            t = MP3(str(filepath))
            return str(t.get('TPE1', ''))
        elif ext == '.flac':
            t = FLAC(str(filepath))
            return t.get('artist', [''])[0] if t.get('artist') else ''
        elif ext == '.ogg':
            t = OggVorbis(str(filepath))
            return t.get('artist', [''])[0] if t.get('artist') else ''
        elif ext == '.opus':
            t = OggOpus(str(filepath))
            return t.get('artist', [''])[0] if t.get('artist') else ''
    except Exception:
        pass
    return ''


def set_artist(filepath, artist):
    if not HAS_MUTAGEN:
        return
    ext = filepath.suffix.lower()
    if ext == '.m4a':
        t = MP4(str(filepath))
        t['\xa9ART'] = [artist]
        t.save()
    elif ext == '.mp3':
        t = MP3(str(filepath))
        if t.tags is None:
            t.add_tags()
        t.tags['TPE1'] = TPE1(encoding=3, text=[artist])
        t.save()
    elif ext == '.flac':
        t = FLAC(str(filepath))
        t['artist'] = [artist]
        t.save()
    elif ext == '.ogg':
        t = OggVorbis(str(filepath))
        t['artist'] = [artist]
        t.save()
    elif ext == '.opus':
        t = OggOpus(str(filepath))
        t['artist'] = [artist]
        t.save()


def safe_move(src, dst_dir):
    target = dst_dir / src.name
    if target.exists():
        stem, suffix = src.stem, src.suffix
        i = 1
        while target.exists():
            target = dst_dir / f"{stem}_{i}{suffix}"
            i += 1
    shutil.move(str(src), str(target))
    return target


# =========================================================================
#  Main
# =========================================================================

def main():
    if len(sys.argv) < 2 or '--help' in sys.argv:
        print(__doc__)
        sys.exit(0)

    music_dir = Path(sys.argv[1])
    execute = '--execute' in sys.argv

    if not music_dir.is_dir():
        print(f"Error: {music_dir} is not a directory")
        sys.exit(1)

    if not HAS_MUTAGEN:
        print("Warning: mutagen not installed — metadata tagging will be skipped.")
        print("  Install: pip install mutagen\n")

    folders = sorted([d.name for d in music_dir.iterdir() if d.is_dir()])
    print(f"Found {len(folders)} folders\n")

    # =================================================================
    #  STEP 1: Group folders by normalized primary artist name
    # =================================================================
    norm_groups = defaultdict(list)
    for f in folders:
        primary = extract_primary(f)
        n = normalize(primary)
        if n:
            norm_groups[n].append(f)
        else:
            norm_groups[f].append(f)

    group_keys = sorted(norm_groups.keys(), key=len, reverse=True)
    merge_into = {}
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
            if re.search(r'(?:^|\s)' + re.escape(k2) + r'(?:\s|$)', k1):
                merge_into[k2] = k1
            elif spaceless[k1] == spaceless[k2]:
                merge_into[k2] = k1

    def resolve(k):
        visited = set()
        while k in merge_into and k not in visited:
            visited.add(k)
            k = merge_into[k]
        return k

    final_groups = defaultdict(list)
    for k, fl in norm_groups.items():
        final_groups[resolve(k)].extend(fl)

    merge_plan = []
    canonical_map = {}

    for nk, fl in final_groups.items():
        canonical = KNOWN_ARTISTS.get(nk) or pick_canonical(fl)
        canonical_map[nk] = canonical
        others = [f for f in fl if f != canonical]
        if others:
            merge_plan.append((canonical, sorted(others)))

    artist_lookup = {}
    for nk, canonical in canonical_map.items():
        artist_lookup[nk] = canonical
        cn = normalize(canonical)
        if cn and cn != nk:
            artist_lookup[cn] = canonical

    # =================================================================
    #  STEP 2: Scan files for misplaced artist references
    # =================================================================
    searchable = []
    for nn, canonical in artist_lookup.items():
        if len(nn) >= 5 and nn not in FILENAME_SKIP_ARTISTS:
            searchable.append((nn, canonical))
    searchable.sort(key=lambda x: len(x[0]), reverse=True)

    file_move_plan = []

    for folder_name in folders:
        folder_path = music_dir / folder_name
        if not folder_path.exists():
            continue

        folder_norm = normalize(extract_primary(folder_name))
        folder_canonical = artist_lookup.get(resolve(folder_norm), folder_name)

        for f in folder_path.iterdir():
            if not f.is_file() or f.suffix.lower() not in MUSIC_EXTS:
                continue

            fn = normalize_filename(f.stem)
            for artist_norm, artist_canonical in searchable:
                if artist_canonical == folder_canonical or artist_norm == folder_norm:
                    continue
                if re.search(r'(?:^|\s)' + re.escape(artist_norm) + r'(?:\s|$)', fn):
                    file_move_plan.append((f, artist_canonical))
                    break

    # =================================================================
    #  STEP 3: Scan metadata for tagging
    # =================================================================
    tag_plan = []  # (filepath, new_artist_name)

    if HAS_MUTAGEN:
        for folder_name in folders:
            folder_path = music_dir / folder_name
            if not folder_path.exists():
                continue

            desired = clean_artist_name(folder_name)

            for f in folder_path.iterdir():
                if not f.is_file() or f.suffix.lower() not in TAGGABLE_EXTS:
                    continue
                try:
                    current = get_artist(f)
                except Exception:
                    continue

                if current == desired:
                    continue

                tag_plan.append((f, current, desired))

    # =================================================================
    #  REPORT
    # =================================================================
    print("=" * 70)
    print("  STEP 1: FOLDER MERGES")
    print("=" * 70)
    if merge_plan:
        for canonical, others in sorted(merge_plan, key=lambda x: x[0].lower()):
            sd = music_dir / canonical
            fc = sum(1 for _ in sd.iterdir()) if sd.exists() else 0
            print(f"\n  → {canonical}/ ({fc} files)")
            for o in others:
                od = music_dir / o
                oc = sum(1 for _ in od.iterdir()) if od.exists() else 0
                print(f"      ← {o}/ ({oc} files)")
    else:
        print("\n  (none)")

    print(f"\n{'=' * 70}")
    print("  STEP 2: FILE MOVES")
    print("=" * 70)
    if file_move_plan:
        by_dst = defaultdict(list)
        for sf, df in file_move_plan:
            by_dst[df].append(sf)
        for dst, files in sorted(by_dst.items()):
            print(f"\n  → {dst}/")
            for f in sorted(files, key=lambda x: x.name):
                print(f"      ← {f.parent.name}/{f.name}")
    else:
        print("\n  (none)")

    print(f"\n{'=' * 70}")
    print("  STEP 3: ARTIST TAG UPDATES")
    print("=" * 70)
    if tag_plan:
        shown = 0
        for fp, old, new in tag_plan:
            if shown < 50:  # Cap output for large libraries
                old_d = old if old else '(empty)'
                print(f"  {fp.parent.name}/{fp.name}: \"{old_d}\" → \"{new}\"")
                shown += 1
        if len(tag_plan) > 50:
            print(f"  ... and {len(tag_plan) - 50} more")
    else:
        print("\n  (none)")

    # Summary
    total_merge_files = sum(
        sum(1 for _ in (music_dir / o).iterdir())
        for _, others in merge_plan for o in others
        if (music_dir / o).exists()
    )
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY:")
    print(f"    Folder merges:   {len(merge_plan)} groups ({total_merge_files} files)")
    print(f"    File moves:      {len(file_move_plan)}")
    print(f"    Tag updates:     {len(tag_plan)}")
    print(f"{'=' * 70}")

    if not execute:
        print("\n  ** DRY RUN ** — Run with --execute to apply.\n")
        return

    # =================================================================
    #  EXECUTE
    # =================================================================
    print("\nApplying...\n")

    # Fix permissions
    user = os.environ.get('USER') or os.environ.get('LOGNAME', 'sarun')
    print(f"  Fixing ownership: chown -R {user}:{user} {music_dir}")
    result = subprocess.run(
        ['sudo', 'chown', '-R', f'{user}:{user}', str(music_dir)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  chown failed: {result.stderr.strip()}")
        print(f"  Run manually: sudo chown -R {user}:{user} {music_dir}")
        sys.exit(1)
    print("  Done.\n")

    # Folder merges
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
                print(f"  Warning: {other}/ not empty")

    # File moves
    for src_file, dst_folder in file_move_plan:
        if not src_file.exists():
            continue
        dst = music_dir / dst_folder
        dst.mkdir(exist_ok=True)
        safe_move(src_file, dst)
        print(f"  Moved: {src_file.parent.name}/{src_file.name} → {dst_folder}/")

    # Tag updates — re-scan after moves since files may have moved
    if HAS_MUTAGEN:
        tag_success = 0
        for folder in sorted(music_dir.iterdir()):
            if not folder.is_dir():
                continue
            desired = clean_artist_name(folder.name)
            for f in folder.iterdir():
                if not f.is_file() or f.suffix.lower() not in TAGGABLE_EXTS:
                    continue
                try:
                    current = get_artist(f)
                    if current != desired:
                        set_artist(f, desired)
                        tag_success += 1
                except Exception as e:
                    print(f"  Tag error: {f.name}: {e}")
        print(f"  Updated {tag_success} artist tags.")

    # Cleanup empty dirs
    removed = 0
    for d in sorted(music_dir.iterdir()):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            removed += 1
            print(f"  Removed empty: {d.name}/")

    print(f"\nDone! Removed {removed} empty folders.")


if __name__ == '__main__':
    main()
