"""Build window/taskbar icons (Pillow).

  .venv\\Scripts\\python.exe scripts\\prepare_branding_assets.py
      → Ncurity Home 배너 + 작업표시줄 아이콘만 갱신
  .venv\\Scripts\\python.exe scripts\\prepare_branding_assets.py --f5-only
      → F5 아이콘만 (선택)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "app" / "resources"
_CURSOR_ASSETS = (
    Path.home()
    / ".cursor"
    / "projects"
    / "c-Users-ejes3-Ejes-OneDrive-OneDrive-Ncurity-WorksFiles-F5-Project-Config-Rules-Apps-AI-First"
    / "assets"
)
_F5_LOGO_NAME = (
    "c__Users_ejes3_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_"
    "f5-logo-6d8929f3-8d31-47f0-b172-a354addb446e.png"
)
_NCURITY_HOME_LOGO_NAME = (
    "c__Users_ejes3_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_"
    "BIG_________Blue-eb210af6-63a2-4899-91cb-42011692aef0.png"
)
_NCURITY_ICON_LOGO_NAME = (
    "c__Users_ejes3_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_"
    "BIG_________Blue-08534bac-ac0e-46ff-bd2e-4acab59bc1e1.png"
)
_NCURITY_ONLY_BLUE_LOGO_NAME = (
    "c__Users_ejes3_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_"
    "BIG_Logo_OnlyBlue-a83fb399-bb1a-4773-ac91-f9b7ae95d6a4.png"
)
_NCURITY_HOME_WHITE_LOGO_NAME = (
    "c__Users_ejes3_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_"
    "BIG_________White-2328704d-2e39-4456-a933-7e6fc9457b85.png"
)
NCURITY_HOME_MAX_HEIGHT = 118
NCURITY_HOME_WHITE_MAX_HEIGHT = 64
NCURITY_ICON_CANVAS = 512
# 작업 표시줄·타이틀바: 심볼이 잘리지 않으면서도 24/32px에서 너무 작지 않게
NCURITY_ICON_MARGIN_RATIO = 0.10
# 가로형(심볼|텍스트): 왼쪽만 — 글자 제외
NCURITY_SYMBOL_LEFT_FRAC = 0.44
# 세로형(심볼 위·텍스트 아래): 위쪽만 — 글자 제외
NCURITY_SYMBOL_TOP_FRAC = 0.42
# w/h 가 이 값보다 크면 “가로 로고”로 보고 왼쪽만 자름
NCURITY_SYMBOL_WIDE_RATIO = 1.12
# .ico 안에 넣을 정사각 레이어(px). 큰 원본에서 각각 리샘플 → 다운스케일보다 선명.
# (작업 표시줄은 보통 24·32·48 계열; 256은 고해상도·exe용)
NCURITY_ICO_LAYERS: tuple[int, ...] = (256, 128, 96, 64, 48, 40, 32, 24, 20, 16)
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def _resolve(*candidates: Path) -> Path:
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def _black_to_alpha(img, *, threshold: int = 28):
    from PIL import Image

    rgba = img.convert("RGBA")
    pixels = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r <= threshold and g <= threshold and b <= threshold:
                pixels[x, y] = (r, g, b, 0)
    return rgba


def _fit_square(img, *, canvas: int, padding: int = 6):
    from PIL import Image

    rgba = img.convert("RGBA")
    bbox = rgba.getbbox()
    if not bbox:
        return rgba.resize((canvas, canvas), Image.Resampling.LANCZOS)
    cropped = rgba.crop(bbox)
    inner = canvas - padding * 2
    cw, ch = cropped.size
    scale = min(inner / cw, inner / ch)
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    resized = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    square.paste(resized, ((canvas - nw) // 2, (canvas - nh) // 2), resized)
    return square


def _alpha_bbox(img, *, alpha_floor: int = 8):
    """Tighter than getbbox(): ignore nearly-transparent fringe."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > alpha_floor:
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def _trim_transparent_hard(img, *, alpha_floor: int = 8):
    bbox = _alpha_bbox(img, alpha_floor=alpha_floor)
    if bbox:
        return img.crop(bbox)
    return _trim_transparent(img)


def _fit_square_tight(
    img,
    *,
    canvas: int,
    margin_ratio: float = NCURITY_ICON_MARGIN_RATIO,
    bg: tuple[int, int, int, int] | None = None,
):
    """Trim edges and scale symbol to fill the canvas (optional opaque bg)."""
    from PIL import Image

    cropped = _trim_transparent_hard(img.convert("RGBA"))
    if not cropped.getbbox():
        return Image.new("RGBA", (canvas, canvas), bg or (0, 0, 0, 0))
    cw, ch = cropped.size
    margin = int(round(canvas * margin_ratio)) if margin_ratio > 0 else 0
    inner = max(1, canvas - margin * 2)
    scale = min(inner / cw, inner / ch)
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    resized = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
    base = Image.new("RGBA", (canvas, canvas), bg if bg is not None else (0, 0, 0, 0))
    base.paste(resized, ((canvas - nw) // 2, (canvas - nh) // 2), resized)
    return base


def _pad_uniform_rgba(img, *, pad_ratio: float = 0.06):
    """원본이 가장자리에 붙어 있으면 작은 해상도에서 잘린 것처럼 보일 수 있어 여백 추가."""
    from PIL import Image

    w, h = img.size
    pad = max(1, int(max(w, h) * pad_ratio))
    nw, nh = w + pad * 2, h + pad * 2
    out = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    out.paste(img, (pad, pad), img)
    return out


def _icon_src_is_whole_symbol_only(path: Path) -> bool:
    """가로/세로 비율로 자르지 않고 전체 래스터를 아이콘에 넣음."""
    n = path.name.lower()
    if n == "ncurity_symbol_only_source.png":
        return True
    if "onlyblue" in n:
        return True
    if n == "ncurity_icon_source.png":
        return True
    return False


def _raster_symbol_no_crop(source: Path):
    """검은 배경 → 투명, 알파 bbox 트림. (OnlyBlue 등 심볼 전용 PNG)"""
    from PIL import Image

    raw = Image.open(source)
    return _trim_transparent_hard(_black_to_alpha(raw))


def _crop_ncurity_symbol(source):
    """심볼만 (한글/영문 텍스트 제외). 가로·세로 원본 모두 지원."""
    from PIL import Image

    raw = Image.open(source)
    w, h = raw.size
    wide = w > h * NCURITY_SYMBOL_WIDE_RATIO
    if wide:
        # 가로: 심볼은 보통 왼쪽, 텍스트는 오른쪽
        sym_w = max(1, int(w * NCURITY_SYMBOL_LEFT_FRAC))
        region = raw.crop((0, 0, sym_w, h))
    else:
        # 세로: 심볼은 위, 텍스트는 아래
        sym_h = max(1, int(h * NCURITY_SYMBOL_TOP_FRAC))
        region = raw.crop((0, 0, w, sym_h))
    return _trim_transparent_hard(_black_to_alpha(region))


def _save_ncurity_app_icons(symbol, out_dir: Path) -> None:
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    # 투명 배경 + 여백으로 심볼 전체가 보이도록
    master = _fit_square_tight(
        symbol,
        canvas=NCURITY_ICON_CANVAS,
        margin_ratio=NCURITY_ICON_MARGIN_RATIO,
        bg=None,
    )
    png_path = out_dir / "ncurity_app_icon.png"
    master.save(png_path, format="PNG", optimize=True)
    ico_path = out_dir / "ncurity_app_icon.ico"
    layers = [master.resize((s, s), Image.Resampling.LANCZOS) for s in NCURITY_ICO_LAYERS]
    if layers:
        first, *rest = layers
        first.save(ico_path, format="ICO", append_images=rest)
    print(f"Wrote {png_path} ({master.size[0]}x{master.size[1]})")
    print(f"Wrote {ico_path} (layers: {', '.join(str(s) for s in NCURITY_ICO_LAYERS)})")


def build_f5_icons(source: Path, out_dir: Path) -> None:
    from PIL import Image

    raw = _black_to_alpha(Image.open(source))
    out_dir.mkdir(parents=True, exist_ok=True)
    master = _fit_square(raw, canvas=256, padding=8)
    master.save(out_dir / "f5_app_icon.png", format="PNG", optimize=True)
    master.save(out_dir / "f5_app_icon.ico", format="ICO", sizes=ICO_SIZES)
    print(f"Wrote {out_dir / 'f5_app_icon.png'}")
    print(f"Wrote {out_dir / 'f5_app_icon.ico'}")


def _trim_transparent(img):
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def _scale_to_height(img, max_height: int):
    from PIL import Image

    w, h = img.size
    if h <= 0:
        return img
    scale = max_height / h
    nw = max(1, int(w * scale))
    return img.resize((nw, max_height), Image.Resampling.LANCZOS)


def build_ncurity_home_banner(source: Path, out_dir: Path, *, max_height: int = NCURITY_HOME_MAX_HEIGHT) -> None:
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = _trim_transparent(_black_to_alpha(Image.open(source)))
    banner = _scale_to_height(raw, max_height)
    path = out_dir / "ncurity_home_logo.png"
    banner.save(path, format="PNG", optimize=True)
    print(f"Wrote {path} ({banner.size[0]}x{banner.size[1]})")


def build_combobox_chevron(out_dir: Path) -> None:
    """Blue chevron for QComboBox drop-down (GUI theme)."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(3, 5), (13, 5), (8, 12)], fill=(2, 96, 234, 255))
    path = out_dir / "combobox_chevron.png"
    img.save(path, format="PNG", optimize=True)
    print(f"Wrote {path}")


def build_theme_checkbox_icons(out_dir: Path) -> None:
    """Checkbox PNGs for Fusion QSS (unchecked border + checked blue tick)."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    unchecked = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
    udraw = ImageDraw.Draw(unchecked)
    udraw.rounded_rectangle((0, 0, 21, 21), radius=4, fill=(255, 255, 255, 255))
    udraw.rounded_rectangle((0, 0, 21, 21), radius=4, outline=(100, 116, 139, 255), width=2)
    unchecked_path = out_dir / "checkbox_unchecked.png"
    unchecked.save(unchecked_path, format="PNG", optimize=True)

    checked = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(checked)
    cdraw.rounded_rectangle((0, 0, 21, 21), radius=4, fill=(2, 96, 234, 255))
    cdraw.line([(5, 11), (9, 15), (17, 7)], fill=(255, 255, 255, 255), width=2)
    checked_path = out_dir / "checkbox_checked.png"
    checked.save(checked_path, format="PNG", optimize=True)
    print(f"Wrote {unchecked_path}")
    print(f"Wrote {checked_path}")


def build_ncurity_home_white(source: Path, out_dir: Path, *, max_height: int = NCURITY_HOME_WHITE_MAX_HEIGHT) -> None:
    """White logo for blue UI strips (black background → transparent)."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = _trim_transparent(_black_to_alpha(Image.open(source)))
    banner = _scale_to_height(raw, max_height)
    path = out_dir / "ncurity_home_logo_white.png"
    banner.save(path, format="PNG", optimize=True)
    print(f"Wrote {path} ({banner.size[0]}x{banner.size[1]})")


def build_ncurity_icons(source: Path, out_dir: Path) -> None:
    if _icon_src_is_whole_symbol_only(source):
        symbol = _raster_symbol_no_crop(source)
        symbol = _pad_uniform_rgba(symbol, pad_ratio=0.06)
    else:
        symbol = _crop_ncurity_symbol(source)
    _save_ncurity_app_icons(symbol, out_dir)


def main(argv: list[str]) -> int:
    f5_only = "--f5-only" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Install Pillow: .venv\\Scripts\\pip install Pillow", file=sys.stderr)
        return 1

    try:
        if f5_only:
            f5_src = Path(args[0]) if args else _resolve(
                OUT_DIR / "f5_logo_source.png",
                _CURSOR_ASSETS / _F5_LOGO_NAME,
            )
            build_f5_icons(f5_src, OUT_DIR)
        if not f5_only:
            home_src = _resolve(
                OUT_DIR / "ncurity_home_source.png",
                OUT_DIR / "ncurity_logo_source.png",
                _CURSOR_ASSETS / _NCURITY_HOME_LOGO_NAME,
                _CURSOR_ASSETS / _NCURITY_ICON_LOGO_NAME,
            )
            if home_src.is_file():
                build_ncurity_home_banner(home_src, OUT_DIR)
            white_src = _resolve(
                OUT_DIR / "ncurity_home_logo_white_source.png",
                _CURSOR_ASSETS / _NCURITY_HOME_WHITE_LOGO_NAME,
            )
            if white_src.is_file():
                build_ncurity_home_white(white_src, OUT_DIR)
            # 심볼 전용 OnlyBlue / ncurity_symbol_only_source.png 최우선 (가로·세로 비율 자르기 없음)
            icon_src = _resolve(
                OUT_DIR / "ncurity_icon_source.png",
                OUT_DIR / "ncurity_symbol_only_source.png",
                _CURSOR_ASSETS / _NCURITY_ONLY_BLUE_LOGO_NAME,
                OUT_DIR / "ncurity_logo_source.png",
                _CURSOR_ASSETS / _NCURITY_ICON_LOGO_NAME,
                _CURSOR_ASSETS / _NCURITY_HOME_LOGO_NAME,
            )
            if icon_src.is_file():
                build_ncurity_icons(icon_src, OUT_DIR)
            build_theme_checkbox_icons(OUT_DIR)
            build_combobox_chevron(OUT_DIR)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
