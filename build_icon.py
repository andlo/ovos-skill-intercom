"""Generates icon.png - 512x512, rounded-rect background (radius 90),
white line-art of a doorbell/intercom speaker grille - matching the
style of the other skills' icons."""

from PIL import Image, ImageDraw

SIZE = 512
BG_COLOR = (196, 90, 40, 255)  # warm terracotta, distinct from siblings
WHITE = (255, 255, 255, 255)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=90, fill=BG_COLOR)

# Outer intercom panel
panel = [136, 96, 376, 416]
draw.rounded_rectangle(panel, radius=28, outline=WHITE, width=14)

# Speaker grille - rows of small horizontal slits
grille_left, grille_right = 170, 342
slit_h = 10
slit_gap = 14
slit_top = 140
for i in range(6):
    y0 = slit_top + i * (slit_h + slit_gap)
    draw.rounded_rectangle([grille_left, y0, grille_right, y0 + slit_h],
                            radius=5, fill=WHITE)

# Single call button below the grille
button_cx, button_cy, button_r = 256, 360, 26
draw.ellipse([button_cx - button_r, button_cy - button_r,
              button_cx + button_r, button_cy + button_r],
             outline=WHITE, width=10)

img.save("icon.png")
print("wrote icon.png", img.size, img.mode)
