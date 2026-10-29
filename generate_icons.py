"""Generate PWA icons as simple SVG-based PNGs using pure Python."""
import os
import struct
import zlib

ICON_DIR = os.path.join(os.path.dirname(__file__), "static", "icons")
os.makedirs(ICON_DIR, exist_ok=True)

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]


def create_png(width, height, pixels_rgba):
    """Create a minimal valid PNG file from RGBA pixel data."""
    def chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))

    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # filter: none
        for x in range(width):
            idx = (y * width + x) * 4
            raw_data += bytes(pixels_rgba[idx:idx+4])

    idat = chunk(b'IDAT', zlib.compress(raw_data, 9))
    iend = chunk(b'IEND', b'')

    return header + ihdr + idat + iend


def generate_icon(size):
    """Generate a Pluxee-themed icon at given size."""
    pixels = [0] * (size * size * 4)
    cx, cy = size / 2, size / 2
    r_outer = size * 0.45
    r_inner = size * 0.28

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5

            if dist <= r_outer:
                # Gradient from purple (#7c5cfc) to blue (#4facfe)
                t = dist / r_outer
                r = int(124 + (79 - 124) * t)
                g = int(92 + (172 - 92) * t)
                b = int(252 + (254 - 252) * t)
                a = 255

                # Inner circle: lighter
                if dist <= r_inner:
                    t2 = dist / r_inner
                    r = int(255 - (255 - r) * t2 * 0.6)
                    g = int(255 - (255 - g) * t2 * 0.6)
                    b = int(255 - (255 - b) * t2 * 0.6)

                # Anti-aliasing at edge
                if dist > r_outer - 1.5:
                    a = int(255 * max(0, (r_outer - dist) / 1.5))

                pixels[idx] = min(255, max(0, r))
                pixels[idx+1] = min(255, max(0, g))
                pixels[idx+2] = min(255, max(0, b))
                pixels[idx+3] = a
            else:
                # Transparent
                pixels[idx:idx+4] = [0, 0, 0, 0]

    # Draw a "P" letter (simplified) in the center
    letter_size = int(size * 0.3)
    lx_start = int(cx - letter_size * 0.3)
    ly_start = int(cy - letter_size * 0.45)

    # Vertical bar of P
    bar_w = max(2, int(size * 0.06))
    for dy in range(int(letter_size * 0.9)):
        for dx in range(bar_w):
            px = lx_start + dx
            py = ly_start + dy
            if 0 <= px < size and 0 <= py < size:
                idx = (py * size + px) * 4
                pixels[idx:idx+4] = [255, 255, 255, 230]

    # Top arc of P (simplified as rectangle + right bump)
    arc_h = max(2, int(letter_size * 0.35))
    arc_w = max(3, int(letter_size * 0.4))
    for dy in range(arc_h):
        for dx in range(arc_w):
            px = lx_start + bar_w + dx
            py = ly_start + dy
            if 0 <= px < size and 0 <= py < size:
                idx = (py * size + px) * 4
                pixels[idx:idx+4] = [255, 255, 255, 200]

    # Bottom of P bump
    bump_y = ly_start + arc_h
    for dx in range(arc_w):
        px = lx_start + bar_w + dx
        py = bump_y
        if 0 <= px < size and 0 <= py < size:
            idx = (py * size + px) * 4
            pixels[idx:idx+4] = [255, 255, 255, 200]

    return create_png(size, size, pixels)


def generate_badge(size):
    """Generate a small badge icon (monochrome)."""
    pixels = [0] * (size * size * 4)
    cx, cy = size / 2, size / 2
    r = size * 0.4

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= r:
                a = 255
                if dist > r - 1.5:
                    a = int(255 * max(0, (r - dist) / 1.5))
                pixels[idx:idx+4] = [124, 92, 252, a]

    return create_png(size, size, pixels)


if __name__ == "__main__":
    for sz in SIZES:
        data = generate_icon(sz)
        path = os.path.join(ICON_DIR, f"icon-{sz}.png")
        with open(path, "wb") as f:
            f.write(data)
        print(f"Generated {path} ({len(data)} bytes)")

    # Badge icon
    data = generate_badge(72)
    path = os.path.join(ICON_DIR, "badge-72.png")
    with open(path, "wb") as f:
        f.write(data)
    print(f"Generated {path} ({len(data)} bytes)")

    print("All icons generated!")
