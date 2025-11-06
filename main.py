import js
import random
from pyodide.ffi import create_proxy

# ===== Canvas / Context =====
canvas = js.document.getElementById("gameCanvas")
ctx = canvas.getContext("2d")
CW, CH = canvas.width, canvas.height

# ===== Constants =====
BLOCK_SIZE = 30
ROWS = 15
COLS = 10

COLORS = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FFA500", "#800080", "#00FFFF"]

SHAPES = [
   [[1, 1, 1, 1]],                 # I
   [[1, 1], [1, 1]],               # O
   [[0, 1, 0], [1, 1, 1]],         # T
   [[1, 0, 0], [1, 1, 1]],         # L
   [[0, 0, 1], [1, 1, 1]],         # J
   [[1, 1, 0], [0, 1, 1]],         # S
   [[0, 1, 1], [1, 1, 0]]          # Z
]

# Steady game tick
TICK_MS = 50                       # ~20 FPS heartbeat

# Soft drop timing
MIN_DROP_MS = 50                   # min fall interval while dropping
BURST_MS = 180                     # tap burst duration for Down

# ===== State =====
grid = [[0 for _ in range(COLS)] for _ in range(ROWS)]

current_shape = random.choice(SHAPES)
current_color = random.choice(COLORS)
next_shape = random.choice(SHAPES)
next_color = random.choice(COLORS)
shape_pos = [COLS // 2 - len(current_shape[0]) // 2, 0]

score = 0
game_over = False

# ----- SPEED / TIMER (from your last setup) -----
BASE_SPEED = 5.0                   # start immediately at x5.0
speed_multiplier = BASE_SPEED

start_time = js.Date.now()
game_duration = 30                 # seconds

# Vertical soft drop (Down only)
soft_drop_hold = False
soft_drop_burst = False
burst_timer_down = None

# Accumulators
fall_accum_ms = 0

# ===== Transparent Playfield Backdrop =====
def _is_mobile():
   try:
       return js.document.documentElement.clientWidth <= 480
   except Exception:
       return False

BG_ALPHA_DESKTOP = 0.70
BG_ALPHA_MOBILE  = 0.70

GRID_LINE_ALPHA         = 0.28
GRID_LINE_ALPHA_STRONG  = 0.85

def clear_and_paint_background():
   """Clear the canvas and paint a single semi-transparent panel so the logo shows through."""
   ctx.clearRect(0, 0, CW, CH)
   alpha = BG_ALPHA_MOBILE if _is_mobile() else BG_ALPHA_DESKTOP
   ctx.fillStyle = f"rgba(0,0,0,{alpha})"
   ctx.fillRect(0, 0, CW, CH)

# ===== Drawing =====
def stroke_cell(x, y, alpha):
   ctx.strokeStyle = f"rgba(255,255,255,{alpha})"
   ctx.strokeRect(x * BLOCK_SIZE, y * BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE)

def fill_cell(x, y, color):
   ctx.fillStyle = color
   ctx.fillRect(x * BLOCK_SIZE, y * BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE)
   stroke_cell(x, y, GRID_LINE_ALPHA_STRONG)

def draw_grid():
   for y in range(ROWS):
       for x in range(COLS):
           if grid[y][x] == 0:
               stroke_cell(x, y, GRID_LINE_ALPHA)
           else:
               fill_cell(x, y, grid[y][x])

def draw_shape(shape, pos, color):
   for y, row in enumerate(shape):
       for x, cell in enumerate(row):
           if cell:
               fill_cell(pos[0] + x, pos[1] + y, color)

def _rgba_from_hex(hex_color: str, alpha: float) -> str:
   """Convert '#RRGGBB' to 'rgba(r,g,b,alpha)'."""
   hex_color = hex_color.lstrip('#')
   r = int(hex_color[0:2], 16)
   g = int(hex_color[2:4], 16)
   b = int(hex_color[4:6], 16)
   return f"rgba({r},{g},{b},{alpha})"

def draw_ghost(shape, pos):
   """
   More visible ghost:
     - semi-transparent fill (tinted with current piece color)
     - strong white outline so it stands out on any background/logo
   """
   # find landing Y
   ghost_pos = pos[:]
   while not check_collision(shape, [ghost_pos[0], ghost_pos[1] + 1]):
       ghost_pos[1] += 1

   # draw filled tinted blocks
   ctx.save()
   ctx.globalAlpha = 1.0
   tint = _rgba_from_hex(current_color, 0.35)  # colored fill
   ctx.lineWidth = 2.0
   for y, row in enumerate(shape):
       for x, cell in enumerate(row):
           if cell:
               gx = (ghost_pos[0] + x) * BLOCK_SIZE
               gy = (ghost_pos[1] + y) * BLOCK_SIZE
               # fill
               ctx.fillStyle = tint
               ctx.fillRect(gx, gy, BLOCK_SIZE, BLOCK_SIZE)
               # bright outline
               ctx.strokeStyle = "rgba(255,255,255,0.95)"
               ctx.strokeRect(gx + 0.5, gy + 0.5, BLOCK_SIZE - 1, BLOCK_SIZE - 1)
   ctx.restore()

def draw_next_shape():
   ctx.fillStyle = "rgba(0,0,0,0.35)"
   ctx.fillRect(210, 4, 84, 56)
   ctx.fillStyle = "white"
   ctx.font = "16px Arial"
   ctx.fillText("Next:", 220, 20)
   for y, row in enumerate(next_shape):
       for x, cell in enumerate(row):
           if cell:
               ctx.fillStyle = next_color
               ctx.fillRect(220 + x * 15, 30 + y * 15, 15, 15)
               ctx.strokeStyle = "rgba(0,0,0,0.8)"
               ctx.strokeRect(220 + x * 15, 30 + y * 15, 15, 15)

def draw_info():
   ctx.font = "20px Arial"
   ctx.fillStyle = "yellow"
   ctx.fillText(f"Score: {score}", 10, 20)
   elapsed = (js.Date.now() - start_time) / 1000
   time_left = max(0, game_duration - int(elapsed))
   ctx.fillText(f"Time: {time_left}s", 10, 45)

   dropping = soft_drop_hold or soft_drop_burst
   ctx.fillText(f"Speed: x{speed_multiplier:.2f}" + (" (drop)" if dropping else ""), 10, 70)

   draw_next_shape()
   return time_left

# ===== Logic =====
def check_collision(shape, pos):
   for y, row in enumerate(shape):
       for x, cell in enumerate(row):
           if cell:
               nx = pos[0] + x
               ny = pos[1] + y
               if nx < 0 or nx >= COLS or ny >= ROWS:
                   return True
               if ny >= 0 and grid[ny][nx] != 0:
                   return True
   return False

def merge_shape(shape, pos, color):
   for y, row in enumerate(shape):
       for x, cell in enumerate(row):
           if cell:
               grid[pos[1] + y][pos[0] + x] = color

def clear_lines():
   global grid, score
   new_grid = [row for row in grid if 0 in row]
   lines_cleared = ROWS - len(new_grid)
   score += [0, 10, 30, 60, 100][lines_cleared] if lines_cleared <= 4 else lines_cleared * 10
   while len(new_grid) < ROWS:
       new_grid.insert(0, [0 for _ in range(COLS)])
   grid = new_grid

def new_piece():
   global current_shape, current_color, next_shape, next_color, shape_pos
   global game_over
   current_shape = next_shape
   current_color = next_color
   next_shape = random.choice(SHAPES)
   next_color = random.choice(COLORS)
   shape_pos = [COLS // 2 - len(current_shape[0]) // 2, 0]
   if check_collision(current_shape, shape_pos):
       end_game("gameover")

def current_fall_interval_ms():
   base = int(1000 / max(0.01, speed_multiplier))
   if soft_drop_hold or soft_drop_burst:
       return max(MIN_DROP_MS, base // 6)
   return base

def adjust_speed():
   """Keep at least BASE_SPEED (x5.0); only increase when score crosses thresholds."""
   global speed_multiplier
   target = max(BASE_SPEED, 1.0 + (score // 30) * 0.25)
   if target != speed_multiplier:
       speed_multiplier = target

# Helpers for moving safely
def move_left():
   shape_pos[0] -= 1
   if check_collision(current_shape, shape_pos):
       shape_pos[0] += 1

def move_right():
   shape_pos[0] += 1
   if check_collision(current_shape, shape_pos):
       shape_pos[0] -= 1

def rotate_cw():
   global current_shape
   rotated = [list(row) for row in zip(*current_shape[::-1])]
   if not check_collision(rotated, shape_pos):
       current_shape = rotated

def end_game(reason: str):
   """reason: 'gameover' or 'timeup'"""
   global game_over
   if game_over:
       return
   game_over = True
   msg = "Game Over!" if reason == "gameover" else "Time Up!"
   js.document.getElementById("gameLoading").innerText = f"{msg} Score: {score}"
   js.document.getElementById("restartBtn").style.display = "inline-block"
   try:
       js.onGameOver(int(score), reason)
   except Exception:
       pass
# ===== Main loop (steady tick) =====
def game_loop():
   global shape_pos, fall_accum_ms
   if game_over:
       return

   fall_accum_ms += TICK_MS
   interval_needed = current_fall_interval_ms()
   while fall_accum_ms >= interval_needed and not game_over:
       fall_accum_ms -= interval_needed
       shape_pos[1] += 1
       if check_collision(current_shape, shape_pos):
           shape_pos[1] -= 1
           merge_shape(current_shape, shape_pos, current_color)
           clear_lines()
           adjust_speed()
           new_piece()

   clear_and_paint_background()
   draw_grid()
   draw_ghost(current_shape, shape_pos)
   draw_shape(current_shape, shape_pos, current_color)
   time_left = draw_info()

   if time_left <= 0 and not game_over:
       end_game("timeup")

# ===== Input =====
def _norm_key(event):
   try:
       key = event.key
       try:
           event.preventDefault()
       except Exception:
           pass
       return key
   except Exception:
       if isinstance(event, dict):
           return event.get("key")
       return str(event)

def on_key(event):
   """Public: called from JS for on-screen buttons too."""
   global fall_accum_ms
   if game_over:
       return
   key = _norm_key(event)
   if key == "ArrowLeft":
       move_left()
   elif key == "ArrowRight":
       move_right()
   elif key == "ArrowDown":
       shape_pos[1] += 1
       if check_collision(current_shape, shape_pos):
           shape_pos[1] -= 1
       fall_accum_ms = 0
   elif key == "ArrowUp":
       rotate_cw()

   clear_and_paint_background()
   draw_grid()
   draw_ghost(current_shape, shape_pos)
   draw_shape(current_shape, shape_pos, current_color)
   draw_info()

# --- Soft drop (Down only) ---
def start_soft_drop_hold():
   global soft_drop_hold
   if not game_over and not soft_drop_hold:
       soft_drop_hold = True

def stop_soft_drop_hold():
   global soft_drop_hold
   if soft_drop_hold:
       soft_drop_hold = False

def _end_down_burst():
   global soft_drop_burst
   soft_drop_burst = False
_end_down_burst_proxy = create_proxy(_end_down_burst)

def soft_drop_tap():
   """Tap = brief faster fall."""
   global soft_drop_burst, burst_timer_down
   if game_over:
       return
   soft_drop_burst = True
   if burst_timer_down is not None:
       js.clearTimeout(burst_timer_down)
   burst_timer_down = js.setTimeout(_end_down_burst_proxy, BURST_MS)

# Keyboard handlers
def handle_keydown(event):
   key = _norm_key(event)
   if key == "ArrowDown":
       start_soft_drop_hold()
   else:
       on_key({"key": key})

def handle_keyup(event):
   key = _norm_key(event)
   if key == "ArrowDown":
       stop_soft_drop_hold()

# ===== Wire & Start =====
game_loop_proxy = create_proxy(game_loop)
keydown_proxy  = create_proxy(handle_keydown)
keyup_proxy    = create_proxy(handle_keyup)

js.setInterval(game_loop_proxy, TICK_MS)
js.document.addEventListener("keydown", keydown_proxy)
js.document.addEventListener("keyup",   keyup_proxy)

# First frame
clear_and_paint_background()
draw_grid()
draw_ghost(current_shape, shape_pos)
draw_shape(current_shape, shape_pos, current_color)
draw_info()





















