import sys

if '--decode-bitmaps' in sys.argv:
    from substance.bitmap_decode import main as decode_main
    raise SystemExit(decode_main(sys.argv[sys.argv.index('--decode-bitmaps') + 1:]))

from substance.app import main

if __name__ == "__main__":
    raise SystemExit(main())
