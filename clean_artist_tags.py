#!/usr/bin/env python3
"""
clean_artist_tags.py - Clean up artist metadata by stripping YouTube suffixes,
collab names, and other noise from the artist tag.

"Juice WRLD, Seezyn" → "Juice WRLD"
"edubbleVEVO" → "e-dubble"
"LiSA Official YouTube" → "LiSA"

Usage:
    python3 clean_artist_tags.py /DATA/Media/Music/Youtube              # Dry run
    python3 clean_artist_tags.py /DATA/Media/Music/Youtube --execute    # Apply
"""

import sys
import re
from pathlib import Path

try:
    import mutagen
    from mutagen.mp4 import MP4
    from mutagen.mp3 import MP3
    from mutagen.id3 import TPE1
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
except ImportError:
    print("mutagen is required: pip install mutagen")
    sys.exit(1)

MUSIC_EXTS = {'.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav', '.wma', '.aac', '.webm'}


def clean_artist(name):
    """Clean an artist name by removing YouTube channel noise."""
    s = name.strip()

    # Remove VEVO suffix
    s = re.sub(r'VEVO$', '', s, flags=re.IGNORECASE).strip()

    # Remove "Official YouTube Channel", "Official YouTube", "Official"
    s = re.sub(r'\s*Official\s+YouTube\s+Channel\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*Official\s+YouTube\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*Official\s*$', '', s, flags=re.IGNORECASE).strip()

    # Remove "Ch. <anything>" (hololive channels etc.)
    s = re.sub(r'\s+Ch\.\s+.*$', '', s).strip()

    # Remove trailing "TV", "HD", "HQ", "Music"
    s = re.sub(r'\s+TV\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+HD\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+HQ\s*$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s+Music\s*$', '', s, flags=re.IGNORECASE).strip()

    # Remove trailing #, _
    s = re.sub(r'[#_]+$', '', s).strip()

    # Remove trailing parenthetical: "Kristin Harris (knightvision1228)"
    s = re.sub(r'\s*\(.*?\)\s*$', '', s).strip()

    # Remove "- (Unreleased)" etc.
    s = re.sub(r'\s*[-–]\s*\(.*?\)\s*$', '', s).strip()

    # Strip collab: "Juice WRLD, Seezyn" → "Juice WRLD"
    if ',' in s:
        s = s.split(',')[0].strip()

    # Clean up residual whitespace
    s = s.strip(' -_.,')

    return s


def get_artist(filepath):
    """Get current artist tag."""
    try:
        ext = filepath.suffix.lower()
        if ext == '.m4a':
            tags = MP4(str(filepath))
            return tags.get('\xa9ART', [''])[0] if tags.get('\xa9ART') else ''
        elif ext == '.mp3':
            tags = MP3(str(filepath))
            return str(tags.get('TPE1', ''))
        elif ext == '.flac':
            tags = FLAC(str(filepath))
            return tags.get('artist', [''])[0] if tags.get('artist') else ''
        elif ext == '.ogg':
            tags = OggVorbis(str(filepath))
            return tags.get('artist', [''])[0] if tags.get('artist') else ''
        elif ext == '.opus':
            tags = OggOpus(str(filepath))
            return tags.get('artist', [''])[0] if tags.get('artist') else ''
        else:
            f = mutagen.File(str(filepath))
            if f and hasattr(f, 'get'):
                return f.get('artist', [''])[0] if f.get('artist') else ''
    except Exception:
        pass
    return ''


def set_artist(filepath, artist):
    """Set artist tag."""
    ext = filepath.suffix.lower()
    if ext == '.m4a':
        tags = MP4(str(filepath))
        tags['\xa9ART'] = [artist]
        tags.save()
    elif ext == '.mp3':
        tags = MP3(str(filepath))
        if tags.tags is None:
            tags.add_tags()
        tags.tags['TPE1'] = TPE1(encoding=3, text=[artist])
        tags.save()
    elif ext == '.flac':
        tags = FLAC(str(filepath))
        tags['artist'] = [artist]
        tags.save()
    elif ext == '.ogg':
        tags = OggVorbis(str(filepath))
        tags['artist'] = [artist]
        tags.save()
    elif ext == '.opus':
        tags = OggOpus(str(filepath))
        tags['artist'] = [artist]
        tags.save()
    else:
        f = mutagen.File(str(filepath))
        if f is not None:
            f['artist'] = [artist]
            f.save()


def main():
    if len(sys.argv) < 2 or '--help' in sys.argv:
        print(__doc__)
        sys.exit(0)

    music_dir = Path(sys.argv[1])
    execute = '--execute' in sys.argv

    if not music_dir.is_dir():
        print(f"Error: {music_dir} is not a directory")
        sys.exit(1)

    changes = []
    already_clean = 0
    errors = []

    for artist_dir in sorted(music_dir.iterdir()):
        if not artist_dir.is_dir():
            continue
        for f in sorted(artist_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in MUSIC_EXTS:
                continue
            try:
                current = get_artist(f)
            except Exception as e:
                errors.append((f, str(e)))
                continue

            if not current:
                continue

            cleaned = clean_artist(current)

            if cleaned == current:
                already_clean += 1
                continue

            changes.append((f, current, cleaned))

    # Report
    print(f"Scanned files across {sum(1 for d in music_dir.iterdir() if d.is_dir())} folders\n")

    if changes:
        print(f"{'=' * 70}")
        print(f"  ARTIST TAGS TO CLEAN ({len(changes)})")
        print(f"{'=' * 70}")
        for fpath, old, new in changes:
            print(f"\n  {fpath.parent.name}/{fpath.name}")
            print(f"    \"{old}\" → \"{new}\"")
    else:
        print("All artist tags are already clean!")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for fpath, err in errors:
            print(f"    {fpath.parent.name}/{fpath.name}: {err}")

    print(f"\n{'=' * 70}")
    print(f"  Already clean: {already_clean}")
    print(f"  To update: {len(changes)}")
    print(f"{'=' * 70}")

    if not execute:
        print("\n  ** DRY RUN ** — Run with --execute to apply.\n")
        return

    print("\nApplying changes...\n")
    success = 0
    for fpath, old, new in changes:
        try:
            set_artist(fpath, new)
            success += 1
            print(f"  ✓ \"{old}\" → \"{new}\"")
        except Exception as e:
            print(f"  ✗ {fpath.name}: {e}")

    print(f"\nDone! Cleaned {success}/{len(changes)} artist tags.")


if __name__ == '__main__':
    main()
