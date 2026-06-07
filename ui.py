from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal, QPropertyAnimation, QByteArray, QEvent,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut, QIcon,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar, QGraphicsBlurEffect,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 1060, 720
_MIN_W,     _MIN_H     = 880, 600
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#00d4ff"
    PRI_DIM   = "#007a99"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#8ffcff"
    TEXT_DIM  = "#3a8a9a"
    TEXT_MED  = "#5ab8cc"
    WHITE     = "#d8f8ff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        # Allow the central background to show through; use translucent background
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        except Exception:
            # fallback: remove opaque flag if present
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            except Exception:
                pass
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)
        self._animations_enabled = True

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        # scanning arcs update (reduced when animations are disabled)
        scan_speed = (3.0 if self.speaking else 1.3) if self._animations_enabled else (1.0 if self.speaking else 0.4)
        scan2_speed = (-2.0 if self.speaking else -0.75) if self._animations_enabled else (-0.6 if self.speaking else -0.15)
        self._scan  = (self._scan  + scan_speed) % 360
        self._scan2 = (self._scan2 + scan2_speed) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        # pulses and particles are animation-heavy; skip or throttle when disabled
        if self._animations_enabled:
            self._pulses = [r + spd for r in self._pulses if r + spd < lim]
            if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
                self._pulses.append(0.0)

            if self.speaking and random.random() < 0.28:
                cx, cy = self.width() / 2, self.height() / 2
                ang = random.uniform(0, 2 * math.pi)
                r_s = fw * 0.28
                self._particles.append([
                    cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                    math.cos(ang) * random.uniform(0.9, 2.4),
                    math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
                ])
        # always decay existing particles but slower when animations disabled
        decay = 0.028 if self._animations_enabled else 0.006
        mult = 0.97 if self._animations_enabled else 0.995
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*mult, p[3]*mult, p[4]-decay]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def set_animations_enabled(self, v: bool):
        self._animations_enabled = bool(v)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Do not fill the full rect — keep HUD translucent so background shows through

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots
        p.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc    = (200, 0, 50) if self.muted else (0, 60, 110)
            for i in range(8, 0, -1):
                r2  = int(orb_r * i / 8)
                frc = i / 8
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, "S.T.E.V.E")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

class MetricBar(QWidget):

    def __init__(self, label: str, symbol: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._symbol = symbol
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(34)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 3, 40, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        p.setPen(QPen(qcol(self._color), 1))
        p.drawText(QRectF(0, 1, W - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._symbol)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 16, W - 16, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)

class CircularStatWidget(QWidget):
    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0
        self._text = "--"
        self._extra_lines: list[str] = []
        self.setFixedSize(100, 100)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text = text
        self.update()

    def set_extra(self, lines: list[str]):
        self._extra_lines = lines
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        r = min(W, H) / 2 - 4

        # outer ring
        outer_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        p.setPen(QPen(qcol(C.BORDER_B, 100), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(outer_rect)

        # background arc (dark, subtle)
        bg_pen = QPen(qcol(C.BORDER, 40), 3.5)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(bg_pen)
        p.drawArc(outer_rect, -90 * 16, 360 * 16)

        # value arc
        if self._value > 0:
            span = int(360 * 16 * (self._value / 100.0))
            val_pen = QPen(qcol(self._color, 200), 3.5)
            val_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(val_pen)
            p.drawArc(outer_rect, -90 * 16, span)

        # inner dark circle
        inner_r = r * 0.70
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol("#040c12", 250)))
        p.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))

        # value text (top half)
        p.setPen(QPen(qcol(self._color), 1))
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy - 18, W, 16), Qt.AlignmentFlag.AlignCenter, self._text)

        # label (bottom inside circle)
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy + 2, W, 14), Qt.AlignmentFlag.AlignCenter, self._label)

        # extra lines below label (for UP widget: PROC, OS)
        if self._extra_lines:
            p.setFont(QFont("Courier New", 6))
            ey = cy + 14
            for line in self._extra_lines:
                p.setPen(QPen(qcol(C.TEXT_DIM), 1))
                p.drawText(QRectF(0, ey, W, 10), Qt.AlignmentFlag.AlignCenter, line)
                ey += 10


class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("steve:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)


class OrbitalClockWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(110, 110)
        self.setMaximumSize(130, 130)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._time_text = "00:00:00"
        self._day_text = ""
        self._date_text = ""
        self._second_pulse = 0.0
        self._pulse_tmr = QTimer(self)
        self._pulse_tmr.timeout.connect(self._pulse_step)
        self._pulse_tmr.start(33)

    def set_time(self, time_text: str, day_text: str, date_text: str):
        self._time_text = time_text
        self._day_text = day_text
        self._date_text = date_text
        self._second_pulse = 1.0
        self.update()

    def _pulse_step(self):
        if self._second_pulse > 0.0:
            self._second_pulse = max(0.0, self._second_pulse - 0.05)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        r = min(W, H) / 2 - 3

        # base circular frame
        frame_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        outer = QLinearGradient(frame_rect.topLeft(), frame_rect.bottomRight())
        outer.setColorAt(0.0, qcol(C.PRI, 110))
        outer.setColorAt(1.0, qcol(C.ACC, 80))
        p.setPen(QPen(qcol(C.BORDER_B, 200), 1.2))
        p.setBrush(QBrush(qcol(C.PANEL2, 230)))
        p.drawEllipse(frame_rect)

        # orbital glow ring
        pulse_r = r * (0.72 + 0.08 * self._second_pulse)
        pulse_a = int(220 * self._second_pulse)
        p.setPen(QPen(qcol(C.PRI, pulse_a), 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - pulse_r, cy - pulse_r, pulse_r * 2, pulse_r * 2))

        # minor orbit ticks around the circle
        p.setPen(QPen(qcol(C.PRI_DIM, 170), 1))
        tick_r1 = r * 0.88
        tick_r2 = r * 0.98
        for deg in range(0, 360, 30):
            rad = math.radians(deg)
            p.drawLine(
                QPointF(cx + tick_r1 * math.cos(rad), cy - tick_r1 * math.sin(rad)),
                QPointF(cx + tick_r2 * math.cos(rad), cy - tick_r2 * math.sin(rad)),
            )

        # inner glass center
        inner_r = r * 0.62
        inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol("#091f2a", 220)))
        p.drawEllipse(inner_rect)

        # text — line 1: time
        p.setPen(QPen(qcol(C.PRI, 245), 1))
        p.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy - 24, W, 20), Qt.AlignmentFlag.AlignCenter, self._time_text)

        # line 2: day
        p.setPen(QPen(qcol(C.TEXT_DIM, 220), 1))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy + 0, W, 14), Qt.AlignmentFlag.AlignCenter, self._day_text)

        # line 3: date
        p.setFont(QFont("Courier New", 7))
        p.drawText(QRectF(0, cy + 14, W, 12), Qt.AlignmentFlag.AlignCenter, self._date_text)

        # second pulse indicator
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.ACC2, int(180 * self._second_pulse))))
        p.drawEllipse(QPointF(cx, cy + r * 0.33), 2.5 + 2.5 * self._second_pulse, 2.5 + 2.5 * self._second_pulse)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for STEVE", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure S.T.E.V.E. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)


class ScenarioCard(QWidget):
    """A centered glassmorphism card using SVG borders, animated neon glow
    and a blurred frosted inner area. Content is data-driven and can flip
    between multiple scenario entries loaded from JSON.
    """
    def __init__(self, title: str, lines: list[str], parent=None, svg_path: str | None = None, scenarios: list[dict] | None = None, start_index: int = 0):
        super().__init__(parent)
        self._title = title
        self._lines = lines
        self._svg_path = svg_path
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # blur effect for frosted glass inner rect
        self._blur = QGraphicsBlurEffect(self)
        self._blur.setBlurRadius(12)
        # We'll apply the blur conditionally to the inner overlay

        # SVG renderer for border art (if provided)
        self._svg_renderer = QSvgRenderer(self._svg_path) if self._svg_path else None

        # animation state for neon glow
        self._neon_phase = 0.0
        self._neon_timer = QTimer(self)
        self._neon_timer.timeout.connect(self._neon_step)
        self._neon_timer.start(40)

        # controls
        self._icon_prev = QIcon()
        self._icon_next = QIcon()
        self._icon_close = QIcon()

        # scenarios list for flipping
        self._scenarios = scenarios or []
        self._idx = max(0, min(start_index, len(self._scenarios)-1)) if self._scenarios else 0

        # clickable area rects (computed on resize)
        self._ctrl_rects: dict[str, QRectF] = {}

    def _neon_step(self):
        self._neon_phase = (self._neon_phase + 0.06) % (2 * math.pi)
        self.update()

    def load_icons_from_svgs(self, prev_svg: str, next_svg: str, close_svg: str):
        try:
            self._icon_prev = QIcon(prev_svg)
            self._icon_next = QIcon(next_svg)
            self._icon_close = QIcon(close_svg)
        except Exception:
            pass

    def set_scenarios(self, scenarios: list[dict], start_index: int = 0):
        self._scenarios = scenarios or []
        self._idx = max(0, min(start_index, len(self._scenarios)-1)) if self._scenarios else 0
        if self._scenarios:
            cur = self._scenarios[self._idx]
            self._title = cur.get("title", self._title)
            self._lines = list(cur.get("lines", self._lines))
        self.update()

    def mousePressEvent(self, e):
        for name, rect in self._ctrl_rects.items():
            if rect.contains(e.position()):
                if name == "close":
                    self.hide()
                elif name == "prev":
                    self._on_prev()
                elif name == "next":
                    self._on_next()
                return

    def _on_prev(self):
        if not self._scenarios:
            return
        self._idx = (self._idx - 1) % len(self._scenarios)
        cur = self._scenarios[self._idx]
        self._title = cur.get("title", self._title)
        self._lines = list(cur.get("lines", self._lines))
        self.update()

    def _on_next(self):
        if not self._scenarios:
            return
        self._idx = (self._idx + 1) % len(self._scenarios)
        cur = self._scenarios[self._idx]
        self._title = cur.get("title", self._title)
        self._lines = list(cur.get("lines", self._lines))
        self.update()

    def capture_background_and_blur(self):
        # Capture parent widget background and set a blurred pixmap under inner rect
        try:
            parent = self.parent() or self.window()
            if not parent:
                return
            full = parent.grab()  # QPixmap of parent
            W, H = self.width(), self.height()
            pad = 20
            r = QRectF(pad, pad, W - pad * 2, H - pad * 2)
            inner = r.adjusted(12, 12, -12, -12)
            # crop full pixmap to inner area in this widget's coordinates
            mapped = full.copy(int((self.x()+inner.left())), int((self.y()+inner.top())), int(inner.width()), int(inner.height()))
            lbl = getattr(self, "_frost_label", None)
            if lbl is None:
                from PyQt6.QtWidgets import QLabel
                lbl = QLabel(self)
                lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                lbl.setGeometry(int(inner.left()), int(inner.top()), int(inner.width()), int(inner.height()))
                lbl.setScaledContents(True)
                lbl.setStyleSheet("border-radius: 8px;")
                lbl.setGraphicsEffect(self._blur)
                self._frost_label = lbl
            lbl.setPixmap(mapped)
            lbl.show()
        except Exception:
            pass

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pad = 20
        r = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        # outer background gradient
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0.0, qcol("#3fb0ff", 240))
        grad.setColorAt(1.0, qcol("#1aa0ff", 200))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 20, 20)

        # draw SVG border if available scaled to rect
        if self._svg_renderer and self._svg_renderer.isValid():
            self._svg_renderer.render(p, r)
        else:
            # neon animated border glow layer
            glow = int(150 + 100 * math.sin(self._neon_phase))
            neon_col = qcol(C.PRI, glow)
            pen = QPen(neon_col, 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(4, 4, -4, -4), 18, 18)

        # inner frosted panel: capture background and apply blur
        inner = r.adjusted(12, 12, -12, -12)
        # paint semi-transparent overlay
        p.setBrush(QBrush(qcol("#ffffff", 30)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(inner, 12, 12)

        # compute control icon rects
        ctrl_size = 20
        cx = inner.right() - ctrl_size - 12
        cy = inner.top() + 8
        self._ctrl_rects = {
            "close": QRectF(cx + (ctrl_size + 8) * 2, cy, ctrl_size, ctrl_size),
            "next": QRectF(cx + (ctrl_size + 8), cy, ctrl_size, ctrl_size),
            "prev": QRectF(cx, cy, ctrl_size, ctrl_size),
        }

        # render icons (SVG if loaded) otherwise fallback text
        for name, rect in self._ctrl_rects.items():
            if name == "prev":
                ic = self._icon_prev
            elif name == "next":
                ic = self._icon_next
            else:
                ic = self._icon_close
            if not ic.isNull():
                ic.paint(p, rect.toRect())
            else:
                p.setPen(QPen(qcol(C.WHITE, 200)))
                sym = "<" if name == "prev" else (">" if name == "next" else "✕")
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, sym)

        # Title
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        p.drawText(QRectF(inner.left()+18, inner.top()+22, inner.width()-36, 40), Qt.AlignmentFlag.AlignLeft, self._title)

        # Lines (data-driven)
        p.setFont(QFont("Courier New", 11))
        y = inner.top() + 80
        for ln in self._lines:
            p.setPen(QPen(qcol(C.WHITE, 230), 1))
            p.drawText(QRectF(inner.left()+24, y, inner.width()-48, 26), Qt.AlignmentFlag.AlignLeft, ln)
            y += 34

    def sizeHint(self):
        return QSize(520, 720)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _looks_like_gemini_key(self, key: str) -> bool:
        return key.startswith("AIza") and len(key) >= 20

    def _submit(self):
        key = self._key_input.text().strip()
        if not self._looks_like_gemini_key(key):
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class MicButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._active = True
        self._pulse = 0.0
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._pulse_step)
        self._tmr.start(50)

    def is_active(self) -> bool:
        return self._active

    def set_active(self, v: bool):
        self._active = v
        self.update()

    def _pulse_step(self):
        if self._active:
            self._pulse = min(1.0, self._pulse + 0.08)
        else:
            self._pulse = max(0.0, self._pulse - 0.08)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._active = not self._active
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        r = min(W, H) / 2 - 2

        bg_col = C.GREEN if self._active else C.RED

        # outer glow
        glow_a = int(60 + 40 * self._pulse)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(bg_col, glow_a)))
        p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)

        # main circle
        p.setPen(QPen(qcol(bg_col, 200), 1.5))
        p.setBrush(QBrush(qcol(C.PANEL2, 230)))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # mic icon
        p.setPen(QPen(qcol(bg_col), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # mic body
        mic_w, mic_h = 6, 10
        p.drawRoundedRect(QRectF(cx - mic_w / 2, cy - mic_h / 2 - 2, mic_w, mic_h), 3, 3)
        # mic arc
        arc_r = 9
        p.drawArc(QRectF(cx - arc_r, cy - arc_r + 1, arc_r * 2, arc_r * 2), 0, -180 * 16)
        # mic stand
        p.drawLine(QPointF(cx, cy + arc_r - 1), QPointF(cx, cy + arc_r + 4))
        p.drawLine(QPointF(cx - 4, cy + arc_r + 4), QPointF(cx + 4, cy + arc_r + 4))

        # mute slash
        if not self._active:
            p.setPen(QPen(qcol(C.RED), 2))
            p.drawLine(QPointF(cx - r + 6, cy - r + 6), QPointF(cx + r - 6, cy + r - 6))


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("S.T.E.V.E — MISTAKE IV")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None
        self._animations_enabled = True

        central = QWidget()
        # central widget background; if resources/bg.jpg exists use a QLabel
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        bg_path = BASE_DIR / "resources" / "bg.jpg"
        self._bg_label = None
        self._bg_pix = None
        if bg_path.exists():
            try:
                pix = QPixmap(str(bg_path))
                if not pix.isNull():
                    self._bg_pix = pix
                    from PyQt6.QtWidgets import QLabel
                    lbl = QLabel(central)
                    lbl.setScaledContents(False)
                    lbl.setPixmap(pix)
                    lbl.setGeometry(0, 0, central.width(), central.height())
                    lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    lbl.lower()
                    self._bg_label = lbl
                    central.installEventFilter(self)
            except Exception:
                self._bg_label = None

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._clock_widget = OrbitalClockWidget(central)
        self._clock_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._clock_widget.show()
        self._clock_widget.raise_()

        self._mic_btn = MicButton(central)
        self._mic_btn.clicked.connect(self._toggle_mute)
        self._mic_btn.show()
        self._mic_btn.raise_()

        self._stat_cpu = CircularStatWidget("CPU", C.PRI)
        self._stat_mem = CircularStatWidget("RAM", C.ACC2)
        self._stat_net = CircularStatWidget("NET", C.GREEN)
        self._stat_gpu = CircularStatWidget("GPU", C.ACC)
        self._stat_tmp = CircularStatWidget("TMP", "#ff6688")
        self._stat_up  = CircularStatWidget("UP", C.GREEN)

        self._hud_stats = [
            self._stat_cpu, self._stat_mem, self._stat_net,
            self._stat_gpu, self._stat_tmp, self._stat_up,
        ]
        for w in self._hud_stats:
            w.setParent(central)
            w.show()
            w.raise_()

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        # ensure HUD follows initial animations setting
        self.hud.set_animations_enabled(self._animations_enabled)
        self._position_clock_widget()
        self._position_mic_button()
        self._position_hud_stats()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        self._position_clock_widget()
        self._position_mic_button()
        self._position_hud_stats()

    def _position_clock_widget(self):
        if not hasattr(self, "_clock_widget") or not self._clock_widget:
            return
        hud = self.hud
        if not hud:
            return
        size = self._clock_widget.sizeHint()
        hud_cx = hud.x() + hud.width() / 2
        hud_cy = hud.y() + hud.height() / 2
        hud_r = min(hud.width(), hud.height()) / 2
        angle_rad = math.radians(25)
        x = hud_cx + hud_r * 1.40 * math.cos(angle_rad) - size.width() / 2
        y = hud_cy - hud_r * 1.40 * math.sin(angle_rad) - size.height() / 2
        self._clock_widget.setGeometry(int(x), int(y), size.width(), size.height())
        self._clock_widget.show()
        self._clock_widget.raise_()

    def _position_mic_button(self):
        if not hasattr(self, "_mic_btn") or not self._mic_btn:
            return
        hud = self.hud
        if not hud:
            return
        size = self._mic_btn.size()
        hud_cx = hud.x() + hud.width() / 2
        hud_cy = hud.y() + hud.height() / 2
        hud_r = min(hud.width(), hud.height()) / 2
        angle_rad = math.radians(-25)
        x = hud_cx + hud_r * 1.50 * math.cos(angle_rad) - size.width() / 2
        y = hud_cy - hud_r * 1.50 * math.sin(angle_rad) - size.height() / 2
        self._mic_btn.move(int(x), int(y))
        self._mic_btn.show()
        self._mic_btn.raise_()

    def _position_hud_stats(self):
        if not hasattr(self, "_hud_stats"):
            return
        cw = self.centralWidget()
        if not cw:
            return
        hud = self.hud
        cx = hud.x() + hud.width() / 2
        cy = hud.y() + hud.height() / 2
        hud_r = min(hud.width(), hud.height()) / 2
        stat_r = hud_r * 1.10
        n = len(self._hud_stats)
        arc_start = 225
        arc_end = 135
        step = (arc_start - arc_end) / max(n - 1, 1)
        for i, widget in enumerate(self._hud_stats):
            angle_deg = arc_start - i * step
            angle_rad = math.radians(angle_deg)
            x = cx + stat_r * math.cos(angle_rad) - widget.width() / 2
            y = cy + stat_r * math.sin(angle_rad) - widget.height() / 2
            widget.move(int(x), int(y))

    def eventFilter(self, obj, event):
        # update background pixmap scaling when central widget resizes
        try:
            if obj is self.centralWidget() and event.type() == QEvent.Type.Resize:
                if self._bg_label and self._bg_pix:
                    cw = self.centralWidget()
                    w, h = cw.width(), cw.height()
                    # scale preserving aspect ratio and cover behavior
                    sp = self._bg_pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    self._bg_label.setPixmap(sp)
                    self._bg_label.setGeometry(0, 0, w, h)
                    # re-capture blur for overlays if present
                    if getattr(self, "_scenario_overlay", None):
                        try:
                            self._scenario_overlay.capture_background_and_blur()
                        except Exception:
                            pass
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _update_metrics(self):
        snap = _metrics.snapshot()

        cpu = snap["cpu"]
        self._stat_cpu.set_value(cpu, f"{cpu:.0f}%")

        mem = snap["mem"]
        self._stat_mem.set_value(mem, f"{mem:.0f}%")

        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)
        self._stat_net.set_value(net_pct, net_str)

        gpu = snap["gpu"]
        if gpu >= 0:
            self._stat_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._stat_gpu.set_value(0, "N/A")

        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._stat_tmp.set_value(tmp_pct, f"{tmp:.0f}°")
        else:
            self._stat_tmp.set_value(0, "N/A")

        try:
            boot_t = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._stat_up.set_value(0, f"{h:02d}:{m:02d}")
        except Exception:
            self._stat_up.set_value(0, "--:--")

        try:
            proc_count = len(psutil.pids())
            os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
            self._stat_up.set_extra([f"PROC  {proc_count}", f"OS  {os_name}"])
        except Exception:
            self._stat_up.set_extra([])


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(84)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MISTAKE IV", C.PRI_DIM))
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        title = QLabel("S.T.E.V.E")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("Stupid Technology for Everyday Virtual Errands")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()
        return w

    def _tick_clock(self):
        self._clock_widget.set_time(
            time.strftime("%H:%M:%S"),
            time.strftime("%a"),
            time.strftime("%d %b %Y"),
        )

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setMaximumWidth(_RIGHT_W)
        w.setMinimumWidth(48)
        w.setStyleSheet(
            f"background: rgba(6,18,28,0.68); border-left: 1px solid rgba(15,64,96,0.18);"
        )
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        lay.addSpacing(4)

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute"))
        # animation toggle
        self._anim_btn = QPushButton("ANIM: ON")
        self._anim_btn.setFixedHeight(18)
        self._anim_btn.setFixedWidth(78)
        self._anim_btn.setFont(QFont("Courier New", 7))
        self._anim_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim_btn.setStyleSheet(f"background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 3px;")
        self._anim_btn.clicked.connect(self._toggle_animations)
        lay.addWidget(self._anim_btn)
        lay.addStretch()
        lay.addWidget(_fl("  ·  MISTAKE IV  ·  "))
        lay.addStretch()
        return w

    def _toggle_animations(self):
        self._animations_enabled = not getattr(self, "_animations_enabled", True)
        self.hud.set_animations_enabled(self._animations_enabled)
        self._anim_btn.setText("ANIM: ON" if self._animations_enabled else "ANIM: OFF")

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell STEVE what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        self._mic_btn.set_active(not self._muted)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. STEVE online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class SteveUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)
        # preview shortcut for scenario overlay (Ctrl+Alt+S)
        try:
            sc = QShortcut(QKeySequence("Ctrl+Alt+S"), self._win)
            sc.activated.connect(self._toggle_scenario_preview)
        except Exception:
            pass

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def _toggle_scenario_preview(self):
        # try to load scenarios data from config/scenarios.json
        lines = []
        title = "<SCENARIO>"
        try:
            sfile = CONFIG_DIR / "scenarios.json"
            if sfile.exists():
                data = json.loads(sfile.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    first = data[0]
                    title = first.get("title", title)
                    lines = list(first.get("lines", []))
                else:
                    data = []
        except Exception:
            lines = [
                "CATEGORY: MAIN",
                "DIFFICULTY: F",
                "CLEAR CONDITION: KILL ONE OR MORE LIVING THINGS",
                "TIME LIMIT: 30 MINUTES",
                "REWARDS: 300 COINS",
                "PENALTY FOR FAILURE: DEATH",
            ]
        mw = self._win
        if getattr(mw, "_scenario_overlay", None) and mw._scenario_overlay.isVisible():
            mw._scenario_overlay.hide()
            mw._scenario_overlay.deleteLater()
            mw._scenario_overlay = None
            return
        # try to load SVG assets from resources folder if present
        svg_border = None
        resources_dir = BASE_DIR / "resources"
        if resources_dir.exists():
            b = resources_dir / "scenario_border.svg"
            prev_svg = resources_dir / "prev.svg"
            next_svg = resources_dir / "next.svg"
            close_svg = resources_dir / "close.svg"
            if b.exists(): svg_border = str(b)
        # pass full data list so the card can flip between entries
        ov = ScenarioCard(title, lines, parent=mw.centralWidget(), svg_path=svg_border, scenarios=(data if isinstance(data, list) else []), start_index=0)
        # load icons if available
        try:
            if resources_dir.exists():
                ov.load_icons_from_svgs(str(prev_svg), str(next_svg), str(close_svg))
        except Exception:
            pass
        cw = mw.centralWidget()
        sw, sh = ov.sizeHint().width(), ov.sizeHint().height()
        ov.setGeometry((cw.width()-sw)//2, (cw.height()-sh)//2, sw, sh)
        ov.show()
        # capture background and apply blur to inner area for frosted effect
        try:
            ov.capture_background_and_blur()
        except Exception:
            pass
        mw._scenario_overlay = ov
