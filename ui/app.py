"""
ui/app.py  –  W.O.R.K.E.R
Фон: assets/bg.jpg. Компактный UI на русском, размеры от шрифта и содержимого.
"""

import tkinter as tk
from tkinter import Menu as TkMenu
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
APP_SUB = "голосовой ассистент"
TZ_MGN = datetime.timezone(datetime.timedelta(hours=5))

# Цвета
BG = "#030a12"
BAR = "#061018"
CARD = "#0a1520"
LINE = "#1a3a55"
ACCENT = "#2eb8ff"
TEXT = "#dceefb"
MUTED = "#6a8fa8"
OK = "#3dd68c"
WARN = "#e8b84a"
ERR = "#ff5c6a"
OVERLAY = "#00060c"


def mgn_time() -> str:
    return datetime.datetime.now(tz=TZ_MGN).strftime("%H:%M:%S")


def mgn_datetime() -> str:
    return datetime.datetime.now(tz=TZ_MGN).strftime("%d.%m.%Y  %H:%M")


def _fonts(scale: float) -> dict:
    s = max(0.75, min(1.25, scale))
    return {
        "title": ("Segoe UI", max(13, int(16 * s)), "bold"),
        "ui": ("Segoe UI", max(9, int(10 * s))),
        "ui_sm": ("Segoe UI", max(8, int(9 * s))),
        "mono": ("Consolas", max(8, int(9 * s))),
        "orb": ("Segoe UI", max(10, int(11 * s)), "bold"),
    }


def _scale_from(w: int, h: int) -> float:
    return min(w / 1280, h / 800)


def _pct_color(pct: float) -> str:
    if pct >= 90:
        return ERR
    if pct >= 70:
        return WARN
    return OK


# ══════════════════════════════════════════════════════════════════════════════
class Ring:
    def __init__(self, canvas, cx, cy, r, color, speed, width=2, arc=130):
        self.c = canvas
        self.cx, self.cy, self.r = cx, cy, r
        self.col, self.spd, self.w, self.arc = color, speed, width, arc
        self.ang = random.uniform(0, 360)
        self._id = None

    def set_center(self, cx, cy):
        self.cx, self.cy = cx, cy

    def tick(self, state):
        m = 3.0 if state == "processing" else 1.0
        self.ang = (self.ang + self.spd * m) % 360
        if self._id:
            self.c.delete(self._id)
        cx, cy, r = self.cx, self.cy, self.r
        self._id = self.c.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=self.ang, extent=self.arc,
            outline=self.col, style=tk.ARC, width=self.w, tags="viz",
        )


# ══════════════════════════════════════════════════════════════════════════════
class SplashScreen:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        W, H = min(440, int(sw * 0.34)), min(200, int(sh * 0.22))
        self.win.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        self.win.configure(bg=BG)
        f = _fonts(_scale_from(W, H))
        inner = tk.Frame(self.win, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        inner.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Label(inner, text=APP_NAME, bg=CARD, fg=ACCENT, font=f["title"]).pack(pady=12)
        tk.Label(inner, text="Загрузка…", bg=CARD, fg=MUTED, font=f["ui"]).pack()
        self._bar_bg = tk.Frame(inner, bg=LINE, height=3)
        self._bar_bg.pack(fill="x", padx=24, pady=16)
        self._bar_bg.pack_propagate(False)
        self._bar = tk.Frame(self._bar_bg, bg=ACCENT, height=3, width=0)
        self._bar.place(relx=0, rely=0, relheight=1)
        self._bar_bg.bind("<Configure>", lambda e: setattr(self, "_bw", e.width))
        self._prog = 0.0
        self._bw = W - 48
        self._tick()

    def _tick(self):
        if not self.win.winfo_exists():
            return
        self._prog = min(1.0, self._prog + 0.012)
        self._bar.place(relwidth=max(0.02, self._prog))
        if self._prog < 1.0:
            self.win.after(20, self._tick)
        else:
            self.win.after(350, self.close)

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
class HWMonitor:
    """Три строки текста — без больших блоков."""

    def __init__(self, parent, root, fonts):
        self._root = root
        self._running = True
        self._labels = {}
        box = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        box.pack(anchor="nw", padx=0, pady=0)
        tk.Label(box, text="Система", bg=CARD, fg=MUTED, font=fonts["ui_sm"]).pack(
            anchor="w", padx=8, pady=4,
        )
        body = tk.Frame(box, bg=CARD)
        body.pack(anchor="w", padx=8, pady=4)
        for key, title in (("cpu", "ЦП"), ("gpu", "ГП"), ("ram", "ОЗУ")):
            row = tk.Frame(body, bg=CARD)
            row.pack(anchor="w", pady=1)
            tk.Label(row, text=f"{title}:", bg=CARD, fg=MUTED, font=fonts["mono"]).pack(side="left")
            lbl = tk.Label(row, text=" — ", bg=CARD, fg=ACCENT, font=fonts["mono"])
            lbl.pack(side="left", padx=4)
            self._labels[key] = lbl
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self):
        try:
            from commands.sysinfo import get_all_stats
        except ImportError:
            self._root.after(0, lambda: self._set_all("н/д"))
            return
        while self._running:
            try:
                s = get_all_stats()
                self._root.after(0, lambda st=s: self._apply(st))
            except Exception as e:
                logger.error(f"HW: {e}")
            time.sleep(2)

    def _set_all(self, t):
        for lbl in self._labels.values():
            lbl.config(text=t, fg=MUTED)

    def _apply(self, stats):
        try:
            cpu = float(stats.get("cpu_pct") or 0)
            ct = stats.get("cpu_temp")
            t = f" {cpu:.0f}%"
            if ct:
                t += f"  {ct:.0f}°C"
            self._labels["cpu"].config(text=t, fg=_pct_color(cpu))

            gpu = stats.get("gpu") or {}
            gl, gt, hs = gpu.get("load"), gpu.get("temp"), gpu.get("hotspot")
            if gl is not None:
                t = f" {gl:.0f}%"
                if gt:
                    t += f"  {gt:.0f}°C"
                if hs and hs != gt:
                    t += f"  ({hs:.0f}°)"
                self._labels["gpu"].config(text=t, fg=_pct_color(gl))
            else:
                self._labels["gpu"].config(text=" —", fg=MUTED)

            ram = stats.get("ram") or {}
            rp = float(ram.get("percent") or 0)
            t = f" {rp:.0f}%  {ram.get('used_gb', 0):.1f}/{ram.get('total_gb', 0):.0f} ГБ"
            self._labels["ram"].config(text=t, fg=_pct_color(rp))
        except Exception as e:
            logger.error(f"HW apply: {e}")

    def stop(self):
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
class JarvisApp:
    def __init__(self):
        self._ui_queue = queue.Queue()
        self._root = None
        self._canvas = None
        self._state = "listening"
        self._rings = []
        self._phase = 0.0
        self._bg_photo = None
        self._bg_img_raw = None
        self._bg_item = None
        self._W, self._H = 1280, 800
        self._cx, self._cy = 640, 400
        self._iris = self._pupil = None
        self._lbl_state = None
        self._wave_bars = []
        self._voice_engine = None
        self._dispatcher = None
        self._fonts = _fonts(1.0)
        self._stat_mic = self._stat_asr = None
        self._stat_state = None
        self._clock_lbl = None
        self._resp_lbl = None
        self._log = None
        self._inp = None
        self._pill = None
        self._resize_job = None
        self._hw = None
        self._tray = None

    def set_tray(self, tray):
        self._tray = tray

    def show_window(self):
        if self._root:
            self._root.deiconify()
            self._root.lift()
            self._root.focus_force()

    def hide_window(self):
        if self._root:
            self._root.withdraw()

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
        try:
            splash.close()
        except Exception:
            pass
        self._root.deiconify()
        self._root.after(80, self._start_core)
        self._root.after(16, self._anim_tick)
        self._root.after(50, self._process_queue)
        self._root.after(1000, self._clock_tick)

    def _build_ui(self):
        root = self._root
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        W = max(720, min(int(sw * 0.9), sw))
        H = max(520, min(int(sh * 0.9), sh))
        root.title("W.O.R.K.E.R — голосовой ассистент")
        root.configure(bg=BG)
        root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        root.minsize(640, 480)
        try:
            root.attributes("-toolwindow", True)
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self._canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        root.update_idletasks()
        self._W = root.winfo_width() or W
        self._H = root.winfo_height() or H
        self._fonts = _fonts(_scale_from(self._W, self._H))

        self._load_bg()

        # ── Полоски поверх canvas (только по размеру текста) ─────────────────
        top = tk.Frame(root, bg=BAR)
        top.pack(side="top", fill="x")
        f = self._fonts
        tk.Label(top, text=APP_NAME, bg=BAR, fg=ACCENT, font=f["title"]).pack(
            side="left", padx=10, pady=6,
        )
        tk.Label(top, text=APP_SUB, bg=BAR, fg=MUTED, font=f["ui_sm"]).pack(
            side="left", padx=4, pady=8,
        )
        self._pill = tk.Label(top, text="● Слушаю", bg=CARD, fg=OK, font=f["ui_sm"])
        self._pill.pack(side="left", padx=8, pady=6)
        tk.Button(
            top, text="В трей", command=self.hide_window,
            bg=CARD, fg=MUTED, font=f["ui_sm"], bd=0, relief="flat", cursor="hand2",
            padx=8, pady=2, activebackground=LINE, activeforeground=ACCENT,
        ).pack(side="right", padx=8, pady=6)
        self._clock_top = tk.Label(top, text=mgn_time(), bg=BAR, fg=MUTED, font=f["mono"])
        self._clock_top.pack(side="right", padx=6, pady=8)

        bottom = tk.Frame(root, bg=BAR)
        bottom.pack(side="bottom", fill="x")

        self._resp_lbl = tk.Label(
            bottom, text="Слушаю вас…", bg=BAR, fg=TEXT, font=f["ui"],
            anchor="w", justify="left", wraplength=max(200, self._W - 80),
        )
        self._resp_lbl.pack(fill="x", padx=12, pady=6)

        cmd_row = tk.Frame(bottom, bg=BAR)
        cmd_row.pack(fill="x", padx=10, pady=6)
        tk.Label(cmd_row, text="Команда:", bg=BAR, fg=MUTED, font=f["ui_sm"]).pack(side="left")
        self._inp = tk.StringVar()
        ent = tk.Entry(
            cmd_row, textvariable=self._inp, bg=CARD, fg=TEXT,
            insertbackground=ACCENT, font=f["ui"], relief="flat", bd=0,
        )
        ent.pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        ent.bind("<Return>", self._on_enter)
        ent.focus_set()
        tk.Button(
            cmd_row, text="Отправить", command=self._on_btn,
            bg=LINE, fg=ACCENT, font=f["ui_sm"], bd=0, relief="flat",
            cursor="hand2", padx=10, pady=2,
            activebackground=ACCENT, activeforeground=BG,
        ).pack(side="right")

        left = tk.Frame(root, bg=BG)
        left.pack(side="left", anchor="nw", padx=8, pady=8)
        self._hw = HWMonitor(left, root, f)

        log_box = tk.Frame(left, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        log_box.pack(anchor="nw", pady=8)
        tk.Label(log_box, text="Журнал", bg=CARD, fg=MUTED, font=f["ui_sm"]).pack(
            anchor="w", padx=8, pady=4,
        )
        lh = max(4, min(14, self._H // 55))
        lw = max(28, min(52, self._W // 28))
        self._log = tk.Text(
            log_box, bg=CARD, fg=TEXT, font=f["mono"], height=lh, width=lw,
            bd=0, highlightthickness=0, wrap="word",
            insertbackground=ACCENT, selectbackground=LINE,
        )
        self._log.pack(padx=6, pady=4)
        for tag, col in [("a", ACCENT), ("g", WARN), ("gr", OK), ("r", ERR), ("d", MUTED)]:
            self._log.tag_config(tag, foreground=col)
        self._log_menu = TkMenu(root, tearoff=0, bg=CARD, fg=TEXT, activebackground=LINE)
        self._log_menu.add_command(label="Копировать выделенное", command=self._log_copy_sel)
        self._log_menu.add_command(label="Копировать всё", command=self._log_copy_all)
        self._log_menu.add_separator()
        self._log_menu.add_command(label="Очистить", command=self._log_clear)
        self._log.bind("<Button-3>", self._show_log_menu)

        right = tk.Frame(root, bg=BG)
        right.pack(side="right", anchor="ne", padx=8, pady=8)
        st = tk.Frame(right, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        st.pack(anchor="ne")
        tk.Label(st, text="Статус", bg=CARD, fg=MUTED, font=f["ui_sm"]).pack(
            anchor="w", padx=8, pady=4,
        )
        body = tk.Frame(st, bg=CARD)
        body.pack(padx=8, pady=4)

        def row(lbl_text, val, col, attr):
            r = tk.Frame(body, bg=CARD)
            r.pack(anchor="w", pady=2)
            tk.Label(r, text=lbl_text, bg=CARD, fg=MUTED, font=f["ui_sm"]).pack(side="left")
            lb = tk.Label(r, text=val, bg=CARD, fg=col, font=f["ui_sm"])
            lb.pack(side="left", padx=6)
            setattr(self, attr, lb)

        row("Микрофон:", "активен", OK, "_stat_mic")
        row("Речь:", "онлайн", OK, "_stat_asr")
        self._stat_state = tk.Label(body, text="Слушаю", bg=CARD, fg=ACCENT, font=f["ui"])
        self._stat_state.pack(anchor="w", pady=6)
        tk.Label(body, text="Магнитогорск, UTC+5", bg=CARD, fg=MUTED, font=f["ui_sm"]).pack(anchor="w")
        self._clock_lbl = tk.Label(body, text=mgn_datetime(), bg=CARD, fg=TEXT, font=f["mono"])
        self._clock_lbl.pack(anchor="w", pady=2)

        root.bind("<Configure>", self._on_resize)
        root.update_idletasks()
        self._sync_canvas_geometry()
        self._lift_bars()

    def _sync_canvas_geometry(self):
        self._canvas.update_idletasks()
        self._W = max(100, self._canvas.winfo_width())
        self._H = max(100, self._canvas.winfo_height())
        self._cx = self._W // 2
        self._cy = self._H // 2
        self._render_bg()
        self._draw_viz()

    def _lift_bars(self):
        for w in self._root.winfo_children():
            if w != self._canvas:
                w.lift()

    def _load_bg(self):
        p = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "bg.jpg"))
        if not os.path.exists(p):
            return
        try:
            from PIL import Image
            self._bg_img_raw = Image.open(p).convert("RGB")
        except Exception as e:
            logger.error(f"Фон: {e}")

    def _render_bg(self):
        W, H = self._W, self._H
        c = self._canvas
        if not self._bg_img_raw:
            return
        try:
            from PIL import Image, ImageTk, ImageEnhance
            img = self._bg_img_raw.copy()
            ow, oh = img.size
            sc = max(W / ow, H / oh)
            nw, nh = int(ow * sc), int(oh * sc)
            img = img.resize((nw, nh), Image.LANCZOS)
            l, t = (nw - W) // 2, (nh - H) // 2
            img = img.crop((l, t, l + W, t + H))
            img = ImageEnhance.Brightness(img).enhance(0.5)
            self._bg_photo = ImageTk.PhotoImage(img)
            if self._bg_item:
                c.itemconfig(self._bg_item, image=self._bg_photo)
            else:
                self._bg_item = c.create_image(0, 0, anchor="nw", image=self._bg_photo, tags="bg")
                c.create_rectangle(0, 0, W, H, fill=OVERLAY, outline="", stipple="gray25", tags="bg")
            c.tag_raise("viz")
        except Exception as e:
            logger.error(f"bg: {e}")

    def _orb_r(self):
        return max(40, min(90, int(min(self._W, self._H) * 0.08)))

    def _draw_viz(self):
        c = self._canvas
        c.delete("viz")
        cx, cy = self._cx, self._cy
        R = self._orb_r()
        self._rings = [
            Ring(c, cx, cy, R + 50, ACCENT, 0.4, 2, 150),
            Ring(c, cx, cy, R + 72, LINE, -0.55, 1, 90),
        ]
        self._iris = c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=ACCENT, width=2, fill=BG, tags="viz")
        self._pupil = c.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill=ACCENT, outline="", tags="viz")
        self._lbl_state = c.create_text(
            cx, cy + R + 36, text="Слушаю", fill=TEXT, font=self._fonts["orb"], tags="viz",
        )
        n = max(10, min(28, self._W // 40))
        bw, gap = 3, 2
        bx0 = cx - (n * (bw + gap)) // 2
        by = cy + R + 56
        self._wave_bars = []
        for i in range(n):
            x = bx0 + i * (bw + gap)
            self._wave_bars.append(
                (c.create_rectangle(x, by, x + bw, by, fill=LINE, outline="", tags="viz"), x, by)
            )

    def _on_resize(self, event):
        if event.widget != self._root:
            return
        rw, rh = event.width, event.height
        if rw < 80 or rh < 80:
            return
        self._fonts = _fonts(_scale_from(rw, rh))
        if self._resp_lbl:
            self._resp_lbl.config(wraplength=max(160, rw - 100), font=self._fonts["ui"])
        if self._log:
            lh = max(4, min(14, rh // 55))
            lw = max(24, min(50, rw // 30))
            self._log.config(height=lh, width=lw, font=self._fonts["mono"])
        if self._resize_job:
            self._root.after_cancel(self._resize_job)
        self._resize_job = self._root.after(100, self._resize_done)

    def _resize_done(self):
        self._resize_job = None
        old_w, old_h = self._W, self._H
        self._sync_canvas_geometry()
        if abs(self._W - old_w) > 8 or abs(self._H - old_h) > 8:
            for r in self._rings:
                r.set_center(self._cx, self._cy)
            self._draw_viz()
            self._render_bg()

    def _clock_tick(self):
        try:
            if self._clock_lbl:
                self._clock_lbl.config(text=mgn_datetime())
            if hasattr(self, "_clock_top"):
                self._clock_top.config(text=mgn_time())
        except Exception:
            pass
        if self._root:
            self._root.after(1000, self._clock_tick)

    def _anim_tick(self):
        if not self._root:
            return
        try:
            for r in self._rings:
                r.tick(self._state)
            self._tick_core()
            self._tick_wave()
        except tk.TclError:
            return
        self._root.after(16, self._anim_tick)

    def _tick_core(self):
        self._phase = (self._phase + 0.07) % (6.28)
        p = math.sin(self._phase)
        if self._state == "processing":
            oc, pc, lbl, pill_c = WARN, WARN, "Обработка…", WARN
        else:
            oc, pc, lbl, pill_c = ACCENT, ACCENT, "Слушаю", OK
        R = self._orb_r()
        s = 1.0 + 0.08 * p
        ri, rp = int(R * s), max(5, int(8 * s))
        cx, cy = self._cx, self._cy
        c = self._canvas
        if self._iris:
            c.coords(self._iris, cx - ri, cy - ri, cx + ri, cy + ri)
            c.itemconfig(self._iris, outline=oc)
        if self._pupil:
            c.coords(self._pupil, cx - rp, cy - rp, cx + rp, cy + rp)
        if self._lbl_state:
            c.itemconfig(self._lbl_state, text=lbl, fill=oc)
        if self._pill:
            self._pill.config(text=f"● {lbl}", fg=pill_c)
        if self._stat_state:
            self._stat_state.config(text=lbl, fg=oc)

    def _tick_wave(self):
        t = time.time()
        R, active = self._orb_r(), self._state == "processing"
        by = self._cy + R + 56
        for i, (bid, bx, _) in enumerate(self._wave_bars):
            h = (abs(math.sin(t * 5 + i * 0.4)) * 28 + 8) if active else (2 + abs(math.sin(t * 0.3 + i * 0.2)) * 2)
            col = ACCENT if active else LINE
            self._canvas.coords(bid, bx, by - h, bx + 3, by)
            self._canvas.itemconfig(bid, fill=col)

    def _show_log_menu(self, e):
        try:
            self._log_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._log_menu.grab_release()

    def _log_copy_sel(self):
        try:
            s = self._log.get(tk.SEL_FIRST, tk.SEL_LAST)
            self._root.clipboard_clear()
            self._root.clipboard_append(s)
        except tk.TclError:
            pass

    def _log_copy_all(self):
        self._root.clipboard_clear()
        self._root.clipboard_append(self._log.get("1.0", tk.END))

    def _log_clear(self):
        self._log.delete("1.0", tk.END)

    def _start_core(self):
        self._log_ui("Запуск…", "a")

        def _init():
            try:
                from core.voice_engine import VoiceEngine
                from core.command_dispatcher import CommandDispatcher
                self._dispatcher = CommandDispatcher(on_response=self._cb_response)
                self._voice_engine = VoiceEngine(
                    on_state_change=self._cb_state,
                    on_transcript=self._cb_transcript,
                    on_command=self._cb_command,
                )
                self._voice_engine.start()
                mode = "голос" if self._voice_engine._sd_ok else "текст"
                self._ui_queue.put(("log", (f"Готово · режим: {mode}", "gr")))
                self._ui_queue.put(("log", ("Ожидаю команды…", "d")))
            except Exception as e:
                import traceback
                self._ui_queue.put(("log", (f"Ошибка: {e}", "r")))
                logger.error(traceback.format_exc())

        threading.Thread(target=_init, daemon=True).start()

    def _cb_state(self, state):
        self._ui_queue.put(("state", state))

    def _cb_transcript(self, text, partial):
        self._ui_queue.put(("transcript", (text, partial)))

    def _cb_command(self, text):
        if self._dispatcher:
            try:
                self._dispatcher.dispatch(text)
            except Exception as e:
                self._ui_queue.put(("log", (f"Ошибка: {e}", "r")))

    def _cb_response(self, text):
        self._ui_queue.put(("response", text))

    def _process_queue(self):
        try:
            while True:
                k, p = self._ui_queue.get_nowait()
                if k == "state":
                    self._state = p
                elif k == "transcript":
                    self._log_ui(f"> {p[0]}", "d" if p[1] else "a")
                elif k == "response":
                    self._set_response(p)
                elif k == "log":
                    self._log_ui(*p)
        except queue.Empty:
            pass
        if self._root:
            self._root.after(50, self._process_queue)

    def _set_response(self, text):
        if self._resp_lbl:
            self._resp_lbl.config(text=text)
        self._log_ui(text, "g")
        if self._voice_engine:
            self._voice_engine.speak(text)

    def _log_ui(self, text, tag=""):
        try:
            self._log.insert("end", f"[{mgn_time()}] {text}\n", tag)
            self._log.see("end")
        except Exception:
            pass

    def _on_enter(self, event=None):
        text = self._inp.get().strip()
        if not text:
            return
        self._inp.set("")
        self._log_ui(f"Вы: {text}", "a")
        if self._voice_engine:
            self._voice_engine.send_text_command(text)
        else:
            from core.command_dispatcher import CommandDispatcher
            if not self._dispatcher:
                self._dispatcher = CommandDispatcher(on_response=self._cb_response)
            self._state = "processing"
            try:
                self._dispatcher.dispatch(text)
            except Exception as e:
                self._log_ui(str(e), "r")
            self._state = "listening"

    def _on_btn(self):
        self._on_enter()
