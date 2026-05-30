"""
ui/app.py  –  W.O.R.K.E.R  v5

Исправления:
  1. Фон чата — через Label.place() ПОЗАДИ скролл-области,
     не внутри canvas (иначе двигается вместе с контентом)
  2. Скролл — стандартный Frame+Canvas с правильным yview,
     MouseWheel передаётся через рекурсивный bind на все дочерние виджеты
  3. Панель проекта — выпадающее меню сверху, открыть папку,
     AI читает все файлы и выводит сводку
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
import math
import random
import logging
import queue
import os
import datetime

logger = logging.getLogger("worker.ui")

APP_NAME = "W.O.R.K.E.R"
APP_SUB  = "голосовой ассистент"
TZ_MGN   = datetime.timezone(datetime.timedelta(hours=5))

# ── Палитра ───────────────────────────────────────────────────────────────────
BG         = "#020c16"
BG2        = "#030f1c"
SIDEBAR    = "#020c16"
TOPBAR     = "#040f1c"
CARD       = "#071828"
CARD2      = "#0a1f30"
LINE       = "#0e2d45"
LINE2      = "#153550"
ACCENT     = "#1db8ff"
ACCENT2    = "#0a8fcc"
ACCENT_DIM = "#0d4a6e"
TEXT       = "#cce8f8"
TEXT2      = "#8bb8d4"
MUTED      = "#4a7a9b"
OK         = "#2dd4a0"
WARN       = "#f0b84a"
ERR        = "#ff4f6a"

USER_BG     = "#0d2e45"
USER_FG     = "#d4eeff"
USER_BORDER = "#1e5878"
BOT_BG      = "#050f1a"
BOT_FG      = "#b0d8f0"
BOT_BORDER  = "#0c2840"
SYS_FG      = "#4a7a9b"

MIC_ON  = OK
MIC_OFF = ERR

# Linux/X11 accepts bg="" for transparency over the chat background image;
# Windows Tcl rejects an empty color name — fall back to BG2.
CHAT_SCROLL_BG = BG2 if os.name == "nt" else ""


def _chat_layer_bg(use_bg_image: bool) -> str:
    """Фон слоёв чата: прозрачный поверх картинки (Linux) или BG2 (Windows)."""
    if use_bg_image and os.name != "nt":
        return ""
    return BG2

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv",
    "venv", ".idea", ".vscode", "dist", "build",
    ".next", ".nuxt", "coverage", ".cursor",
}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md",
    ".txt", ".xml", ".sql", ".sh", ".bat", ".ps1", ".cs", ".cpp",
    ".c", ".h", ".java", ".go", ".rs", ".php", ".rb", ".swift",
    ".kt", ".dart", ".vue", ".svelte", ".env",
}
MAX_FILE_SIZE = 200 * 1024   # 200 KB на файл
MAX_TOTAL_CHARS = 80_000     # лимит суммарного контекста


def mgn_time():
    return datetime.datetime.now(tz=TZ_MGN).strftime("%H:%M:%S")

def mgn_datetime():
    return datetime.datetime.now(tz=TZ_MGN).strftime("%d.%m.%Y  %H:%M")

def _pct_color(pct):
    if pct >= 90: return ERR
    if pct >= 70: return WARN
    return OK

def _fonts(scale):
    s = max(0.75, min(1.25, scale))
    return {
        "title":   ("Segoe UI", max(13, int(16*s)), "bold"),
        "ui":      ("Segoe UI", max(9,  int(10*s))),
        "ui_sm":   ("Segoe UI", max(8,  int(9*s))),
        "ui_xs":   ("Segoe UI", max(7,  int(8*s))),
        "mono":    ("Consolas", max(8,  int(9*s))),
        "mono_sm": ("Consolas", max(7,  int(8*s))),
        "chat":    ("Segoe UI", max(9,  int(10*s))),
        "chat_sm": ("Segoe UI", max(8,  int(9*s))),
        "orb_sm":  ("Segoe UI", max(8,  int(9*s))),
    }

def _scale_from(w, h):
    return min(w / 1280, h / 800)

def _bind_mousewheel(widget, callback):
    """Рекурсивно навешивает MouseWheel на виджет и всех детей."""
    widget.bind("<MouseWheel>", callback)
    for child in widget.winfo_children():
        _bind_mousewheel(child, callback)


# ══════════════════════════════════════════════════════════════════════════════
class Ring:
    def __init__(self, canvas, cx, cy, r, color, speed, width=2, arc=130):
        self.c = canvas
        self.cx, self.cy, self.r = cx, cy, r
        self.col, self.spd, self.w, self.arc = color, speed, width, arc
        self.ang = random.uniform(0, 360)
        self._id = None

    def tick(self, state):
        m = 3.0 if state == "processing" else 1.0
        self.ang = (self.ang + self.spd * m) % 360
        if self._id: self.c.delete(self._id)
        cx, cy, r = self.cx, self.cy, self.r
        self._id = self.c.create_arc(
            cx-r, cy-r, cx+r, cy+r,
            start=self.ang, extent=self.arc,
            outline=self.col, style=tk.ARC, width=self.w, tags="viz")


# ══════════════════════════════════════════════════════════════════════════════
class SplashScreen:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        W, H = min(420, int(sw*0.32)), min(180, int(sh*0.20))
        self.win.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.win.configure(bg=BG)
        inner = tk.Frame(self.win, bg=CARD, highlightbackground=LINE2,
                         highlightthickness=1)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        tk.Label(inner, text=APP_NAME, bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack(pady=10)
        tk.Label(inner, text="Загрузка…", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack()
        bar_bg = tk.Frame(inner, bg=LINE, height=2)
        bar_bg.pack(fill="x", padx=20, pady=14)
        bar_bg.pack_propagate(False)
        self._bar = tk.Frame(bar_bg, bg=ACCENT, height=2)
        self._bar.place(relx=0, rely=0, relheight=1, relwidth=0.02)
        self._prog = 0.0
        self._tick()

    def _tick(self):
        if not self.win.winfo_exists(): return
        self._prog = min(1.0, self._prog + 0.014)
        self._bar.place(relwidth=max(0.02, self._prog))
        if self._prog < 1.0: self.win.after(18, self._tick)
        else: self.win.after(300, self.close)

    def close(self):
        try: self.win.destroy()
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
class HWMonitor:
    def __init__(self, parent, root, fonts):
        self._root = root
        self._running = True
        self._labels = {}
        box = tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                       highlightthickness=1)
        box.pack(fill="x")
        tk.Label(box, text="СИСТЕМА", bg=CARD, fg=MUTED,
                 font=fonts["ui_xs"]).pack(anchor="w", padx=8, pady=(5,2))
        body = tk.Frame(box, bg=CARD)
        body.pack(fill="x", padx=8, pady=(0,6))
        for key, title in (("cpu","ЦП"), ("gpu","ГП"), ("ram","ОЗУ")):
            row = tk.Frame(body, bg=CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=title, bg=CARD, fg=MUTED,
                     font=fonts["mono_sm"], width=4, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="—", bg=CARD, fg=ACCENT,
                           font=fonts["mono_sm"], anchor="w")
            lbl.pack(side="left", padx=2)
            self._labels[key] = lbl
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self):
        try:
            from commands.sysinfo import get_all_stats
        except ImportError:
            return
        while self._running:
            try:
                s = get_all_stats()
                self._root.after(0, lambda st=s: self._apply(st))
            except Exception: pass
            time.sleep(2)

    def _apply(self, s):
        try:
            cpu = float(s.get("cpu_pct") or 0)
            ct  = s.get("cpu_temp")
            t   = f"{cpu:.0f}%"
            if ct: t += f"  {ct:.0f}°"
            self._labels["cpu"].config(text=t, fg=_pct_color(cpu))
            gpu = s.get("gpu") or {}
            gl  = gpu.get("load"); gt = gpu.get("temp"); hs = gpu.get("hotspot")
            if gl is not None:
                t = f"{gl:.0f}%"
                if gt: t += f"  {gt:.0f}°"
                if hs and hs != gt: t += f" ({hs:.0f}°)"
                self._labels["gpu"].config(text=t, fg=_pct_color(gl))
            else:
                self._labels["gpu"].config(text="—", fg=MUTED)
            ram = s.get("ram") or {}
            rp  = float(ram.get("percent") or 0)
            self._labels["ram"].config(
                text=f"{rp:.0f}%  {ram.get('used_gb',0):.1f}/{ram.get('total_gb',0):.0f}Г",
                fg=_pct_color(rp))
        except Exception: pass

    def stop(self): self._running = False


# ══════════════════════════════════════════════════════════════════════════════
class ChatWidget:
    """
    Чат: каждое сообщение — отдельный create_window на canvas.
    Фон bg.jpg — статичный (Label + canvas backdrop), не перекрывается inner frame.
    """
    TAG_MSG = "msg"

    def __init__(self, parent, fonts, bg_path=""):
        self._fonts       = fonts
        self._bg_pil      = None
        self._bg_img      = None
        self._canvas_bg_img = None
        self._backdrop_id = None
        self._use_bg      = bool(bg_path and os.path.exists(bg_path))
        self._msg_width   = 400
        self._msg_items: list[int] = []   # canvas window ids
        self._msg_anchors: dict[int, str] = {}
        self._at_bottom   = True

        self._outer = tk.Frame(parent, bg=BG2)
        self._outer.pack(fill="both", expand=True)

        # Статичный фон — Label позади canvas
        self._bg_label = tk.Label(self._outer, bg=BG2, bd=0, highlightthickness=0)
        self._bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._vsb = tk.Scrollbar(self._outer, orient="vertical",
                                  bg=CARD2, troughcolor=BG2,
                                  bd=0, width=6, relief="flat")
        self._vsb.pack(side="right", fill="y")

        self._canvas = tk.Canvas(self._outer, bg=BG2,
                                  highlightthickness=0, bd=0)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.configure(command=self._canvas_yview)
        self._canvas.pack(side="left", fill="both", expand=True)

        self._scroll_cb = self._on_scroll
        self._canvas.bind("<MouseWheel>", self._scroll_cb)
        self._canvas.bind("<Button-4>",
            lambda e: self._canvas_yview("scroll", -3, "units"))
        self._canvas.bind("<Button-5>",
            lambda e: self._canvas_yview("scroll", 3, "units"))
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        self._outer.bind("<MouseWheel>", self._scroll_cb)

        if self._use_bg:
            self._load_bg(bg_path)
            self._outer.bind("<Configure>", lambda e: self._render_bg())

    # ── Scroll / фон ──────────────────────────────────────────────────────────

    def _canvas_yview(self, *args):
        self._canvas.yview(*args)
        self._sync_backdrop()
        self._update_at_bottom()

    def _on_scroll(self, event):
        delta = event.delta
        if delta == 0:
            return
        steps = max(1, abs(delta) // 40)
        direction = -1 if delta > 0 else 1
        self._canvas_yview("scroll", direction * steps, "units")

    def _bind_scroll_recursive(self, widget):
        widget.bind("<MouseWheel>", self._scroll_cb)
        for child in widget.winfo_children():
            self._bind_scroll_recursive(child)

    def _update_at_bottom(self):
        try:
            lo, hi = self._canvas.yview()
            self._at_bottom = hi >= 0.995
        except tk.TclError:
            pass

    def _load_bg(self, path):
        try:
            from PIL import Image, ImageEnhance, ImageFilter
            img = Image.open(path).convert("RGB")
            img = ImageEnhance.Brightness(img).enhance(0.42)
            img = img.filter(ImageFilter.GaussianBlur(radius=1))
            self._bg_pil = img
            self._outer.after(100, self._render_bg)
        except Exception as e:
            logger.error(f"chat bg load: {e}")

    def _render_bg(self):
        if self._bg_pil is None:
            return
        try:
            from PIL import Image, ImageTk
            w = self._outer.winfo_width()
            h = self._outer.winfo_height()
            if w < 10 or h < 10:
                self._outer.after(150, self._render_bg)
                return
            ow, oh = self._bg_pil.size

            def _crop_fit(cw, ch):
                img = self._bg_pil.copy()
                sc  = max(cw / ow, ch / oh)
                nw  = int(ow * sc) + 1
                nh  = int(oh * sc) + 1
                img = img.resize((nw, nh), Image.LANCZOS)
                l   = (nw - cw) // 2
                t   = (nh - ch) // 2
                return img.crop((l, t, l + cw, t + ch))

            self._bg_img = ImageTk.PhotoImage(_crop_fit(w, h))
            self._bg_label.config(image=self._bg_img)

            cw = max(self._canvas.winfo_width(), w)
            ch = max(self._canvas.winfo_height(), h)
            if cw > 10 and ch > 10:
                self._canvas_bg_img = ImageTk.PhotoImage(_crop_fit(cw, ch))
                if self._backdrop_id:
                    self._canvas.delete(self._backdrop_id)
                self._backdrop_id = self._canvas.create_image(
                    0, 0, anchor="nw", image=self._canvas_bg_img,
                    tags="backdrop")
                self._canvas.tag_lower("backdrop")
                for mid in self._msg_items:
                    self._canvas.tag_raise(mid)
                self._sync_backdrop()
        except Exception as e:
            logger.error(f"chat bg render: {e}")

    def _sync_backdrop(self):
        if self._backdrop_id:
            self._canvas.coords(self._backdrop_id, 0, self._canvas.canvasy(0))

    def refresh_bg(self):
        if self._bg_pil:
            self._outer.after(50, self._render_bg)

    def _on_canvas_cfg(self, e):
        self._msg_width = max(200, e.width - 24)
        if self._bg_pil:
            self._outer.after(80, self._render_bg)
        self._outer.after(50, self._reflow_messages)

    def _reflow_messages(self):
        cw = max(self._canvas.winfo_width(), self._msg_width + 24)
        y = 8
        for mid in self._msg_items:
            try:
                anc = self._msg_anchors.get(mid, "nw")
                if anc == "ne":
                    self._canvas.coords(mid, cw - 12, y)
                elif anc == "n":
                    self._canvas.coords(mid, cw // 2, y)
                else:
                    self._canvas.coords(mid, 12, y)
                bb = self._canvas.bbox(mid)
                h = (bb[3] - bb[1]) if bb else 40
            except tk.TclError:
                h = 40
            y += h + 6
        self._update_scrollregion()
        if self._at_bottom:
            self._scroll_bottom()

    def _update_scrollregion(self):
        if not self._msg_items:
            ch = max(self._canvas.winfo_height(), 100)
            cw = max(self._canvas.winfo_width(), self._msg_width + 24)
            self._canvas.configure(scrollregion=(0, 0, cw, ch))
            self._sync_backdrop()
            return
        bbox = self._canvas.bbox(self.TAG_MSG)
        if bbox:
            x1, y1, x2, y2 = bbox
            cw = max(self._canvas.winfo_width(), x2 + 12)
            self._canvas.configure(scrollregion=(0, 0, cw, y2 + 24))
        self._sync_backdrop()

    def _scroll_bottom(self):
        self._canvas.update_idletasks()
        self._canvas.yview_moveto(1.0)
        self._sync_backdrop()
        self._at_bottom = True

    def _mount_widget(self, widget, anchor="w"):
        widget.update_idletasks()
        y = 8
        if self._msg_items:
            last = self._msg_items[-1]
            try:
                bb = self._canvas.bbox(last)
                if bb:
                    y = bb[3] + 6
            except tk.TclError:
                pass
        cw = max(self._canvas.winfo_width(), self._msg_width + 24)
        if anchor == "e":
            x, anc = cw - 12, "ne"
        elif anchor == "center":
            x, anc = cw // 2, "n"
        else:
            x, anc = 12, "nw"
        win_id = self._canvas.create_window(
            x, y, window=widget, anchor=anc,
            tags=(self.TAG_MSG,))
        self._msg_items.append(win_id)
        self._msg_anchors[win_id] = anc
        self._bind_scroll_recursive(widget)
        widget.bind("<Configure>",
                    lambda e, wid=win_id: self._on_msg_resize(wid), add="+")
        self._outer.after(30, self._reflow_messages)
        if self._at_bottom:
            self._outer.after(80, self._scroll_bottom)

    def _on_msg_resize(self, win_id):
        self._outer.after(20, self._reflow_messages)

    # ── Public ────────────────────────────────────────────────────────────────

    def add_user(self, text, ts=""):
        self._bubble(text, "user", ts or mgn_time())

    def add_bot(self, text, ts=""):
        self._bubble(text, "bot", ts or mgn_time())

    def add_system(self, text):
        wrap = tk.Frame(self._canvas, bd=0, highlightthickness=0)
        lbl = tk.Label(wrap, text=f"— {text} —",
                       bg="#040e1acc", fg=SYS_FG,
                       font=self._fonts["ui_xs"])
        lbl.pack(padx=10, pady=2)
        self._mount_widget(wrap, anchor="center")

    def update_fonts(self, fonts):
        self._fonts = fonts

    # ── Пузырьки ─────────────────────────────────────────────────────────────

    def _bubble(self, text, who, ts):
        is_user  = (who == "user")
        bg_c     = USER_BG     if is_user else BOT_BG
        fg_c     = USER_FG     if is_user else BOT_FG
        brd_c    = USER_BORDER if is_user else BOT_BORDER
        name_fg  = ACCENT      if is_user else OK
        name_txt = "Вы"        if is_user else "W.O.R.K.E.R"

        bubble = tk.Frame(self._canvas, bg=bg_c,
                          highlightbackground=brd_c, highlightthickness=1)
        if is_user:
            bubble.pack_propagate(True)

        hdr = tk.Frame(bubble, bg=bg_c)
        hdr.pack(fill="x", padx=8, pady=(5, 0))
        tk.Label(hdr, text=name_txt, bg=bg_c, fg=name_fg,
                 font=self._fonts["chat_sm"]).pack(side="left")
        tk.Label(hdr, text=ts, bg=bg_c, fg=MUTED,
                 font=self._fonts["ui_xs"]).pack(side="right")

        self._render_content(bubble, text, bg_c, fg_c)
        tk.Frame(bubble, bg=bg_c, height=5).pack()
        self._mount_widget(bubble, anchor="e" if is_user else "w")

    def _render_content(self, parent, text, bg_c, fg_c):
        import re
        parts = re.split(r"(```[\s\S]*?```)", text)
        for part in parts:
            if not part:
                continue
            if part.startswith("```") and part.endswith("```"):
                code  = part[3:-3]
                lines = code.split("\n")
                if lines and lines[0].strip() and " " not in lines[0].strip():
                    lines = lines[1:]
                code = "\n".join(lines).strip()
                cf = tk.Frame(parent, bg="#010c15",
                              highlightbackground=ACCENT_DIM,
                              highlightthickness=1)
                cf.pack(fill="x", padx=8, pady=3)
                tk.Label(cf, text="// код", bg="#010c15", fg=ACCENT_DIM,
                         font=self._fonts["ui_xs"]).pack(
                    anchor="w", padx=6, pady=(3, 0))
                cl = tk.Text(cf, bg="#010c15", fg="#7dcfff",
                             font=self._fonts["mono"],
                             bd=0, highlightthickness=0,
                             wrap="none", relief="flat",
                             state="normal", cursor="arrow",
                             selectbackground=LINE2)
                cl.insert("1.0", code)
                cl.config(state="disabled",
                          height=min(25, code.count("\n") + 1))
                sb = tk.Scrollbar(cf, orient="horizontal",
                                  command=cl.xview,
                                  bg=CARD, troughcolor="#010c15",
                                  bd=0, width=4, relief="flat")
                cl.config(xscrollcommand=sb.set)
                cl.pack(fill="x", padx=6)
                sb.pack(fill="x", padx=6, pady=(0, 4))
            else:
                txt = part.strip()
                if txt:
                    lbl = tk.Label(parent, text=txt,
                                   bg=bg_c, fg=fg_c,
                                   font=self._fonts["chat"],
                                   justify="left", anchor="w",
                                   wraplength=self._msg_width - 40)
                    lbl.pack(fill="x", padx=8, pady=(3, 1), anchor="w")
                    lbl.bind("<Configure>",
                             lambda e, l=lbl:
                             l.config(wraplength=max(80, self._msg_width - 40)))


# ══════════════════════════════════════════════════════════════════════════════
class ProjectWorkspace(tk.Frame):
    """Левая панель: список файлов + редактор (блокнот)."""

    WIDTH = 280

    def __init__(self, parent, fonts, on_back_to_chat=None, on_file_saved=None):
        super().__init__(parent, bg=CARD, width=self.WIDTH,
                         highlightbackground=LINE2, highlightthickness=1)
        self.pack_propagate(False)
        self._fonts = fonts
        self._on_back = on_back_to_chat
        self._on_saved = on_file_saved
        self._project_dir = ""
        self._current_path = ""
        self._dirty = False

        hdr = tk.Frame(self, bg=CARD2)
        hdr.pack(fill="x")
        self._lbl_title = tk.Label(hdr, text="ПРОЕКТ", bg=CARD2, fg=MUTED,
                                   font=fonts["ui_xs"])
        self._lbl_title.pack(side="left", padx=8, pady=6)
        self._btn_chat = tk.Button(
            hdr, text="💬 К чату", command=self._go_chat,
            bg=ACCENT_DIM, fg=ACCENT, font=fonts["ui_xs"],
            bd=0, relief="flat", cursor="hand2", padx=6, pady=2,
            activebackground=ACCENT2, activeforeground=BG)
        self._btn_chat.pack(side="right", padx=6, pady=4)

        self._lbl_path = tk.Label(self, text="", bg=CARD, fg=TEXT2,
                                  font=fonts["ui_xs"], anchor="w",
                                  wraplength=self.WIDTH - 16)
        self._lbl_path.pack(fill="x", padx=8, pady=(4, 2))

        list_wrap = tk.Frame(self, bg=CARD)
        list_wrap.pack(fill="x", padx=6, pady=2)
        lsb = tk.Scrollbar(list_wrap, orient="vertical",
                           bg=CARD2, troughcolor=BG2, bd=0, width=5)
        self._listbox = tk.Listbox(
            list_wrap, bg=CARD2, fg=TEXT2, font=fonts["mono_sm"],
            bd=0, highlightthickness=1, highlightbackground=LINE,
            selectbackground=ACCENT_DIM, selectforeground=ACCENT,
            activestyle="none", height=8, yscrollcommand=lsb.set,
        )
        lsb.config(command=self._listbox.yview)
        lsb.pack(side="right", fill="y")
        self._listbox.pack(side="left", fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_select_file)

        tk.Frame(self, bg=LINE, height=1).pack(fill="x", padx=6, pady=4)

        ed_hdr = tk.Frame(self, bg=CARD)
        ed_hdr.pack(fill="x", padx=8)
        self._lbl_file = tk.Label(ed_hdr, text="Выберите файл", bg=CARD,
                                  fg=MUTED, font=fonts["ui_xs"], anchor="w")
        self._lbl_file.pack(side="left")
        self._btn_save = tk.Button(
            ed_hdr, text="💾", command=self._save_file,
            bg=CARD2, fg=OK, font=fonts["ui_xs"],
            bd=0, relief="flat", cursor="hand2", padx=4,
            state="disabled")
        self._btn_save.pack(side="right")

        ed_wrap = tk.Frame(self, bg=CARD)
        ed_wrap.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        ev = tk.Scrollbar(ed_wrap, orient="vertical",
                          bg=CARD2, troughcolor=BG2, bd=0, width=6)
        self._editor = tk.Text(
            ed_wrap, bg="#010c15", fg="#cce8f8", font=fonts["mono"],
            bd=0, highlightthickness=1, highlightbackground=LINE,
            highlightcolor=ACCENT, insertbackground=ACCENT,
            wrap="none", undo=True, state="disabled",
            yscrollcommand=ev.set,
        )
        ev.config(command=self._editor.yview)
        ev.pack(side="right", fill="y")
        self._editor.pack(side="left", fill="both", expand=True)
        self._editor.bind("<<Modified>>", self._on_edit)

    def open_project(self, project_dir: str, all_files: list[str],
                     project_files: dict[str, str]):
        self._project_dir = project_dir
        name = os.path.basename(project_dir)
        self._lbl_path.config(text=project_dir)
        self._lbl_title.config(text=f"ПРОЕКТ · {name}")
        self._listbox.delete(0, "end")
        for fp in all_files:
            mark = "● " if fp in project_files else "○ "
            self._listbox.insert("end", mark + fp)
        self._clear_editor()
        self.pack(side="left", fill="y")

    def close_project(self):
        self._project_dir = ""
        self._listbox.delete(0, "end")
        self._clear_editor()
        self.pack_forget()

    def refresh_files(self, all_files: list[str], project_files: dict[str, str]):
        sel = self._current_path
        self._listbox.delete(0, "end")
        for fp in all_files:
            mark = "● " if fp in project_files else "○ "
            self._listbox.insert("end", mark + fp)
        if sel:
            self._select_in_list(sel)
            self.load_file(sel, project_files.get(sel, ""))

    def _select_in_list(self, path: str):
        for i in range(self._listbox.size()):
            txt = self._listbox.get(i)
            if txt.endswith(path) or txt.endswith(" " + path):
                self._listbox.selection_clear(0, "end")
                self._listbox.selection_set(i)
                self._listbox.see(i)
                break

    def _on_select_file(self, event=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        txt = self._listbox.get(sel[0])
        path = txt[2:] if txt.startswith(("● ", "○ ")) else txt
        self._open_file(path)

    def _open_file(self, rel_path: str):
        if not self._project_dir:
            return
        fpath = os.path.join(self._project_dir, rel_path.replace("/", os.sep))
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            content = f"# Ошибка чтения: {e}"
        self.load_file(rel_path, content)

    def load_file(self, rel_path: str, content: str):
        self._current_path = rel_path
        self._lbl_file.config(text=rel_path, fg=ACCENT)
        self._editor.config(state="normal")
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", content)
        self._editor.edit_modified(False)
        self._editor.config(state="normal")
        self._dirty = False
        self._btn_save.config(state="normal")

    def _clear_editor(self):
        self._current_path = ""
        self._lbl_file.config(text="Выберите файл", fg=MUTED)
        self._editor.config(state="normal")
        self._editor.delete("1.0", "end")
        self._editor.config(state="disabled")
        self._btn_save.config(state="disabled")
        self._dirty = False

    def _on_edit(self, event=None):
        if self._editor.edit_modified():
            self._dirty = True
            self._editor.edit_modified(False)

    def _save_file(self):
        if not self._project_dir or not self._current_path:
            return
        content = self._editor.get("1.0", "end-1c")
        from core.project_editor import write_file
        write_file(self._project_dir, self._current_path, content)
        self._dirty = False
        if self._on_saved:
            self._on_saved(self._current_path, content)

    def reload_current(self, content: str):
        if self._current_path:
            self.load_file(self._current_path, content)

    def _go_chat(self):
        if self._on_back:
            self._on_back()


# ══════════════════════════════════════════════════════════════════════════════
class ProjectPanel:
    """Выпадающее меню проекта (открыть / перечитать / спросить / закрыть)."""

    def __init__(self, parent_btn, root, chat_ref, fonts, response_cb,
                 on_update=None, on_project_open=None, on_project_close=None,
                 on_files_loaded=None):
        self._root           = root
        self._chat           = chat_ref
        self._fonts          = fonts
        self._response_cb    = response_cb
        self._on_update      = on_update
        self._on_open        = on_project_open
        self._on_close       = on_project_close
        self._on_files_loaded = on_files_loaded
        self._btn            = parent_btn
        self._panel          = None
        self._visible        = False
        self._project_dir    = None
        self._project_files: dict[str, str] = {}
        self._all_files: list[str] = []

    def toggle(self):
        if self._visible:
            self._hide()
        else:
            self._show()

    def _show(self):
        if self._panel and self._panel.winfo_exists():
            self._panel.destroy()
        self._btn.update_idletasks()
        bx = self._btn.winfo_rootx()
        by = self._btn.winfo_rooty() + self._btn.winfo_height()
        panel = tk.Toplevel(self._root)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.configure(bg=CARD)
        h = 240 if self._project_dir else 120
        panel.geometry(f"260x{h}+{bx}+{by}")
        panel.bind("<FocusOut>", self._on_panel_focus_out)
        inner = tk.Frame(panel, bg=CARD, highlightbackground=LINE2,
                         highlightthickness=1)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        f = self._fonts
        tk.Label(inner, text="ПРОЕКТ", bg=CARD, fg=MUTED,
                 font=f["ui_xs"]).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Button(
            inner, text="📁  Открыть папку", command=self._open_folder,
            bg=CARD2, fg=ACCENT, font=f["ui_xs"], bd=0, relief="flat",
            cursor="hand2", padx=10, pady=6, anchor="w",
            activebackground=LINE, activeforeground=TEXT,
        ).pack(fill="x", padx=8, pady=2)
        if self._project_dir:
            n = len(self._project_files)
            tk.Label(inner,
                     text=f"AI: {n} файлов · всего: {len(self._all_files)}",
                     bg=CARD, fg=OK if n else MUTED, font=f["ui_xs"],
                     wraplength=230).pack(anchor="w", padx=10, pady=2)
            tk.Label(inner, text=self._project_dir, bg=CARD, fg=TEXT2,
                     font=f["ui_xs"], wraplength=230, anchor="w",
                     ).pack(fill="x", padx=10)
            for txt, cmd, bg, fg in [
                ("🔄  Перечитать файлы", self._on_reread, CARD2, TEXT2),
                ("💬  Спросить про проект", self._ask_about_project,
                 ACCENT_DIM, ACCENT),
                ("✖  Закрыть проект", self._close_project, CARD2, ERR),
            ]:
                tk.Button(
                    inner, text=txt, command=cmd,
                    bg=bg, fg=fg, font=f["ui_xs"], bd=0, relief="flat",
                    cursor="hand2", padx=10, pady=4, anchor="w",
                ).pack(fill="x", padx=8, pady=2)
        self._panel = panel
        self._visible = True
        panel.focus_set()

    def _on_panel_focus_out(self, event=None):
        self._root.after(200, self._try_hide_panel)

    def _try_hide_panel(self):
        if not self._panel or not self._panel.winfo_exists():
            return
        try:
            focus = self._root.focus_get()
            if focus:
                w, p = str(focus), str(self._panel)
                if w == p or w.startswith(p + "."):
                    return
        except tk.TclError:
            pass
        self._hide()

    def _hide(self):
        self._visible = False
        if self._panel:
            try:
                self._panel.destroy()
            except Exception:
                pass
            self._panel = None

    def _notify_update(self):
        if self._on_update:
            self._on_update()

    def _open_folder(self):
        folder = filedialog.askdirectory(
            title="Выберите папку проекта", parent=self._root)
        if not folder:
            return
        self._hide()
        self._load_project(os.path.normpath(folder), ask_ai=True)

    def _load_project(self, folder: str, ask_ai: bool = True):
        from core.project_editor import read_project_files, build_context
        from core.project_context import set_project_context

        self._project_dir = folder
        files, skipped, all_files = read_project_files(folder)
        self._project_files = files
        self._all_files = all_files
        n = len(files)
        logger.info(f"Проект: {folder}, AI={n}, всего={len(all_files)}")

        ctx = build_context(files)
        set_project_context(ctx, folder)

        try:
            from commands.ai_query import _get_engine
            _get_engine().clear_history()
        except Exception as e:
            logger.error(f"clear history: {e}")

        if self._on_open:
            self._on_open(folder, all_files, files)
        if self._on_files_loaded:
            self._on_files_loaded(all_files, files)

        msg = f"Прочитано {n} файлов для AI · всего: {len(all_files)}"
        if skipped:
            msg += f" ({skipped} пропущено)"
        if self._chat:
            self._chat.add_system(msg)
        self._notify_update()

        if ask_ai and files:
            self._greet_project()
        elif ask_ai and not files:
            if self._chat:
                self._chat.add_system("Не найдено текстовых файлов для AI.")

    def _on_reread(self):
        if not self._project_dir:
            if self._chat:
                self._chat.add_system("Сначала откройте папку")
            return
        self._hide()
        if self._chat:
            self._chat.add_system("Перечитываю файлы…")
        self._load_project(self._project_dir, ask_ai=False)

    def _greet_project(self):
        name = os.path.basename(self._project_dir)
        n = len(self._project_files)
        prompt = (
            f"Я вижу ваш проект «{name}». В нём {n} файлов с кодом. "
            "Проанализируй все файлы проекта, кратко опиши что это за проект, "
            "какие ключевые файлы и модули есть, и спроси чем можешь помочь. "
            "Отвечай только на русском."
        )
        if self._chat:
            self._chat.add_system(f"Анализирую проект «{name}»…")
        threading.Thread(
            target=self._ask_ai, args=(prompt,), daemon=True).start()

    def _ask_about_project(self):
        self._hide()
        if not self._project_dir:
            if self._chat:
                self._chat.add_system("Сначала откройте папку проекта")
            return
        if not self._project_files:
            self._load_project(self._project_dir, ask_ai=True)
            return
        self._greet_project()

    def _ask_ai(self, prompt: str):
        try:
            from commands.ai_query import _get_engine
            reply = _get_engine().ask(prompt)
            if self._response_cb and self._root:
                self._root.after(0, lambda r=reply: self._response_cb(r))
        except Exception as e:
            logger.error(f"project AI ask: {e}")
            if self._chat and self._root:
                self._root.after(0, lambda: self._chat.add_system(
                    f"Ошибка AI: {e}"))

    def _close_project(self):
        self._hide()
        self._project_dir = None
        self._project_files = {}
        self._all_files = []
        from core.project_context import clear_project_context
        clear_project_context()
        try:
            from commands.ai_query import _get_engine
            _get_engine().clear_history()
        except Exception:
            pass
        if self._on_close:
            self._on_close()
        if self._chat:
            self._chat.add_system("Проект закрыт")
        self._notify_update()

    def get_project_files(self) -> dict:
        return self._project_files

    def get_project_dir(self) -> str:
        return self._project_dir or ""

    def update_file_content(self, rel_path: str, content: str):
        self._project_files[rel_path] = content
        from core.project_editor import build_context
        from core.project_context import set_project_context
        set_project_context(
            build_context(self._project_files), self._project_dir or "")


# ══════════════════════════════════════════════════════════════════════════════
class JarvisApp:
    def __init__(self):
        self._ui_queue     = queue.Queue()
        self._root         = None
        self._state        = "listening"
        self._rings        = []
        self._phase        = 0.0
        self._orb_canvas   = None
        self._orb_bg_img   = None
        self._iris = self._pupil = self._lbl_orb = None
        self._wave_bars    = []
        self._voice_engine = None
        self._dispatcher   = None
        self._fonts        = _fonts(1.0)
        self._btn_mute     = None
        self._btn_project  = None
        self._pill         = None
        self._stat_mic     = None
        self._stat_asr     = None
        self._stat_state   = None
        self._clock_lbl    = None
        self._clock_top    = None
        self._inp          = None
        self._chat         = None
        self._hw           = None
        self._tray         = None
        self._resize_job   = None
        self._bg_path      = ""
        self._project_panel = None
        self._workspace     = None
        self._chat_column   = None
        self._entry         = None
        self._mic_muted    = False

        self._queue_running = False
        self._anim_running  = False
        self._clock_running = False

    def set_tray(self, t): self._tray = t

    def show_window(self):
        if self._root:
            self._root.deiconify()
            self._root.lift()
            self._root.focus_force()

    def hide_window(self):
        if self._root: self._root.withdraw()

    def run(self):
        root = tk.Tk()
        self._root = root
        root.withdraw()
        root.update()
        splash = SplashScreen(root)
        root.update()
        self._build_ui()
        root.after(2200, lambda: self._after_splash(splash))
        root.mainloop()

    def _after_splash(self, splash):
        try: splash.close()
        except Exception: pass
        self._root.deiconify()
        self._root.after(80, self._start_core)
        if not self._queue_running:
            self._queue_running = True
            self._root.after(50, self._process_queue)
        if not self._anim_running:
            self._anim_running = True
            self._root.after(16, self._anim_tick)
        if not self._clock_running:
            self._clock_running = True
            self._root.after(1000, self._clock_tick)

    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        root   = self._root
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        W = max(960, min(int(sw * 0.92), sw))
        H = max(580, min(int(sh * 0.92), sh))
        root.title("W.O.R.K.E.R — голосовой ассистент")
        root.configure(bg=BG)
        root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        root.minsize(820, 540)
        try: root.attributes("-toolwindow", True)
        except Exception: pass
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        root.update_idletasks()
        self._fonts = _fonts(_scale_from(
            root.winfo_width() or W,
            root.winfo_height() or H))
        f = self._fonts

        self._bg_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "assets", "bg.jpg"))

        # ── TOP BAR ───────────────────────────────────────────────────────────
        top = tk.Frame(root, bg=TOPBAR)
        top.pack(side="top", fill="x")

        tk.Label(top, text=APP_NAME, bg=TOPBAR, fg=ACCENT,
                 font=f["title"]).pack(side="left", padx=10, pady=5)
        tk.Label(top, text=APP_SUB, bg=TOPBAR, fg=MUTED,
                 font=f["ui_xs"]).pack(side="left", padx=2)

        self._pill = tk.Label(top, text="● Слушаю", bg=CARD, fg=OK,
                              font=f["ui_xs"])
        self._pill.pack(side="left", padx=8, pady=6)

        self._btn_mute = tk.Button(
            top, text="🎤 Микрофон вкл", command=self._on_mute_toggle,
            bg=CARD, fg=MIC_ON, font=f["ui_xs"],
            bd=0, relief="flat", cursor="hand2", padx=6, pady=1,
            activebackground=LINE, activeforeground=TEXT)
        self._btn_mute.pack(side="left", padx=4, pady=6)

        # Кнопка проекта
        self._btn_project = tk.Button(
            top, text="📁 Проект", command=self._toggle_project_panel,
            bg=CARD, fg=TEXT2, font=f["ui_xs"],
            bd=0, relief="flat", cursor="hand2", padx=6, pady=1,
            activebackground=LINE, activeforeground=ACCENT)
        self._btn_project.pack(side="left", padx=4, pady=6)

        tk.Button(top, text="В трей", command=self.hide_window,
                  bg=CARD, fg=MUTED, font=f["ui_xs"],
                  bd=0, relief="flat", cursor="hand2", padx=6, pady=1,
                  activebackground=LINE, activeforeground=ACCENT,
                  ).pack(side="right", padx=8, pady=6)

        self._clock_top = tk.Label(top, text=mgn_time(), bg=TOPBAR,
                                   fg=MUTED, font=f["mono_sm"])
        self._clock_top.pack(side="right", padx=6)

        # ── MAIN ──────────────────────────────────────────────────────────────
        main = tk.Frame(root, bg=BG)
        main.pack(fill="both", expand=True)

        # ── SIDEBAR ───────────────────────────────────────────────────────────
        sidebar = tk.Frame(main, bg=SIDEBAR, width=222)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self._orb_canvas = tk.Canvas(sidebar, bg=BG, highlightthickness=0,
                                     width=222, height=175)
        self._orb_canvas.pack(fill="x")
        self._load_orb_bg()
        self._draw_orb()

        tk.Frame(sidebar, bg=LINE2, height=1).pack(fill="x")

        st_box = tk.Frame(sidebar, bg=CARD, highlightbackground=LINE,
                          highlightthickness=1)
        st_box.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(st_box, text="СТАТУС", bg=CARD, fg=MUTED,
                 font=f["ui_xs"]).pack(anchor="w", padx=8, pady=(5, 2))
        bd = tk.Frame(st_box, bg=CARD)
        bd.pack(fill="x", padx=8, pady=(0, 6))

        def st_row(txt, val, col, attr):
            r = tk.Frame(bd, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=txt, bg=CARD, fg=MUTED,
                     font=f["ui_xs"], width=12, anchor="w").pack(side="left")
            lb = tk.Label(r, text=val, bg=CARD, fg=col, font=f["ui_xs"])
            lb.pack(side="left")
            setattr(self, attr, lb)

        st_row("Микрофон:",   "активен", OK,    "_stat_mic")
        st_row("Распознав.:", "онлайн",  OK,    "_stat_asr")
        self._stat_state = tk.Label(bd, text="Слушаю", bg=CARD,
                                    fg=ACCENT, font=f["ui_sm"])
        self._stat_state.pack(anchor="w", pady=(4, 2))
        tk.Frame(st_box, bg=LINE, height=1).pack(fill="x", padx=6)
        tz = tk.Frame(st_box, bg=CARD)
        tz.pack(fill="x", padx=8, pady=(4, 6))
        tk.Label(tz, text="UTC+5  Магнитогорск", bg=CARD, fg=MUTED,
                 font=f["ui_xs"]).pack(anchor="w")
        self._clock_lbl = tk.Label(tz, text=mgn_datetime(), bg=CARD,
                                   fg=TEXT2, font=f["mono_sm"])
        self._clock_lbl.pack(anchor="w")

        hw_wrap = tk.Frame(sidebar, bg=SIDEBAR)
        hw_wrap.pack(fill="x", padx=8, pady=4)
        self._hw = HWMonitor(hw_wrap, root, f)

        hb = tk.Frame(sidebar, bg=CARD, highlightbackground=LINE,
                      highlightthickness=1)
        hb.pack(fill="x", padx=8, pady=4)
        tk.Label(hb, text="КОМАНДЫ", bg=CARD, fg=MUTED,
                 font=f["ui_xs"]).pack(anchor="w", padx=8, pady=(5, 2))
        for h in ["«микрофон» — вкл/выкл",
                  "«громче / тише»",
                  "«включи музыку»",
                  "«открой гугл»",
                  "«добавь команду …»",
                  "«покажи мои команды»",
                  "«что ты знаешь обо мне»"]:
            tk.Label(hb, text=h, bg=CARD, fg=MUTED, font=f["ui_xs"],
                     anchor="w").pack(anchor="w", padx=8, pady=1)
        tk.Frame(hb, height=4, bg=CARD).pack()

        tk.Frame(main, bg=LINE2, width=1).pack(side="left", fill="y")

        # ── CHAT ──────────────────────────────────────────────────────────────
        right = tk.Frame(main, bg=BG2)
        right.pack(side="left", fill="both", expand=True)

        chat_hdr = tk.Frame(right, bg=CARD, height=30)
        chat_hdr.pack(fill="x")
        chat_hdr.pack_propagate(False)
        tk.Label(chat_hdr, text="ЧАТ", bg=CARD, fg=MUTED,
                 font=f["ui_xs"]).pack(side="left", padx=10)
        tk.Label(chat_hdr, text="W.O.R.K.E.R · локальная нейросеть",
                 bg=CARD, fg=TEXT2, font=f["ui_xs"]).pack(side="left", padx=4)

        # Индикатор проекта в заголовке чата
        self._lbl_project = tk.Label(chat_hdr, text="", bg=CARD,
                                      fg=OK, font=f["ui_xs"])
        self._lbl_project.pack(side="right", padx=10)

        chat_body = tk.Frame(right, bg=BG2)
        chat_body.pack(fill="both", expand=True)

        self._workspace = ProjectWorkspace(
            chat_body, f,
            on_back_to_chat=self._focus_chat,
            on_file_saved=self._on_file_saved,
        )

        self._chat_column = tk.Frame(chat_body, bg=BG2)
        self._chat_column.pack(side="left", fill="both", expand=True)

        self._chat = ChatWidget(
            self._chat_column, f,
            bg_path=self._bg_path if os.path.exists(self._bg_path) else "")

        tk.Frame(right, bg=LINE, height=1).pack(fill="x")

        inp_row = tk.Frame(right, bg=TOPBAR)
        inp_row.pack(fill="x", side="bottom")
        tk.Label(inp_row, text=">", bg=TOPBAR, fg=ACCENT2,
                 font=f["mono"]).pack(side="left", padx=(10, 4), pady=8)
        self._inp = tk.StringVar()
        self._entry = tk.Entry(inp_row, textvariable=self._inp,
                       bg=CARD2, fg=TEXT, insertbackground=ACCENT,
                       font=f["chat"], relief="flat", bd=0,
                       highlightthickness=1,
                       highlightbackground=LINE,
                       highlightcolor=ACCENT)
        self._entry.pack(side="left", fill="x", expand=True,
                 padx=(0, 6), ipady=6, pady=7)
        self._entry.bind("<Return>", self._on_enter)
        self._entry.focus_set()
        tk.Button(inp_row, text="Отправить", command=self._on_btn,
                  bg=ACCENT_DIM, fg=ACCENT, font=f["ui_xs"],
                  bd=0, relief="flat", cursor="hand2",
                  padx=10, pady=4,
                  activebackground=ACCENT2, activeforeground=BG,
                  ).pack(side="right", padx=8, pady=7)

        root.bind("<Configure>", self._on_resize)

        # Инициализируем панель проекта (после того как chat создан)
        self._project_panel = ProjectPanel(
            parent_btn=self._btn_project,
            root=root,
            chat_ref=self._chat,
            fonts=f,
            response_cb=self._cb_response,
            on_update=lambda: self._ui_queue.put(("project",)),
            on_project_open=self._on_project_open,
            on_project_close=self._on_project_close,
            on_files_loaded=self._on_files_loaded,
        )

    def _on_project_open(self, folder, all_files, project_files):
        if self._workspace:
            self._workspace.open_project(folder, all_files, project_files)
        if self._chat:
            name = os.path.basename(folder)
            self._chat.add_system(f"📁 Проект «{name}» открыт — файлы слева")
        self._focus_chat()

    def _on_project_close(self):
        if self._workspace:
            self._workspace.close_project()

    def _on_files_loaded(self, all_files, project_files):
        if self._workspace and self._project_panel.get_project_dir():
            self._workspace.refresh_files(all_files, project_files)

    def _on_file_saved(self, rel_path, content):
        if self._project_panel:
            self._project_panel.update_file_content(rel_path, content)
        if self._chat:
            self._chat.add_system(f"💾 Сохранено: {rel_path}")

    def _focus_chat(self):
        if self._entry:
            self._entry.focus_set()

    # ── Проект ───────────────────────────────────────────────────────────────

    def _toggle_project_panel(self):
        if self._project_panel:
            self._project_panel.toggle()

    def _update_project_label(self):
        if not self._lbl_project: return
        if self._project_panel and self._project_panel.get_project_dir():
            name = os.path.basename(self._project_panel.get_project_dir())
            n    = len(self._project_panel.get_project_files())
            self._lbl_project.config(
                text=f"📁 {name}  ({n} файлов)", fg=OK)
        else:
            self._lbl_project.config(text="", fg=OK)

    # ── Орб ──────────────────────────────────────────────────────────────────

    def _load_orb_bg(self):
        p = self._bg_path if self._bg_path else os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "assets", "bg.jpg"))
        if not os.path.exists(p) or not self._orb_canvas: return
        try:
            from PIL import Image, ImageTk, ImageEnhance
            img = Image.open(p).convert("RGB")
            W, H = 222, 175
            ow, oh = img.size
            sc = max(W / ow, H / oh)
            nw, nh = int(ow * sc), int(oh * sc)
            img = img.resize((nw, nh), Image.LANCZOS)
            l, t = (nw - W) // 2, 0
            img = img.crop((l, t, l + W, t + H))
            img = ImageEnhance.Brightness(img).enhance(0.28)
            self._orb_bg_img = ImageTk.PhotoImage(img)
            self._orb_canvas.create_image(0, 0, anchor="nw",
                                          image=self._orb_bg_img, tags="bg")
        except Exception as e:
            logger.error(f"orb bg: {e}")

    def _draw_orb(self):
        c = self._orb_canvas
        if not c: return
        c.delete("viz")
        W, H = 222, 175
        cx = W // 2; cy = H // 2 - 8; R = 40
        self._rings = [
            Ring(c, cx, cy, R + 26, ACCENT,  0.35, 2, 160),
            Ring(c, cx, cy, R + 42, LINE2,  -0.5,  1,  80),
        ]
        self._iris    = c.create_oval(cx-R, cy-R, cx+R, cy+R,
                                      outline=ACCENT, width=2, fill=BG,
                                      tags="viz")
        self._pupil   = c.create_oval(cx-5, cy-5, cx+5, cy+5,
                                      fill=ACCENT, outline="", tags="viz")
        self._lbl_orb = c.create_text(cx, cy+R+18, text="Слушаю",
                                       fill=TEXT2, font=self._fonts["orb_sm"],
                                       tags="viz")
        n = max(8, min(16, W // 14))
        bw, gap = 3, 2
        bx0 = cx - (n * (bw + gap)) // 2
        by  = cy + R + 32
        self._wave_bars = []
        for i in range(n):
            x = bx0 + i * (bw + gap)
            self._wave_bars.append(
                (c.create_rectangle(x, by, x+bw, by,
                                    fill=LINE, outline="", tags="viz"),
                 x, by))

    # ── Мут ──────────────────────────────────────────────────────────────────

    def _on_mute_toggle(self):
        if self._voice_engine:
            self._voice_engine.toggle_mute()
        else:
            self._mic_muted = not self._mic_muted
            self._update_mute_ui(self._mic_muted)

    def _cb_mute_change(self, is_muted):
        self._mic_muted = is_muted
        self._ui_queue.put(("mute", is_muted))

    def _update_mute_ui(self, is_muted):
        if self._btn_mute:
            if is_muted:
                self._btn_mute.config(text="🔇 Микрофон выкл",
                                      fg=MIC_OFF, bg="#150810")
            else:
                self._btn_mute.config(text="🎤 Микрофон вкл",
                                      fg=MIC_ON, bg=CARD)
        if self._stat_mic:
            self._stat_mic.config(
                text="заглушён" if is_muted else "активен",
                fg=MIC_OFF if is_muted else OK)
        if self._pill:
            if is_muted: self._pill.config(text="🔇 Мут", fg=MIC_OFF)
            else:        self._pill.config(text="● Слушаю", fg=OK)
        if self._chat:
            self._chat.add_system(
                "🔇 Микрофон заглушён" if is_muted else "🎤 Микрофон включён")

    # ── Resize ────────────────────────────────────────────────────────────────

    def _on_resize(self, event):
        if event.widget != self._root: return
        rw, rh = event.width, event.height
        if rw < 80 or rh < 80: return
        if self._resize_job: self._root.after_cancel(self._resize_job)
        self._resize_job = self._root.after(
            180, lambda: self._do_resize(rw, rh))

    def _do_resize(self, rw, rh):
        self._resize_job = None
        self._fonts = _fonts(_scale_from(rw, rh))
        if self._chat:
            self._chat.update_fonts(self._fonts)
            self._chat.refresh_bg()

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _clock_tick(self):
        if not self._root or not self._clock_running: return
        try:
            if self._clock_lbl: self._clock_lbl.config(text=mgn_datetime())
            if self._clock_top: self._clock_top.config(text=mgn_time())
        except Exception: pass
        self._root.after(1000, self._clock_tick)

    # ── Animation ─────────────────────────────────────────────────────────────

    def _anim_tick(self):
        if not self._root or not self._anim_running: return
        try:
            for r in self._rings: r.tick(self._state)
            self._tick_orb()
            self._tick_wave()
        except tk.TclError:
            return
        self._root.after(16, self._anim_tick)

    def _tick_orb(self):
        self._phase = (self._phase + 0.07) % 6.28
        p = math.sin(self._phase)
        if self._state == "processing":
            oc, lbl = WARN, "Думаю…"
        else:
            oc, lbl = ACCENT, "Слушаю"
        R  = 40; s = 1.0 + 0.07 * p
        ri = int(R * s); rp = max(3, int(5 * s))
        W, H = 222, 175
        cx = W // 2; cy = H // 2 - 8
        c = self._orb_canvas
        if not c: return
        if self._iris:
            c.coords(self._iris, cx-ri, cy-ri, cx+ri, cy+ri)
            c.itemconfig(self._iris, outline=oc)
        if self._pupil:
            c.coords(self._pupil, cx-rp, cy-rp, cx+rp, cy+rp)
        if self._lbl_orb:
            c.itemconfig(self._lbl_orb, text=lbl, fill=oc)
        if self._pill:
            is_muted = self._voice_engine.is_muted if self._voice_engine else False
            if is_muted:
                self._pill.config(text="🔇 Мут", fg=MIC_OFF)
            elif self._state == "processing":
                self._pill.config(text="● Думаю…", fg=WARN)
            else:
                self._pill.config(text="● Слушаю", fg=OK)
        if self._stat_state:
            self._stat_state.config(text=lbl, fg=oc)

    def _tick_wave(self):
        t      = time.time()
        active = self._state == "processing"
        W, H   = 222, 175
        cx = W // 2; cy = H // 2 - 8; R = 40; by = cy + R + 32
        for i, (bid, bx, _) in enumerate(self._wave_bars):
            if active:
                h = abs(math.sin(t * 5 + i * 0.4)) * 18 + 5; col = WARN
            else:
                h = 2 + abs(math.sin(t * 0.4 + i * 0.25)) * 2; col = LINE2
            self._orb_canvas.coords(bid, bx, by-h, bx+3, by)
            self._orb_canvas.itemconfig(bid, fill=col)

    # ── Core ─────────────────────────────────────────────────────────────────

    def _start_core(self):
        if self._voice_engine is not None: return
        if self._chat: self._chat.add_system("Запуск W.O.R.K.E.R…")

        def _init():
            try:
                from core.voice_engine import VoiceEngine
                from core.command_dispatcher import CommandDispatcher
                self._dispatcher = CommandDispatcher(
                    on_response=self._cb_response)
                # Обновляем диспетчер в ProjectPanel
                if self._project_panel:
                    self._project_panel._dispatcher = self._dispatcher
                self._voice_engine = VoiceEngine(
                    on_state_change=self._cb_state,
                    on_transcript=self._cb_transcript,
                    on_command=self._cb_command,
                    on_mute_change=self._cb_mute_change,
                )
                if self._mic_muted:
                    self._voice_engine._muted = True
                self._voice_engine.start()
                mode = "голос" if self._voice_engine._sd_ok else "текст"
                self._ui_queue.put(("system", f"Готово · режим: {mode}"))
            except Exception as e:
                import traceback
                self._ui_queue.put(("system", f"Ошибка запуска: {e}"))
                logger.error(traceback.format_exc())

        threading.Thread(target=_init, daemon=True).start()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _cb_state(self, state):
        self._ui_queue.put(("state", state))

    def _cb_transcript(self, text, partial):
        if partial:
            self._ui_queue.put(("system", text))
        else:
            self._ui_queue.put(("user_msg", text))

    def _cb_command(self, text):
        tl = text.strip().lower()
        if tl in ("микрофон", "выключи микрофон", "включи микрофон",
                  "заглуши микрофон", "отключи микрофон"):
            self._on_mute_toggle()
            return
        if self._dispatcher:
            try:
                self._dispatcher.dispatch(text)
            except Exception as e:
                self._ui_queue.put(("system", f"Ошибка: {e}"))

    def _cb_response(self, text):
        self._ui_queue.put(("bot_msg", text))
        self._apply_project_edits(text)

    def _apply_project_edits(self, reply: str):
        if not self._project_panel or not self._project_panel.get_project_dir():
            return
        from core.project_editor import apply_ai_edits, read_project_files, build_context
        from core.project_context import set_project_context
        changed = apply_ai_edits(self._project_panel.get_project_dir(), reply)
        if not changed:
            return
        files, _, all_files = read_project_files(
            self._project_panel.get_project_dir())
        self._project_panel._project_files = files
        self._project_panel._all_files = all_files
        set_project_context(build_context(files), self._project_panel.get_project_dir())
        if self._workspace:
            self._workspace.refresh_files(all_files, files)
            cur = getattr(self._workspace, "_current_path", "")
            if cur in changed and cur in files:
                self._workspace.reload_current(files[cur])
        names = ", ".join(changed)
        self._ui_queue.put(("system", f"✏️ AI изменил: {names}"))

    # ── Queue ─────────────────────────────────────────────────────────────────

    def _process_queue(self):
        if not self._root or not self._queue_running: return
        try:
            for _ in range(20):
                k, p = self._ui_queue.get_nowait()
                if   k == "state":    self._state = p
                elif k == "user_msg" and self._chat: self._chat.add_user(p)
                elif k == "bot_msg"  and self._chat: self._chat.add_bot(p)
                elif k == "system"   and self._chat: self._chat.add_system(p)
                elif k == "mute":     self._update_mute_ui(p)
                elif k == "project":  self._update_project_label()
        except queue.Empty:
            pass
        self._root.after(50, self._process_queue)

    # ── Input ─────────────────────────────────────────────────────────────────

    def _on_enter(self, event=None):
        text = self._inp.get().strip()
        if not text: return
        self._inp.set("")
        tl = text.lower()
        if tl in ("микрофон", "выключи микрофон", "включи микрофон",
                  "заглуши микрофон", "отключи микрофон"):
            self._on_mute_toggle()
            return
        if self._chat: self._chat.add_user(text)
        if not self._dispatcher:
            from core.command_dispatcher import CommandDispatcher
            self._dispatcher = CommandDispatcher(on_response=self._cb_response)
        self._state = "processing"
        threading.Thread(target=self._dispatch_bg, args=(text,),
                         daemon=True).start()

    def _dispatch_bg(self, text):
        try:
            self._dispatcher.dispatch(text)
        except Exception as e:
            self._ui_queue.put(("system", f"Ошибка: {e}"))
        finally:
            self._state = "listening"

    def _on_btn(self):
        self._on_enter()