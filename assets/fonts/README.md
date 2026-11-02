# Bundled PDF font

`Vazirmatn-Regular.ttf` is an offline container-format conversion of the existing
`qpanel/themes/qpanel/static/fonts/Vazirmatn-Regular.woff2`. Glyphs and font names
were retained. The original authors' SIL Open Font License is included in
`OFL.txt`; the font is not sold separately. No font is downloaded at runtime.

Reproduction with FontTools 4.60.1 and Brotli 1.1.0 (development tools only):

```python
from fontTools.ttLib import TTFont
font = TTFont('qpanel/themes/qpanel/static/fonts/Vazirmatn-Regular.woff2')
font.flavor = None
font.save('assets/fonts/Vazirmatn-Regular.ttf')
```

The PDF worker reads this fixed asset through a bounded regular-file descriptor
and embeds the needed TrueType glyph subset. Arabic presentation-form glyphs
required by the Persian shaping adapter are present in its character map.
