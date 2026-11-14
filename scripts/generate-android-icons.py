"""Generate Android mipmap launcher icons and splash screens from the web app logo."""

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RES_DIR = ROOT / "android" / "app" / "src" / "main" / "res"
LOGO_PATH = ROOT / "frontend" / "icons" / "icon-512.png"

BG_RGBA = (15, 23, 42, 255)  # #0F172A matching icon-maskable-512 background

DENSITIES = {
    "mdpi": (48, 108),
    "hdpi": (72, 162),
    "xhdpi": (96, 216),
    "xxhdpi": (144, 324),
    "xxxhdpi": (192, 432),
}

SPLASH_SIZES = {
    "drawable/splash.png": (480, 320),
    "drawable-land-mdpi/splash.png": (480, 320),
    "drawable-land-hdpi/splash.png": (800, 480),
    "drawable-land-xhdpi/splash.png": (1280, 720),
    "drawable-land-xxhdpi/splash.png": (1600, 960),
    "drawable-land-xxxhdpi/splash.png": (1920, 1280),
    "drawable-port-mdpi/splash.png": (320, 480),
    "drawable-port-hdpi/splash.png": (480, 800),
    "drawable-port-xhdpi/splash.png": (720, 1280),
    "drawable-port-xxhdpi/splash.png": (960, 1600),
    "drawable-port-xxxhdpi/splash.png": (1280, 1920),
}


def render_centered(logo: Image.Image, canvas_size: tuple[int, int], logo_px: int, bg_rgba: tuple[int, int, int, int]) -> Image.Image:
    w, h = canvas_size
    canvas = Image.new("RGBA", (w, h), bg_rgba)
    resized = logo.resize((logo_px, logo_px), Image.Resampling.LANCZOS)
    pos = ((w - logo_px) // 2, (h - logo_px) // 2)
    canvas.paste(resized, pos, resized)
    return canvas


def render_rounded_legacy(logo: Image.Image, size: int) -> Image.Image:
    scale = 4
    hi = size * scale
    canvas = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    mask = Image.new("L", (hi, hi), 0)
    draw = ImageDraw.Draw(mask)
    radius = round(hi * 0.20)
    draw.rounded_rectangle((0, 0, hi - 1, hi - 1), radius=radius, fill=255)
    bg = Image.new("RGBA", (hi, hi), BG_RGBA)
    canvas.paste(bg, (0, 0), mask)

    logo_px = round(hi * 0.86)
    resized = logo.resize((logo_px, logo_px), Image.Resampling.LANCZOS)
    pos = ((hi - logo_px) // 2, (hi - logo_px) // 2)
    canvas.paste(resized, pos, resized)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def render_round_legacy(logo: Image.Image, size: int) -> Image.Image:
    scale = 4
    hi = size * scale
    canvas = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    mask = Image.new("L", (hi, hi), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, hi - 1, hi - 1), fill=255)
    bg = Image.new("RGBA", (hi, hi), BG_RGBA)
    canvas.paste(bg, (0, 0), mask)

    logo_px = round(hi * 0.96)
    resized = logo.resize((logo_px, logo_px), Image.Resampling.LANCZOS)
    pos = ((hi - logo_px) // 2, (hi - logo_px) // 2)
    canvas.paste(resized, pos, resized)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    logo = Image.open(LOGO_PATH).convert("RGBA")

    for density, (icon_px, fg_px) in DENSITIES.items():
        mipmap_dir = RES_DIR / f"mipmap-{density}"
        render_rounded_legacy(logo, icon_px).save(mipmap_dir / "ic_launcher.png")
        render_round_legacy(logo, icon_px).save(mipmap_dir / "ic_launcher_round.png")
        render_centered(logo, (fg_px, fg_px), round(fg_px * 0.66), (0, 0, 0, 0)).save(
            mipmap_dir / "ic_launcher_foreground.png"
        )

    for rel_path, (w, h) in SPLASH_SIZES.items():
        out_path = RES_DIR / rel_path
        logo_px = max(120, round(min(w, h) * 0.42))
        render_centered(logo, (w, h), logo_px, BG_RGBA).save(out_path)

    print(f"Generated {len(DENSITIES) * 3} mipmap icons and {len(SPLASH_SIZES)} splash screens.")


if __name__ == "__main__":
    main()
