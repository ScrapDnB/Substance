"""Isolated PyAV decoder: never loads Qt/OpenCV into its FFmpeg process."""
import base64
import io
import json
import re
import sys

import numpy as np

def pgs_palette(data, palette):
    offset = 0
    while offset + 3 <= len(data):
        if data[offset:offset+2] == b'PG':
            offset += 10
        if offset + 3 > len(data):
            break
        kind, size = data[offset], int.from_bytes(data[offset+1:offset+3], 'big')
        payload = data[offset+3:offset+3+size]
        if kind == 0x14:
            for j in range(2, len(payload)-4, 5):
                index, y, cr, cb, alpha = payload[j:j+5]
                c, d, e = y - 16, cb - 128, cr - 128
                rgb = np.clip([(298*c + 409*e + 128)//256, (298*c - 100*d - 208*e + 128)//256,
                               (298*c + 516*d + 128)//256], 0, 255)
                palette[index] = [*rgb, alpha]
        offset += 3 + size
    return palette


def dvd_palette(data, global_palette):
    colors, alpha = 0x3210, 0xFFF0
    if len(data) < 8:
        raise ValueError('Повреждён пакет VobSub.')
    at = int.from_bytes(data[2:4], 'big')
    visited = set()
    while at + 4 <= len(data) and at not in visited:
        visited.add(at)
        next_at = int.from_bytes(data[at+2:at+4], 'big')
        pos = at + 4
        sizes = {0: 0, 1: 0, 2: 0, 3: 2, 4: 2, 5: 6, 6: 4}
        while pos < len(data):
            command = data[pos]; pos += 1
            if command == 0xff:
                break
            if command not in sizes:
                raise ValueError('Этот VobSub меняет палитру внутри изображения. Такой вариант пока не поддерживается.')
            size = sizes[command]
            if pos + size > len(data):
                raise ValueError('Оборвана палитра VobSub.')
            if command == 3:
                colors = int.from_bytes(data[pos:pos+2], 'big')
            if command == 4:
                alpha = int.from_bytes(data[pos:pos+2], 'big')
            pos += size
        at = next_at
    palette = np.zeros((256, 4), dtype=np.uint8)
    for i in range(4):
        palette[i, :3] = global_palette[(colors >> (i*4)) & 15]
        palette[i, 3] = ((alpha >> (i*4)) & 15) * 17
    return palette


def bitmap_image(rects, palette):
    rects = [r for r in rects if r.type == b'bitmap' and r.width and r.height]
    if not rects:
        return None
    left, top = min(r.x for r in rects), min(r.y for r in rects)
    right, bottom = max(r.x+r.width for r in rects), max(r.y+r.height for r in rects)
    if not (0 < right-left <= 8192 and 0 < bottom-top <= 8192):
        raise ValueError('Изображение субтитров слишком большое.')
    visible = palette[palette[:, 3] > 128, :3]
    background = 16 if visible.size and visible.mean() >= 128 else 245
    result = np.full((bottom-top, right-left, 3), background, dtype=np.uint8)
    for rect in rects:
        # FFmpeg's subtitle plane is a packed 8-bit palette-index bitmap.
        pixels = np.frombuffer(bytes(rect.planes[0]), dtype=np.uint8).reshape(rect.height, rect.width)
        rgba = palette[pixels]
        alpha = rgba[:, :, 3:4].astype(np.float32) / 255
        behind = result[rect.y-top:rect.y-top+rect.height, rect.x-left:rect.x-left+rect.width][:, :, ::-1]
        rgb = rgba[:, :, :3] * alpha + behind * (1-alpha)
        result[rect.y-top:rect.y-top+rect.height, rect.x-left:rect.x-left+rect.width] = rgb[:, :, ::-1]
    # Give OCR a visible margin around a tightly cropped subtitle rectangle.
    return np.pad(result, ((12, 12), (12, 12), (0, 0)), constant_values=background)


def decode_bitmaps(path, track):
    import av
    from PIL import Image
    palette = np.zeros((256, 4), dtype=np.uint8)
    pending = None
    with av.open(path) as container:
        stream = container.streams[track]
        if stream.codec_context.name not in ('hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub'):
            raise ValueError('Выберите графическую дорожку PGS или VobSub.')
        extra = (stream.codec_context.extradata or b'').decode('ascii', errors='ignore')
        match = re.search(r'palette:\s*([0-9a-fA-F, ]+)', extra)
        global_palette = [tuple(bytes.fromhex(v.strip())) for v in match[1].split(',')] if match else []
        if 'dvd' in stream.codec_context.name and len(global_palette) != 16:
            raise ValueError('В VobSub отсутствует палитра. Откройте файл .idx рядом с .sub.')
        origin = (container.start_time or 0) / 1000 if (container.streams.video or container.streams.audio) else 0
        for packet in container.demux(stream):
            if not packet.size:
                continue
            raw = bytes(packet)
            palette = dvd_palette(raw, global_palette) if 'dvd' in stream.codec_context.name else pgs_palette(raw, palette)
            subset = stream.decode2(packet)
            if subset is None:
                continue
            stamp = subset.pts / 1000 - origin if subset.pts is not None and subset.pts > -1e15 else float(packet.pts * packet.time_base) * 1000 - origin
            start = max(0, round(stamp + subset.start_display_time))
            if pending and start > pending['start']:
                pending['end'] = min(pending['end'], start) if pending['end'] > pending['start'] else start
                yield pending
                pending = None
            image = bitmap_image(subset, palette)
            if image is None:
                continue
            output = io.BytesIO()
            Image.fromarray(image[:, :, ::-1]).save(output, format='PNG')
            end = round(stamp + subset.end_display_time) if 0 < subset.end_display_time < 86400000 else start
            pending = {'start': start, 'end': end, 'image': base64.b64encode(output.getvalue()).decode('ascii')}
        if pending:
            yield pending


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('track', type=int)
    args = parser.parse_args(argv)
    if __package__:
        from .stdio import binary_stdio
    else:
        from stdio import binary_stdio
    output = binary_stdio(sys.stdout, output=True)
    try:
        for row in decode_bitmaps(args.path, args.track):
            output.write((json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8'))
            output.flush()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
