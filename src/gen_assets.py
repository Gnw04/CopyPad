# -*- coding: utf-8 -*-
"""Generate app.ico and PyInstaller version resource."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
S = 256 * 4


def build_icon():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # rounded blue tile
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22),
                        fill=(90, 122, 246, 255))
    d.rounded_rectangle([0, 0, S - 1, int(S * 0.55)], radius=int(S * 0.22),
                        fill=(118, 148, 255, 255))
    # paper
    d.rounded_rectangle([int(S * .26), int(S * .25), int(S * .74), int(S * .81)],
                        radius=int(S * .045), fill=(255, 255, 255, 250))
    # text lines
    for y, w in ((.39, .34), (.49, .36), (.59, .29), (.69, .21)):
        d.rounded_rectangle([int(S * .32), int(S * y),
                             int(S * (.32 + w)), int(S * y + S * .022)],
                            radius=int(S * .011), fill=(109, 140, 255, 225))
    # clip
    d.rounded_rectangle([int(S * .41), int(S * .195), int(S * .59), int(S * .285)],
                        radius=int(S * .024), fill=(255, 255, 255, 255))
    d.rounded_rectangle([int(S * .455), int(S * .215), int(S * .545), int(S * .262)],
                        radius=int(S * .012), fill=(90, 122, 246, 255))
    img = img.resize((256, 256), Image.LANCZOS)
    path = os.path.join(HERE, "app.ico")
    img.save(path, format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon:", path)


VERSION = '''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(2, 0, 0, 0),
    prodvers=(2, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'CopyPad'),
        StringStruct('FileDescription', 'CopyPad Floating Clipboard Pad'),
        StringStruct('FileVersion', '2.0.1.0'),
        StringStruct('InternalName', 'CopyPad'),
        StringStruct('LegalCopyright', 'CopyPad'),
        StringStruct('OriginalFilename', 'CopyPad.exe'),
        StringStruct('ProductName', 'CopyPad'),
        StringStruct('ProductVersion', '2.0.1.0')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''


def build_version():
    p = os.path.join(HERE, "version.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(VERSION)
    print("version:", p)


if __name__ == "__main__":
    build_icon()
    build_version()
