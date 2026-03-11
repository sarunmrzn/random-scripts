#!/usr/bin/env python3
"""
fix_artist_tags.py - Set each music file's artist metadata to its parent folder name.

Usage:
    python3 fix_artist_tags.py /DATA/Media/Music/Youtube              # Dry run
    python3 fix_artist_tags.py /DATA/Media/Music/Youtube --execute    # Apply changes
"""

import sys
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
    print("mutagen is required. Install it:")
    print("  pip install mutagen")
    sys.exit(1)

MUSIC_EXTS = {'.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav', '.wma', '.aac', '.webm'}


def get_artist(filepath):
    """Get current artist tag from a music file."""
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
        elif ext in ('.ogg',):
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
    """Set artist tag on a music file."""
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
    elif ext in ('.ogg',):
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
    errors = []
    already_correct = 0

    for artist_dir in sorted(music_dir.iterdir()):
        if not artist_dir.is_dir():
            continue

        artist_name = artist_dir.name

        for f in sorted(artist_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in MUSIC_EXTS:
                continue

            try:
                current = get_artist(f)
            except Exception as e:
                errors.append((f, str(e)))
                continue

            if current == artist_name:
                already_correct += 1
                continue

            changes.append((f, current, artist_name))

    # Report
    print(f"Scanned {already_correct + len(changes) + len(errors)} files\n")

    if changes:
        print(f"{'=' * 70}")
        print(f"  FILES TO UPDATE ({len(changes)})")
        print(f"{'=' * 70}")

        current_artist = None
        for fpath, old, new in changes:
            if new != current_artist:
                current_artist = new
                print(f"\n  {new}/")
            old_display = old if old else '(empty)'
            print(f"    {fpath.name}")
            print(f"      artist: {old_display} → {new}")
    else:
        print("All files already have correct artist tags!")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for fpath, err in errors:
            print(f"    {fpath.parent.name}/{fpath.name}: {err}")

    print(f"\n{'=' * 70}")
    print(f"  Already correct: {already_correct}")
    print(f"  To update: {len(changes)}")
    print(f"  Errors: {len(errors)}")
    print(f"{'=' * 70}")

    if not execute:
        print("\n  ** DRY RUN ** — Run with --execute to apply.\n")
        return

    # Apply
    print("\nApplying changes...\n")
    success = 0
    for fpath, old, new in changes:
        try:
            set_artist(fpath, new)
            success += 1
        except Exception as e:
            print(f"  Failed: {fpath.parent.name}/{fpath.name}: {e}")

    print(f"\nDone! Updated {success}/{len(changes)} files.")


if __name__ == '__main__':
    main()
