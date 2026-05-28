"""
ui/app.py  –  W.O.R.K.E.R  v4  — фикс дублирования

Причины дублирования были:
  1. bind_all("<MouseWheel>") накапливал обработчики
  2. _process_queue/_anim_tick/_clock_tick могли запускаться повторно
  3. on_command вызывал dispatch, который звал on_response,
     который звал _cb_response — всё это нормально, но
     VoiceEngine._execute_command дополнительно звал on_transcript
     который добавлял ещё один пузырёк

Решения:
  - Все периодические задачи защищены флагами (уже запущен?)
  - bind на <MouseWheel> только на canvas чата (не bind_all)
  - Строгое разделение: голос → on_transcript(text,False) → пузырёк
    текст → add_user() в _on_enter → диспатч напрямую, VoiceEngine не трогаем
  - _cb_command ТОЛЬКО диспатчит, НИКОГДА не пишет в чат
"""

import tkinter as tk
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
            self._root.after(0, lambda: [l.config(text="н/д", fg=MUTED)
                                          for l in self._labels.values()])
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
    Чат с пузырьками.
    bg.jpg — фон на весь canvas, затемнённый.
    MouseWheel — только на self._canvas (не bind_all).
    """
    def __init__(self, parent, fonts, bg_path=""):
        self._fonts   = fonts
        self._bg_pil  = None
        self._bg_img  = None
        self._bg_item = None

        outer = tk.Frame(parent, bg=BG2)
        outer.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(outer, bg=BG2, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(outer, orient="vertical",
                           command=self._canvas.yview,
                           bg=CARD2, troughcolor=BG2,
                           bd=0, width=6, relief="flat")
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner  = tk.Frame(self._canvas, bg=BG2)
        self._win_id = self._canvas.create_window(
            (0,0), window=self._inner, anchor="nw", tags="msgs")

        self._inner.bind("<Configure>", self._on_inner_cfg)
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        # ТОЛЬКО на canvas — не bind_all
        self._canvas.bind("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._inner.bind("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

        if bg_path and os.path.exists(bg_path):
            self._load_bg(bg_path)

    def _load_bg(self, path):
        try:
            from PIL import Image, ImageTk, ImageEnhance, ImageFilter
            img = Image.open(path).convert("RGB")
            img = ImageEnhance.Brightness(img).enhance(0.25)
            img = img.filter(ImageFilter.GaussianBlur(radius=3))
            self._bg_pil = img
            self._canvas.after(80, self._render_bg)
        except Exception as e:
            logger.error(f"chat bg load: {e}")

    def _render_bg(self):
        if self._bg_pil is None: return
        try:
            from PIL import Image, ImageTk
            w = self._canvas.winfo_width()
            h = self._canvas.winfo_height()
            if w < 10 or h < 10:
                self._canvas.after(100, self._render_bg)
                return
            img = self._bg_pil.copy()
            ow, oh = img.size
            sc  = max(w/ow, h/oh)
            nw  = int(ow*sc)+1; nh = int(oh*sc)+1
            img = img.resize((nw, nh), Image.LANCZOS)
            l   = (nw-w)//2; t = (nh-h)//2
            img = img.crop((l, t, l+w, t+h))
            self._bg_img = ImageTk.PhotoImage(img)
            if self._bg_item:
                self._canvas.itemconfig(self._bg_item, image=self._bg_img)
                self._canvas.coords(self._bg_item, 0, 0)
            else:
                self._bg_item = self._canvas.create_image(
                    0, 0, anchor="nw", image=self._bg_img, tags="bg")
            self._canvas.tag_lower("bg", "msgs")
        except Exception as e:
            logger.error(f"chat bg render: {e}")

    def refresh_bg(self):
        if self._bg_pil: self._render_bg()

    # ── Public ────────────────────────────────────────────────────────────────

    def add_user(self, text, ts=""):
        self._bubble(text, "user", ts or mgn_time())

    def add_bot(self, text, ts=""):
        self._bubble(text, "bot", ts or mgn_time())

    def add_system(self, text):
        row = tk.Frame(self._inner, bg=BG2)
        row.pack(fill="x", padx=10, pady=2)
        tk.Label(row, text=f"— {text} —", bg=BG2, fg=SYS_FG,
                 font=self._fonts["ui_xs"]).pack()
        self._scroll_bottom()

    def update_fonts(self, fonts):
        self._fonts = fonts

    # ── Private ───────────────────────────────────────────────────────────────

    def _bubble(self, text, who, ts):
        is_user  = (who == "user")
        bg_c     = USER_BG     if is_user else BOT_BG
        fg_c     = USER_FG     if is_user else BOT_FG
        brd_c    = USER_BORDER if is_user else BOT_BORDER
        name_fg  = ACCENT      if is_user else OK
        name_txt = "Вы"        if is_user else "W.O.R.K.E.R"
        side     = "right"     if is_user else "left"
        pad_l    = 80 if is_user else 6
        pad_r    = 6  if is_user else 80

        row = tk.Frame(self._inner, bg=BG2)
        row.pack(fill="x", pady=2)

        bubble = tk.Frame(row, bg=bg_c,
                          highlightbackground=brd_c, highlightthickness=1)
        bubble.pack(side=side, padx=(pad_l, pad_r), anchor="n")

        hdr = tk.Frame(bubble, bg=bg_c)
        hdr.pack(fill="x", padx=8, pady=(5,0))
        tk.Label(hdr, text=name_txt, bg=bg_c, fg=name_fg,
                 font=self._fonts["chat_sm"]).pack(side="left")
        tk.Label(hdr, text=ts, bg=bg_c, fg=MUTED,
                 font=self._fonts["ui_xs"]).pack(side="right")

        self._render_content(bubble, text, bg_c, fg_c)
        tk.Frame(bubble, bg=bg_c, height=5).pack()
        self._scroll_bottom()

    def _render_content(self, parent, text, bg_c, fg_c):
        import re
        parts = re.split(r"(```[\s\S]*?```)", text)
        for part in parts:
            if not part: continue
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
                    anchor="w", padx=6, pady=(3,0))
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
                cl.pack(fill="x", padx=6, pady=(0,0))
                sb.pack(fill="x", padx=6, pady=(0,4))
            else:
                txt = part.strip()
                if txt:
                    lbl = tk.Label(parent, text=txt,
                                   bg=bg_c, fg=fg_c,
                                   font=self._fonts["chat"],
                                   justify="left", anchor="w",
                                   wraplength=400)
                    lbl.pack(fill="x", padx=8, pady=(3,1), anchor="w")
                    lbl.bind("<Configure>",
                             lambda e, l=lbl:
                             l.config(wraplength=max(80, e.width-24)))

    def _on_inner_cfg(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_cfg(self, e):
        self._canvas.itemconfig(self._win_id, width=e.width)
        if self._bg_pil: self._canvas.after(60, self._render_bg)

    def _scroll_bottom(self):
        self._canvas.after(40, lambda: self._canvas.yview_moveto(1.0))


# ══════════════════════════════════════════════════════════════════════════════
class JarvisApp:
    def __init__(self):
        self._ui_queue    = queue.Queue()
        self._root        = None
        self._state       = "listening"
        self._rings       = []
        self._phase       = 0.0
        self._orb_canvas  = None
        self._orb_bg_img  = None
        self._iris = self._pupil = self._lbl_orb = None
        self._wave_bars   = []
        self._voice_engine = None
        self._dispatcher  = None
        self._fonts       = _fonts(1.0)
        self._btn_mute    = None
        self._pill        = None
        self._stat_mic    = None
        self._stat_asr    = None
        self._stat_state  = None
        self._clock_lbl   = None
        self._clock_top   = None
        self._inp         = None
        self._chat        = None
        self._hw          = None
        self._tray        = None
        self._resize_job  = None
        self._bg_path     = ""

        # Флаги защиты от повторного запуска периодических задач
        self._queue_running = False
        self._anim_running  = False
        self._clock_running = False

    def set_tray(self, t): self._tray = t

    def show_window(self):
        if self._root:
            self._root.deiconify(); self._root.lift(); self._root.focus_force()

    def hide_window(self):
        if self._root: self._root.withdraw()

    def run(self):
        root = tk.Tk()
        self._root = root
        root.withdraw(); root.update()
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
        # Запускаем периодические задачи — только один раз каждую
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
        W = max(960, min(int(sw*0.92), sw))
        H = max(580, min(int(sh*0.92), sh))
        root.title("W.O.R.K.E.R — голосовой ассистент")
        root.configure(bg=BG)
        root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        root.minsize(820, 540)
        try: root.attributes("-toolwindow", True)
        except Exception: pass
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        root.update_idletasks()
        self._fonts = _fonts(_scale_from(
            root.winfo_width() or W, root.winfo_height() or H))
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
        st_box.pack(fill="x", padx=8, pady=(8,4))
        tk.Label(st_box, text="СТАТУС", bg=CARD, fg=MUTED,
                 font=f["ui_xs"]).pack(anchor="w", padx=8, pady=(5,2))
        bd = tk.Frame(st_box, bg=CARD)
        bd.pack(fill="x", padx=8, pady=(0,6))

        def st_row(txt, val, col, attr):
            r = tk.Frame(bd, bg=CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=txt, bg=CARD, fg=MUTED,
                     font=f["ui_xs"], width=12, anchor="w").pack(side="left")
            lb = tk.Label(r, text=val, bg=CARD, fg=col, font=f["ui_xs"])
            lb.pack(side="left")
            setattr(self, attr, lb)

        st_row("Микрофон:",   "активен", OK, "_stat_mic")
        st_row("Распознав.:", "онлайн",  OK, "_stat_asr")
        self._stat_state = tk.Label(bd, text="Слушаю", bg=CARD,
                                    fg=ACCENT, font=f["ui_sm"])
        self._stat_state.pack(anchor="w", pady=(4,2))
        tk.Frame(st_box, bg=LINE, height=1).pack(fill="x", padx=6)
        tz = tk.Frame(st_box, bg=CARD)
        tz.pack(fill="x", padx=8, pady=(4,6))
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
                 font=f["ui_xs"]).pack(anchor="w", padx=8, pady=(5,2))
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

        chat_body = tk.Frame(right, bg=BG2)
        chat_body.pack(fill="both", expand=True)
        self._chat = ChatWidget(
            chat_body, f,
            bg_path=self._bg_path if os.path.exists(self._bg_path) else "")

        tk.Frame(right, bg=LINE, height=1).pack(fill="x")

        inp_row = tk.Frame(right, bg=TOPBAR)
        inp_row.pack(fill="x", side="bottom")
        tk.Label(inp_row, text=">", bg=TOPBAR, fg=ACCENT2,
                 font=f["mono"]).pack(side="left", padx=(10,4), pady=8)
        self._inp = tk.StringVar()
        ent = tk.Entry(inp_row, textvariable=self._inp,
                       bg=CARD2, fg=TEXT, insertbackground=ACCENT,
                       font=f["chat"], relief="flat", bd=0,
                       highlightthickness=1,
                       highlightbackground=LINE,
                       highlightcolor=ACCENT)
        ent.pack(side="left", fill="x", expand=True,
                 padx=(0,6), ipady=6, pady=7)
        ent.bind("<Return>", self._on_enter)
        ent.focus_set()
        tk.Button(inp_row, text="Отправить", command=self._on_btn,
                  bg=ACCENT_DIM, fg=ACCENT, font=f["ui_xs"],
                  bd=0, relief="flat", cursor="hand2",
                  padx=10, pady=4,
                  activebackground=ACCENT2, activeforeground=BG,
                  ).pack(side="right", padx=8, pady=7)

        root.bind("<Configure>", self._on_resize)

    # ── Орб ──────────────────────────────────────────────────────────────────

    def _load_orb_bg(self):
        p = self._bg_path if hasattr(self, "_bg_path") and self._bg_path else \
            os.path.normpath(os.path.join(
                os.path.dirname(__file__), "..", "assets", "bg.jpg"))
        if not os.path.exists(p) or not self._orb_canvas: return
        try:
            from PIL import Image, ImageTk, ImageEnhance
            img = Image.open(p).convert("RGB")
            W, H = 222, 175
            ow, oh = img.size
            sc = max(W/ow, H/oh)
            nw, nh = int(ow*sc), int(oh*sc)
            img = img.resize((nw, nh), Image.LANCZOS)
            l, t = (nw-W)//2, 0
            img = img.crop((l, t, l+W, t+H))
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
        cx = W//2; cy = H//2 - 8; R = 40
        self._rings = [
            Ring(c, cx, cy, R+26, ACCENT,  0.35, 2, 160),
            Ring(c, cx, cy, R+42, LINE2,  -0.5,  1,  80),
        ]
        self._iris    = c.create_oval(cx-R, cy-R, cx+R, cy+R,
                                      outline=ACCENT, width=2, fill=BG,
                                      tags="viz")
        self._pupil   = c.create_oval(cx-5, cy-5, cx+5, cy+5,
                                      fill=ACCENT, outline="", tags="viz")
        self._lbl_orb = c.create_text(cx, cy+R+18, text="Слушаю",
                                       fill=TEXT2, font=self._fonts["orb_sm"],
                                       tags="viz")
        n = max(8, min(16, W//14))
        bw, gap = 3, 2
        bx0 = cx - (n*(bw+gap))//2
        by  = cy + R + 32
        self._wave_bars = []
        for i in range(n):
            x = bx0 + i*(bw+gap)
            self._wave_bars.append(
                (c.create_rectangle(x, by, x+bw, by,
                                    fill=LINE, outline="", tags="viz"), x, by))

    # ── Мут ──────────────────────────────────────────────────────────────────

    def _on_mute_toggle(self):
        if self._voice_engine: self._voice_engine.toggle_mute()

    def _cb_mute_change(self, is_muted):
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

        # Орб показывает ТОЛЬКО состояние обработки — мут его не касается
        if self._state == "processing":
            oc, lbl = WARN, "Думаю…"
        else:
            oc, lbl = ACCENT, "Слушаю"

        R  = 40; s = 1.0 + 0.07*p
        ri = int(R*s); rp = max(3, int(5*s))
        W, H = 222, 175
        cx = W//2; cy = H//2 - 8
        c = self._orb_canvas
        if not c: return

        if self._iris:
            c.coords(self._iris, cx-ri, cy-ri, cx+ri, cy+ri)
            c.itemconfig(self._iris, outline=oc)
        if self._pupil:
            c.coords(self._pupil, cx-rp, cy-rp, cx+rp, cy+rp)
        if self._lbl_orb:
            c.itemconfig(self._lbl_orb, text=lbl, fill=oc)
        # Пилюля в топбаре — отдельно показывает мут если нужно
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
        cx = W//2; cy = H//2 - 8; R = 40; by = cy+R+32
        for i, (bid, bx, _) in enumerate(self._wave_bars):
            if active:
                h = abs(math.sin(t*5 + i*0.4))*18 + 5; col = WARN
            else:
                h = 2 + abs(math.sin(t*0.4 + i*0.25))*2; col = LINE2
            self._orb_canvas.coords(bid, bx, by-h, bx+3, by)
            self._orb_canvas.itemconfig(bid, fill=col)

    # ── Core ─────────────────────────────────────────────────────────────────

    def _start_core(self):
        # Защита от повторного вызова
        if self._voice_engine is not None: return
        if self._chat: self._chat.add_system("Запуск W.O.R.K.E.R…")

        def _init():
            try:
                from core.voice_engine import VoiceEngine
                from core.command_dispatcher import CommandDispatcher
                self._dispatcher   = CommandDispatcher(
                    on_response=self._cb_response)
                self._voice_engine = VoiceEngine(
                    on_state_change=self._cb_state,
                    on_transcript=self._cb_transcript,
                    on_command=self._cb_command,
                    on_mute_change=self._cb_mute_change,
                )
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
        # Вызывается из VoiceEngine-потока — только очередь, никакого UI
        self._ui_queue.put(("state", state))

    def _cb_transcript(self, text, partial):
        """
        partial=False → голосовая фраза → пузырёк user (ОДИН РАЗ)
        partial=True  → системное событие (мут) → system-строка
        """
        if partial:
            self._ui_queue.put(("system", text))
        else:
            self._ui_queue.put(("user_msg", text))

    def _cb_command(self, text):
        """
        Вызывается из VoiceEngine после on_transcript.
        ТОЛЬКО диспатч — никакого add_user, никакого лога.
        Сообщение пользователя уже добавлено через _cb_transcript.
        """
        if self._dispatcher:
            try:
                self._dispatcher.dispatch(text)
            except Exception as e:
                self._ui_queue.put(("system", f"Ошибка: {e}"))

    def _cb_response(self, text):
        """Ответ бота → в очередь."""
        self._ui_queue.put(("bot_msg", text))

    # ── Queue ─────────────────────────────────────────────────────────────────

    def _process_queue(self):
        if not self._root or not self._queue_running: return
        try:
            # Обрабатываем не более 20 событий за тик чтобы не тормозить UI
            for _ in range(20):
                k, p = self._ui_queue.get_nowait()
                if   k == "state":    self._state = p
                elif k == "user_msg" and self._chat: self._chat.add_user(p)
                elif k == "bot_msg"  and self._chat: self._chat.add_bot(p)
                elif k == "system"   and self._chat: self._chat.add_system(p)
                elif k == "mute":     self._update_mute_ui(p)
        except queue.Empty:
            pass
        self._root.after(50, self._process_queue)

    # ── Input ─────────────────────────────────────────────────────────────────

    def _on_enter(self, event=None):
        text = self._inp.get().strip()
        if not text: return
        self._inp.set("")

        # Пузырёк user — ОДИН РАЗ, здесь, больше нигде
        if self._chat: self._chat.add_user(text)

        # Диспетчер
        if not self._dispatcher:
            from core.command_dispatcher import CommandDispatcher
            self._dispatcher = CommandDispatcher(on_response=self._cb_response)

        # Диспатч в фоне напрямую — VoiceEngine вообще не трогаем
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