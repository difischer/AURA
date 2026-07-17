"""
gui.py
Aura Cast graphical interface.

Features:
- Name edited with a field + ✓ button (or Enter); no audio re-decode per keystroke.
- Left panel with tabs (People / Settings / Output) and scroll.
- "Avatar grows while speaking" toggle (progressive, up to a maximum).
- Presets menu (save/load/manage the "look").
- Base People menu (save image+crop+name without audio; add later assigning audio).
- Language selector (English / Español).
- "Save as default" writes config.json next to the software.

Preview updates are incremental: renaming, recoloring or moving does NOT re-read
the audio; that only happens when audio changes or an envelope parameter does.

Run:  python gui.py

Author: Diego Fischer - Rocaroja Podcast
License: CC BY 4.0.
"""

from __future__ import annotations

import os
import threading
import time

import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox, simpledialog

from PIL import Image, ImageTk

import aura_cast as ac
import multiprocessing


# Translation from english to spanish, english word is key for the dict
CURRENT_LANG = "en"

TRANSLATIONS = {
    "es": {
        # tabs / main
        "People": "Personas",
        "Settings": "Ajustes",
        "Output": "Salida",
        "+ Add person (image + audio)": "+ Agregar persona (imagen + audio)",
        "Add from library…": "Agregar desde biblioteca…",
        "⏵ Render video": "⏵ Renderizar video",
        "Preview frame": "Frame de preview",
        "Add people to see the preview": "Agrega personas para ver el preview",
        # menu
        "File": "Archivo",
        "Load config…": "Cargar config…",
        "Save config…": "Guardar config…",
        "Save as default": "Guardar como predeterminado",
        "Presets": "Presets",
        "Save current preset…": "Guardar preset actual…",
        "(no presets)": "(sin presets)",
        "Load": "Cargar",
        "Delete": "Borrar",
        "Base People": "Personas base",
        "Create base person (from image)…": "Crear persona base (desde imagen)…",
        "Manage library…": "Gestionar biblioteca…",
        "(library empty)": "(biblioteca vacía)",
        # settings
        "People background": "Fondo de las personas",
        "Darken background": "Oscurecer fondo",
        "Background saturation": "Saturación fondo",
        "Avatar": "Avatar",
        "Avatar size": "Tamaño avatar",
        "Avatar grows while speaking": "El avatar crece al hablar",
        "Max avatar growth": "Crecimiento máx. avatar",
        "Growth mode": "Modo de crecimiento",
        "React to volume": "Reacciona al volumen",
        "Grow once while speaking": "Crece una vez al hablar",
        "Tile border": "Borde del tile",
        "Border glows while speaking": "El borde se ilumina al hablar",
        "Audio (envelope)": "Audio (envolvente)",
        "Voice gate (silence threshold)": "Umbral de voz (silencio)",
        "Aura": "Aura",
        "Aura enabled": "Aura activada",
        "Ring sensitivity": "Sensibilidad anillos",
        "Ring spacing": "Sep. anillos",
        "Aura expansion": "Expansión aura",
        "Release (inertia)": "Release (inercia)",
        "Waveform": "Onda",
        "Waveform enabled": "Onda activada",
        "Waveform height": "Alto onda",
        "Waveform bars": "Barras onda",
        "Wave style": "Estilo de onda",
        "Line thickness": "Grosor de línea",
        "Idle motion": "Movimiento en silencio",
        "Bars (loudness)": "Barras (volumen)",
        "Line (oscilloscope)": "Línea (osciloscopio)",
        "Mirror": "Espejo",
        "Filled + gradient": "Relleno + degradado",
        "Dots": "Puntos",
        "Radial": "Radial",
        "elapsed": "transcurrido",
        "remaining": "restante",
        "Name": "Nombre",
        "Name enabled": "Nombre activado",
        "Position": "Posición",
        "Move name ↔ (x)": "Mover nombre ↔ (x)",
        "Move name ↕ (y)": "Mover nombre ↕ (y)",
        "Name box opacity": "Opacidad caja nombre",
        "Name size": "Tamaño del nombre",
        "Layout (tiles)": "Distribución (tiles)",
        "Horizontal spacing": "Separación horizontal",
        "Vertical spacing": "Separación vertical",
        "Tile height": "Alto de los tiles",
        "Margin": "Margen",
        "Bottom safe zone (YouTube)": "Zona segura inferior (YouTube)",
        # output
        "Output format": "Formato de salida",
        "(mov and webm keep transparency)": "(mov y webm conservan transparencia)",
        "Transparent background": "Fondo transparente",
        "Embed audio (mix of tracks)": "Incrustar audio (mezcla de pistas)",
        "Delete intermediate PNGs when done": "Borrar PNG intermedios al terminar",
        "Cores to use (detected: {n})": "Cores a usar (detectados: {n})",
        "auto (recommended)": "auto (recomendado)",
        "all": "todos",
        "(1 core available: 1 process will be used)":
            "(1 core disponible: se usará 1 proceso)",
        "Resolution (px)": "Resolución (px)",
        "Width": "Ancho",
        "Height": "Alto",
        "Language": "Idioma",
        # dialogs
        "Circular crop": "Recorte circular",
        "Zoom": "Zoom",
        "Center": "Centrar",
        "OK": "Aceptar",
        "New base person": "Nueva persona base",
        "Image": "Imagen",
        "Save to library": "Guardar en biblioteca",
        "Base people library": "Biblioteca de personas base",
        "Add to render": "Agregar al render",
        "Close": "Cerrar",
        # card
        "⚠ no audio": "⚠ sin audio",
        "Audio": "Audio",
        # file dialog titles
        "Person image": "Imagen de la persona",
        "Audio for that person": "Audio de esa persona",
        "Audio for {name}": "Audio para {name}",
        "Output folder": "Carpeta de salida",
        "Save video as": "Guardar video como",
        # messages
        "Missing audio": "Falta audio",
        "Each person needs their own audio track.":
            "Cada persona necesita su pista de audio.",
        "Assign an audio track.": "Asigna una pista de audio.",
        "No people": "Sin personas",
        "Add at least one person.": "Agrega al menos una persona.",
        "Some people have no audio track assigned.":
            "Hay personas sin pista de audio asignada.",
        "Rendering…": "Renderizando…",
        "Rendering… {done}/{total}": "Renderizando… {done}/{total}",
        "Done": "Listo",
        "Done: {out}": "Listo: {out}",
        "Save preset": "Guardar preset",
        "Preset name:": "Nombre del preset:",
        "Preset “{name}” saved": "Preset “{name}” guardado",
        "Preset “{name}” loaded": "Preset “{name}” cargado",
        "Saved: {f}": "Guardado: {f}",
        "Default settings saved (config.json)":
            "Ajustes predeterminados guardados (config.json)",
        "“{name}” saved as base person": "“{name}” guardada como persona base",
        "Base person “{name}” created": "Persona base “{name}” creada",
        "Error": "Error",
    }
}


def t(s):
    """Translate a UI string to the current language (English is the key)."""
    return TRANSLATIONS.get(CURRENT_LANG, {}).get(s, s)


def img_types():
    return [(t("Image") + "s", "*.png *.jpg *.jpeg *.webp *.bmp")]


AUDIO_TYPES = [("Audio", "*.wav *.mp3 *.flac *.m4a *.ogg *.aac")]

# parameters whose change forces recomputing the audio envelope
ENV_PARAMS = {("aura", "release"), ("aura", "attack"), ("audio", "gate"),
              ("audio", "window_ms")}

class Scrollable(ttk.Frame):
    """Vertically scrollable frame. Add children to .inner."""

    def __init__(self, master, width=380, height=420):
        super().__init__(master)
        self.canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self._bind_wheel())
        self.canvas.bind("<Leave>", lambda e: self._unbind_wheel())

    def _bind_wheel(self):
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)

    def _unbind_wheel(self):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _wheel(self, e):
        step = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1
        self.canvas.yview_scroll(step, "units")


class CropDialog(tk.Toplevel):
    """Circular crop for images of participants"""
    BOX = 420

    def __init__(self, master, path, crop=None):
        super().__init__(master)
        self.title(t("Circular crop"))
        self.transient(master)
        self.grab_set()
        self.result = None
        self.path = path
        self.img = Image.open(path).convert("RGBA")
        self.crop = dict(crop or {"zoom": 1.0, "ox": 0.0, "oy": 0.0})

        self.disp = self.img.copy()
        self.disp.thumbnail((self.BOX, self.BOX))
        self.scale = self.disp.width / self.img.width

        self.cv = tk.Canvas(self, width=self.disp.width, height=self.disp.height,
                            highlightthickness=0, bg="#111")
        self.cv.grid(row=0, column=0, padx=8, pady=8)
        self.prev = tk.Label(self, bg="#111")
        self.prev.grid(row=0, column=1, padx=8)

        ttk.Label(self, text=t("Zoom")).grid(row=1, column=0, sticky="w", padx=8)
        self.zv = tk.DoubleVar(value=self.crop["zoom"])
        ttk.Scale(self, from_=1.0, to=5.0, variable=self.zv,
                  command=lambda *_: self.redraw()).grid(row=2, column=0, sticky="ew", padx=8)

        bar = ttk.Frame(self)
        bar.grid(row=2, column=1, padx=8, sticky="e")
        ttk.Button(bar, text=t("Center"), command=self.reset).pack(side="left", padx=2)
        ttk.Button(bar, text=t("OK"), command=self.ok).pack(side="left", padx=2)

        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<MouseWheel>", self.wheel)
        self.cv.bind("<Button-4>", self.wheel)
        self.cv.bind("<Button-5>", self.wheel)
        self._last = (0, 0)
        self.redraw()

    def reset(self):
        self.crop = {"zoom": 1.0, "ox": 0.0, "oy": 0.0}
        self.zv.set(1.0)
        self.redraw()

    def press(self, e):
        self._last = (e.x, e.y)

    def drag(self, e):
        dx, dy = e.x - self._last[0], e.y - self._last[1]
        self._last = (e.x, e.y)
        self.crop["ox"] -= dx / (self.img.width * self.scale)
        self.crop["oy"] -= dy / (self.img.height * self.scale)
        self.redraw()

    def wheel(self, e):
        up = getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4
        self.zv.set(min(5.0, max(1.0, self.zv.get() + (0.1 if up else -0.1))))
        self.redraw()

    def redraw(self):
        self.crop["zoom"] = float(self.zv.get())
        W, H = self.img.size
        side = min(W, H) / self.crop["zoom"]
        cx = min(max(W / 2 + self.crop["ox"] * W, side / 2), W - side / 2)
        cy = min(max(H / 2 + self.crop["oy"] * H, side / 2), H - side / 2)
        self.crop["ox"], self.crop["oy"] = (cx - W / 2) / W, (cy - H / 2) / H

        self._tk = ImageTk.PhotoImage(self.disp)
        self.cv.delete("all")
        self.cv.create_image(0, 0, anchor="nw", image=self._tk)
        r = (side / 2) * self.scale
        dx, dy = cx * self.scale, cy * self.scale
        self.cv.create_oval(dx - r, dy - r, dx + r, dy + r, outline="#23A55A", width=2)

        av = ac.circular_avatar(self.path, 180, self.crop)
        bg = Image.new("RGBA", av.size, (17, 17, 17, 255))
        bg.alpha_composite(av)
        self._tkp = ImageTk.PhotoImage(bg)
        self.prev.configure(image=self._tkp)

    def ok(self):
        self.result = self.crop
        self.destroy()

# #########################################################
# ####################  BASE PERSON ######################
# #########################################################

# This are the persons that he program have saved as base/preset for repeated
# participants or hosts

class NewBasePersonDialog(tk.Toplevel):
    """Create a base person: image + crop + name (without audio)."""

    def __init__(self, master):
        super().__init__(master)
        self.title(t("New base person"))
        self.transient(master)
        self.grab_set()
        self.result = None

        f = filedialog.askopenfilename(parent=self, title=t("Image"), filetypes=img_types())
        if not f:
            self.destroy()
            return
        self.image = f
        crop = CropDialog(self, f)
        self.wait_window(crop)
        self.crop = crop.result or {"zoom": 1.0, "ox": 0.0, "oy": 0.0}

        av = ac.circular_avatar(f, 96, self.crop)
        bg = Image.new("RGBA", av.size, (17, 17, 17, 255))
        bg.alpha_composite(av)
        self._thumb = ImageTk.PhotoImage(bg)
        ttk.Label(self, image=self._thumb).grid(row=0, column=0, padx=10, pady=10)

        box = ttk.Frame(self)
        box.grid(row=0, column=1, padx=10)
        ttk.Label(box, text=t("Name")).pack(anchor="w")
        self.name = tk.StringVar(value=os.path.splitext(os.path.basename(f))[0])
        ttk.Entry(box, textvariable=self.name, width=22).pack()
        ttk.Button(box, text=t("Save to library"), command=self.ok).pack(pady=8)

    def ok(self):
        self.result = {
            "name": self.name.get(),
            "image": self.image,
            "crop": self.crop,
            "color": "",
            "aura_color": ac.DEFAULTS["aura"]["color"],
        }
        self.destroy()


# #########################################################
# #################### LIBRARY MANAGER ####################
# #########################################################

class ManagePeopleDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.title(t("Base people library"))
        self.transient(master)
        self.grab_set()
        self.app = app
        self._refresh()

    def _refresh(self):
        for w in self.winfo_children():
            w.destroy()
        people = ac.load_base_people()
        if not people:
            ttk.Label(self, text=t("(library empty)")).pack(padx=20, pady=20)
        for person in people:
            row = ttk.Frame(self, padding=4)
            row.pack(fill="x")
            try:
                av = ac.circular_avatar(person["image"], 40, person.get("crop"))
                bg = Image.new("RGBA", av.size, (17, 17, 17, 255))
                bg.alpha_composite(av)
                ph = ImageTk.PhotoImage(bg)
                lbl = ttk.Label(row, image=ph)
                lbl.image = ph
                lbl.pack(side="left", padx=4)
            except Exception:  # noqa: BLE001
                pass
            ttk.Label(row, text=person["name"], width=20).pack(side="left")
            ttk.Button(row, text=t("Add to render"),
                       command=lambda p=person: (self.app.add_from_base(p))).pack(side="left", padx=2)
            ttk.Button(row, text=t("Delete"),
                       command=lambda p=person: self._delete(p["name"])).pack(side="left", padx=2)
        ttk.Button(self, text=t("Close"), command=self.destroy).pack(pady=6)

    def _delete(self, name):
        ac.delete_base_person(name)
        self.app.rebuild_people_menu()
        self._refresh()


# #####################################################
# #################### PERSON CARD ####################
# #####################################################

class PersonCard(ttk.Frame):
    def __init__(self, master, app, idx):
        super().__init__(master, padding=6, relief="groove")
        self.app, self.idx = app, idx
        p = app.cfg["participants"][idx]

        av = ac.circular_avatar(p["image"], 52, p.get("crop"))
        bg = Image.new("RGBA", av.size, ac.hex_rgba(p.get("color") or "#000000"))
        bg.alpha_composite(av)
        self._thumb = ImageTk.PhotoImage(bg)
        ttk.Label(self, image=self._thumb).grid(row=0, column=0, rowspan=2, padx=(0, 8))

        namebar = ttk.Frame(self)
        namebar.grid(row=0, column=1, sticky="w")
        self.name = tk.StringVar(value=p["name"])
        entry = ttk.Entry(namebar, textvariable=self.name, width=16)
        entry.pack(side="left")
        entry.bind("<Return>", lambda e: self.commit_name())
        entry.bind("<FocusOut>", lambda e: self.commit_name())
        ttk.Button(namebar, text="✓", width=2, command=self.commit_name).pack(side="left", padx=(2, 0))

        audio_lbl = os.path.basename(p["audio"]) if p.get("audio") else t("⚠ no audio")
        ttk.Label(self, text=audio_lbl, foreground="#888").grid(row=1, column=1, sticky="w")

        btns = ttk.Frame(self)
        btns.grid(row=0, column=2, rowspan=2, padx=4)
        rowA = ttk.Frame(btns); rowA.pack()
        rowB = ttk.Frame(btns); rowB.pack()
        for parent, items in [
            (rowA, [("▲", self.up), ("▼", self.down), ("✂", self.crop), ("★", self.save_base)]),
            (rowB, [("🎨", self.tile_color), ("◎", self.aura_color), ("♪", self.audio), ("✕", self.remove)]),
        ]:
            for txt, cmd in items:
                ttk.Button(parent, text=txt, width=3, command=cmd).pack(side="left")

        sw = ttk.Frame(self)
        sw.grid(row=0, column=3, rowspan=2, padx=4)
        tk.Label(sw, width=2, bg=p.get("color") or "#000000", relief="solid", bd=1).pack(pady=1)
        tk.Label(sw, width=2, bg=p.get("aura_color") or "#23A55A", relief="solid", bd=1).pack(pady=1)

    def P(self):
        return self.app.cfg["participants"][self.idx]

    def commit_name(self):
        self.app.update_name(self.idx, self.name.get())

    def up(self):
        self.app.move(self.idx, -1)

    def down(self):
        self.app.move(self.idx, +1)

    def remove(self):
        self.app.remove_person(self.idx)

    def crop(self):
        d = CropDialog(self.app, self.P()["image"], self.P().get("crop"))
        self.app.wait_window(d)
        if d.result:
            self.app.update_crop(self.idx, d.result)

    def tile_color(self):
        c = colorchooser.askcolor(initialcolor=self.P().get("color") or "#000000")[1]
        if c:
            self.app.update_tile_color(self.idx, c)

    def aura_color(self):
        c = colorchooser.askcolor(initialcolor=self.P().get("aura_color") or "#23A55A")[1]
        if c:
            self.app.update_aura_color(self.idx, c)

    def audio(self):
        f = filedialog.askopenfilename(title=t("Audio"), filetypes=AUDIO_TYPES)
        if f:
            self.app.update_audio(self.idx, f)

    def save_base(self):
        self.app.save_person_as_base(self.idx)


# #############################################
# #################### APP ####################
# #############################################
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        global CURRENT_LANG
        self.title("Aura Cast")
        self.geometry("1480x900")
        self.minsize(1200, 780)
        self.cfg = ac.load_config()
        CURRENT_LANG = self.cfg.get("ui_language", "en")
        self.lang = CURRENT_LANG
        self.parts = []
        self.preview_img = None
        self._rendering = False
        self.vars = {}

        self._build_menu()
        self._build_body()

        self.refresh_list()
        self.refresh()
        self.after(150, self.refresh)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ******************** language config ********************
    def set_language(self, code):
        global CURRENT_LANG
        if code == self.lang:
            return
        self.sync()                       # capture current slider values first
        self.lang = code
        CURRENT_LANG = code
        self.cfg["ui_language"] = code
        try:
            ac.save_config(self.cfg)      # remember the choice
        except Exception:  # noqa: BLE001
            pass
        # rebuild the whole UI in the new language
        self.left.destroy()
        self.right.destroy()
        self.vars = {}
        self._build_menu()
        self._build_body()
        self.refresh_list()
        self.refresh()

    def _on_close(self):
        try:
            self.sync()
            ac.save_config(self.cfg)
        except Exception:  # noqa: BLE001
            pass
        self.destroy()

    # ******************** body ********************
    def _build_body(self):
        self.left = ttk.Frame(self, padding=6)
        self.left.pack(side="left", fill="y")
        nb = ttk.Notebook(self.left)
        nb.pack(fill="both", expand=True)

        # People tab
        tab_p = ttk.Frame(nb)
        nb.add(tab_p, text=t("People"))
        ttk.Button(tab_p, text=t("+ Add person (image + audio)"),
                   command=self.add).pack(fill="x", pady=4)
        sf = Scrollable(tab_p, width=380, height=600)
        sf.pack(fill="both", expand=True)
        self.list_frame = sf.inner
        ttk.Button(tab_p, text=t("Add from library…"),
                   command=lambda: ManagePeopleDialog(self, self)).pack(fill="x", pady=4)

        # Settings tab
        tab_s = ttk.Frame(nb)
        nb.add(tab_s, text=t("Settings"))
        sset = Scrollable(tab_s, width=380, height=640)
        sset.pack(fill="both", expand=True)
        self._build_params(sset.inner)

        # Output tab
        tab_o = ttk.Frame(nb)
        nb.add(tab_o, text=t("Output"))
        self._build_output(tab_o)

        # always-visible bottom bar
        bottom = ttk.Frame(self.left)
        bottom.pack(fill="x", pady=(6, 0))
        ttk.Button(bottom, text=t("⏵ Render video"), command=self.render).pack(fill="x")
        self.status = ttk.Label(bottom, text="", foreground="#2a2")
        self.status.pack(anchor="w")

        # right panel: preview
        self.right = ttk.Frame(self, padding=8)
        self.right.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Label(self.right, bg="#202020")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        fr = ttk.Frame(self.right)
        fr.pack(fill="x")
        ttk.Label(fr, text=t("Preview frame")).pack(side="left")
        self.fv = tk.IntVar(value=0)
        ttk.Scale(fr, from_=0, to=300, variable=self.fv,
                  command=lambda *_: self.refresh()).pack(side="left", fill="x", expand=True)

    def _preview_size(self):
        """Available preview area; falls back to a default before layout runs."""
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50:
            return (1040, 620)
        return (max(200, w - 6), max(150, h - 6))

    def _on_canvas_resize(self, e):
        """Re-render the preview to fill the panel when the window resizes."""
        size = (e.width, e.height)
        if size == getattr(self, "_last_canvas_size", None):
            return
        self._last_canvas_size = size
        if getattr(self, "_resize_job", None):
            try:
                self.after_cancel(self._resize_job)
            except Exception:  # noqa: BLE001
                pass
        self._resize_job = self.after(120, self.refresh)

    # ******************** menu ********************
    def _build_menu(self):
        menubar = tk.Menu(self)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label=t("Load config…"), command=self.load_cfg)
        m_file.add_command(label=t("Save config…"), command=self.save_cfg)
        m_file.add_command(label=t("Save as default"), command=self.save_default)
        menubar.add_cascade(label=t("File"), menu=m_file)

        self.m_presets = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=t("Presets"), menu=self.m_presets)
        self.rebuild_presets_menu()

        self.m_people = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=t("Base People"), menu=self.m_people)
        self.rebuild_people_menu()

        m_lang = tk.Menu(menubar, tearoff=0)
        m_lang.add_command(label="English", command=lambda: self.set_language("en"))
        m_lang.add_command(label="Español", command=lambda: self.set_language("es"))
        menubar.add_cascade(label=t("Language"), menu=m_lang)

        self.m_about = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=t("About"), menu=self.m_about)
        self.rebuild_people_menu()

        self.config(menu=menubar)

    def rebuild_presets_menu(self):
        m = self.m_presets
        m.delete(0, "end")
        m.add_command(label=t("Save current preset…"), command=self.save_preset_dialog)
        m.add_separator()
        presets = ac.list_presets()
        if not presets:
            m.add_command(label=t("(no presets)"), state="disabled")
        for name in presets:
            sub = tk.Menu(m, tearoff=0)
            sub.add_command(label=t("Load"), command=lambda n=name: self.load_preset(n))
            sub.add_command(label=t("Delete"),
                            command=lambda n=name: (ac.delete_preset(n), self.rebuild_presets_menu()))
            m.add_cascade(label=name, menu=sub)

    def rebuild_people_menu(self):
        m = self.m_people
        m.delete(0, "end")
        m.add_command(label=t("Create base person (from image)…"), command=self.new_base_person)
        m.add_command(label=t("Manage library…"),
                      command=lambda: ManagePeopleDialog(self, self))
        m.add_separator()
        people = ac.load_base_people()
        if not people:
            m.add_command(label=t("(library empty)"), state="disabled")
        for person in people:
            m.add_command(label=f"+ {person['name']}",
                          command=lambda p=person: self.add_from_base(p))

    @staticmethod
    def _fmt_num(v, is_int):
        """Compact numeric readout: ints as ints, floats without trailing zeros."""
        if is_int:
            return str(int(round(float(v))))
        s = f"{float(v):.4f}".rstrip("0").rstrip(".")
        return s if s else "0"

    def _apply_popmode(self):
        self.cfg["tile"]["avatar_pop_mode"] = self._popmode_opts.get(
            self.v_popmode.get(), "reactive")
        self.refresh(clear_base=True)

    def _apply_wavestyle(self):
        self.cfg["wave"]["style"] = self._wavestyle_opts.get(self.v_wavestyle.get(), "bars")
        self.refresh(clear_base=True)

    # ******************** parameters ********************
    def _build_params(self, parent):
        ttk.Label(parent, text=t("People background"), font=("", 10, "bold")).pack(anchor="w", pady=(4, 0))
        self.mode = tk.StringVar(value=self.cfg["tile"]["color_mode"])
        ttk.Combobox(parent, textvariable=self.mode, state="readonly",
                     values=["edge", "dominant", "average", "manual"]).pack(fill="x")
        self.mode.trace_add("write", lambda *_: self.recompute_colors())

        def slider(label, path, lo, hi):
            cur = self.cfg[path[0]][path[1]]
            is_int = isinstance(cur, int) and not isinstance(cur, bool)
            var = (tk.IntVar if is_int else tk.DoubleVar)(value=cur)
            self.vars[path] = var
            rebuild = path in ENV_PARAMS
            recolor = path in {("tile", "color_darken"), ("tile", "color_sat")}

            # label on the left, current value (editable) on the right
            head = ttk.Frame(parent)
            head.pack(fill="x", pady=(6, 0))
            ttk.Label(head, text=label).pack(side="left")
            txt = tk.StringVar(value=self._fmt_num(cur, is_int))
            ent = ttk.Entry(head, textvariable=txt, width=7, justify="right")
            ent.pack(side="right")
            # keep the readout in sync with the slider (and with preset/config loads)
            var.trace_add("write", lambda *_: txt.set(self._fmt_num(var.get(), is_int)))

            def apply_change():
                if recolor:
                    self.recompute_colors()
                else:
                    self.refresh(rebuild=rebuild, clear_base=not rebuild)

            def on_type(*_):
                try:
                    val = float(txt.get().replace(",", "."))
                except ValueError:
                    txt.set(self._fmt_num(var.get(), is_int))
                    return
                val = max(lo, min(hi, val))         # clamp to the slider range
                var.set(int(round(val)) if is_int else round(val, 4))
                apply_change()
            ent.bind("<Return>", on_type)
            ent.bind("<FocusOut>", on_type)

            ttk.Scale(parent, from_=lo, to=hi, variable=var,
                      command=lambda *_: apply_change()).pack(fill="x")

        def checkbox(label, path):
            var = tk.BooleanVar(value=bool(self.cfg[path[0]][path[1]]))
            self.vars[path] = var
            ttk.Checkbutton(parent, text=label, variable=var,
                            command=lambda: self.refresh(clear_base=True)).pack(anchor="w", pady=(4, 0))

        slider(t("Darken background"), ("tile", "color_darken"), 0.0, 0.6)
        slider(t("Background saturation"), ("tile", "color_sat"), 0.0, 1.5)

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Avatar"), font=("", 10, "bold")).pack(anchor="w")
        slider(t("Avatar size"), ("tile", "avatar_scale"), 0.10, 0.60)
        checkbox(t("Avatar grows while speaking"), ("tile", "avatar_pop"))
        slider(t("Max avatar growth"), ("tile", "avatar_pop_max"), 0.0, 0.5)
        # growth mode: react to volume (pulses) vs grow once while speaking
        ttk.Label(parent, text=t("Growth mode")).pack(anchor="w", pady=(6, 0))
        self._popmode_opts = {t("React to volume"): "reactive",
                              t("Grow once while speaking"): "speaking"}
        cur_mode = self.cfg["tile"].get("avatar_pop_mode", "reactive")
        cur_label = next((k for k, v in self._popmode_opts.items() if v == cur_mode),
                         t("React to volume"))
        self.v_popmode = tk.StringVar(value=cur_label)
        ttk.Combobox(parent, textvariable=self.v_popmode, state="readonly",
                     values=list(self._popmode_opts.keys())).pack(fill="x")
        self.v_popmode.trace_add("write", lambda *_: self._apply_popmode())

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Tile border"), font=("", 10, "bold")).pack(anchor="w")
        checkbox(t("Border glows while speaking"), ("tile", "border_glow"))

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Audio (envelope)"), font=("", 10, "bold")).pack(anchor="w")
        slider(t("Voice gate (silence threshold)"), ("audio", "gate"), 0.0, 0.20)

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Aura"), font=("", 10, "bold")).pack(anchor="w")
        checkbox(t("Aura enabled"), ("aura", "enabled"))
        slider(t("Ring sensitivity"), ("aura", "sensitivity"), 0.3, 3.0)
        slider(t("Ring spacing"), ("aura", "spacing"), 4, 40)
        slider(t("Aura expansion"), ("aura", "expand"), 0, 40)
        slider(t("Release (inertia)"), ("aura", "release"), 0.50, 0.99)

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Waveform"), font=("", 10, "bold")).pack(anchor="w")
        checkbox(t("Waveform enabled"), ("wave", "enabled"))
        ttk.Label(parent, text=t("Wave style")).pack(anchor="w", pady=(6, 0))
        self._wavestyle_opts = {
            t("Bars (loudness)"): "bars",
            t("Line (oscilloscope)"): "line",
            t("Mirror"): "mirror",
            t("Filled + gradient"): "relleno",
            t("Dots"): "puntos",
            t("Radial"): "radial",
        }
        cur_ws = self.cfg["wave"].get("style", "bars")
        self.v_wavestyle = tk.StringVar(value=next(
            (k for k, v in self._wavestyle_opts.items() if v == cur_ws), t("Bars (loudness)")))
        ttk.Combobox(parent, textvariable=self.v_wavestyle, state="readonly",
                     values=list(self._wavestyle_opts.keys())).pack(fill="x")
        self.v_wavestyle.trace_add("write", lambda *_: self._apply_wavestyle())
        slider(t("Waveform height"), ("wave", "height"), 0, 120)
        slider(t("Line thickness"), ("wave", "line_width"), 1, 14)
        slider(t("Idle motion"), ("wave", "idle_motion"), 0.0, 0.5)
        slider(t("Waveform bars"), ("wave", "bars"), 8, 96)

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Name"), font=("", 10, "bold")).pack(anchor="w")
        checkbox(t("Name enabled"), ("name", "enabled"))
        ttk.Label(parent, text=t("Position")).pack(anchor="w", pady=(6, 0))
        self.namepos = tk.StringVar(value=self.cfg["name"].get("position", "bottom-left"))
        ttk.Combobox(parent, textvariable=self.namepos, state="readonly",
                     values=["bottom-left", "bottom-center", "bottom-right",
                             "top-left", "top-center", "top-right"]).pack(fill="x")
        self.namepos.trace_add("write", lambda *_: (
            self.cfg["name"].__setitem__("position", self.namepos.get()),
            self.refresh(clear_base=True)))
        slider(t("Move name ↔ (x)"), ("name", "offset_x"), -300, 300)
        slider(t("Move name ↕ (y)"), ("name", "offset_y"), -300, 300)
        slider(t("Name box opacity"), ("name", "pill_opacity"), 0.0, 1.0)
        slider(t("Name size"), ("name", "font_size"), 12, 48)

        ttk.Separator(parent).pack(fill="x", pady=6)
        ttk.Label(parent, text=t("Layout (tiles)"), font=("", 10, "bold")).pack(anchor="w")
        slider(t("Horizontal spacing"), ("canvas", "gap_x"), 0, 160)
        slider(t("Vertical spacing"), ("canvas", "gap_y"), 0, 160)
        slider(t("Tile height"), ("tile", "tile_height_scale"), 0.4, 1.0)
        slider(t("Margin"), ("canvas", "margin"), 0, 200)
        slider(t("Bottom safe zone (YouTube)"), ("canvas", "safe_bottom"), 0.0, 0.15)

    def _build_output(self, parent):
        parent = ttk.Frame(parent, padding=8)
        parent.pack(fill="both", expand=True)

        ttk.Label(parent, text=t("Output format"), font=("", 10, "bold")).pack(anchor="w")
        self.fmt = tk.StringVar(value=self.cfg["output"]["format"])
        ttk.Combobox(parent, textvariable=self.fmt, state="readonly",
                     values=["mp4", "mov", "webm", "png_sequence"]).pack(fill="x")
        self.fmt.trace_add("write", lambda *_: self.cfg["output"].__setitem__("format", self.fmt.get()))

        ttk.Label(parent, text=t("(mov and webm keep transparency)"),
                  foreground="#888").pack(anchor="w")

        self.v_transparent = tk.BooleanVar(value=self.cfg["canvas"]["transparent"])
        ttk.Checkbutton(parent, text=t("Transparent background"),
                        variable=self.v_transparent,
                        command=lambda: (self.cfg["canvas"].__setitem__("transparent", self.v_transparent.get()),
                                         self.refresh())).pack(anchor="w", pady=(8, 0))

        self.v_mux = tk.BooleanVar(value=self.cfg["output"]["mux_audio"])
        ttk.Checkbutton(parent, text=t("Embed audio (mix of tracks)"),
                        variable=self.v_mux,
                        command=lambda: self.cfg["output"].__setitem__("mux_audio", self.v_mux.get())
                        ).pack(anchor="w", pady=(8, 0))

        self.v_clean = tk.BooleanVar(value=self.cfg["output"]["cleanup_frames"])
        ttk.Checkbutton(parent, text=t("Delete intermediate PNGs when done"),
                        variable=self.v_clean,
                        command=lambda: self.cfg["output"].__setitem__("cleanup_frames", self.v_clean.get())
                        ).pack(anchor="w", pady=(8, 0))

        # core selection (parallel processes)
        ncores = ac.cpu_count_safe()
        ttk.Label(parent, text=t("Cores to use (detected: {n})").format(n=ncores)).pack(anchor="w", pady=(10, 0))
        opts = [t("auto (recommended)"), t("all")] + [str(i) for i in range(1, ncores + 1)]
        cur = str(self.cfg["output"].get("workers", "auto"))
        current_label = {"auto": t("auto (recommended)"), "all": t("all")}.get(cur, cur)
        if current_label not in opts:
            current_label = t("auto (recommended)")
        self.workers = tk.StringVar(value=current_label)
        ttk.Combobox(parent, textvariable=self.workers, state="readonly",
                     values=opts).pack(fill="x")
        self.workers.trace_add("write", lambda *_: self._apply_workers())
        if ncores <= 1:
            ttk.Label(parent, text=t("(1 core available: 1 process will be used)"),
                      foreground="#888").pack(anchor="w")

        ttk.Label(parent, text=t("Resolution (px)")).pack(anchor="w", pady=(10, 0))
        res = ttk.Frame(parent)
        res.pack(anchor="w")
        self.v_w = tk.IntVar(value=self.cfg["canvas"]["width"])
        self.v_h = tk.IntVar(value=self.cfg["canvas"]["height"])
        for lbl, var in [(t("Width"), self.v_w), (t("Height"), self.v_h)]:
            ttk.Label(res, text=lbl).pack(side="left")
            e = ttk.Entry(res, textvariable=var, width=6)
            e.pack(side="left", padx=(2, 8))
            e.bind("<Return>", lambda ev: self.apply_resolution())
            e.bind("<FocusOut>", lambda ev: self.apply_resolution())

        ttk.Label(parent, text="FPS").pack(anchor="w", pady=(6, 0))
        self.v_fps = tk.IntVar(value=self.cfg["canvas"]["fps"])
        e = ttk.Entry(parent, textvariable=self.v_fps, width=6)
        e.pack(anchor="w")
        e.bind("<Return>", lambda ev: self.apply_resolution())
        e.bind("<FocusOut>", lambda ev: self.apply_resolution())

    def apply_resolution(self):
        try:
            self.cfg["canvas"]["width"] = int(self.v_w.get())
            self.cfg["canvas"]["height"] = int(self.v_h.get())
            self.cfg["canvas"]["fps"] = int(self.v_fps.get())
        except (tk.TclError, ValueError):
            return
        self.refresh(rebuild=True)

    def _apply_workers(self):
        label = self.workers.get()
        if label.startswith("auto"):
            self.cfg["output"]["workers"] = "auto"
        elif label in (t("all"), "all", "todos"):
            self.cfg["output"]["workers"] = "all"
        else:
            self.cfg["output"]["workers"] = label

    # ******************** sliders ********************
    def sync(self):
        for (a, b), v in self.vars.items():
            cur = ac.DEFAULTS[a][b]
            try:
                val = v.get()
            except tk.TclError:
                continue
            if isinstance(cur, bool):
                self.cfg[a][b] = bool(val)
            elif isinstance(cur, int):
                self.cfg[a][b] = int(val)
            else:
                self.cfg[a][b] = round(float(val), 4)

    # ******************** participants of video ********************
    def add(self):
        f = filedialog.askopenfilename(title=t("Person image"), filetypes=img_types())
        if not f:
            return
        a = filedialog.askopenfilename(title=t("Audio for that person"), filetypes=AUDIO_TYPES)
        if not a:
            messagebox.showwarning(t("Missing audio"), t("Each person needs their own audio track."))
            return
        dlg = CropDialog(self, f)
        self.wait_window(dlg)
        self._append_participant({
            "name": os.path.splitext(os.path.basename(f))[0],
            "image": f, "audio": a,
            "crop": dlg.result or {"zoom": 1.0, "ox": 0.0, "oy": 0.0},
            "color": self._auto_color(f),
            "aura_color": self.cfg["aura"]["color"],
        })

    def add_from_base(self, person):
        a = filedialog.askopenfilename(
            title=t("Audio for {name}").format(name=person["name"]), filetypes=AUDIO_TYPES)
        if not a:
            messagebox.showwarning(t("Missing audio"), t("Assign an audio track."))
            return
        self._append_participant({
            "name": person["name"], "image": person["image"], "audio": a,
            "crop": person.get("crop", {"zoom": 1.0, "ox": 0.0, "oy": 0.0}),
            "color": person.get("color") or self._auto_color(person["image"]),
            "aura_color": person.get("aura_color") or self.cfg["aura"]["color"],
        })

    def _auto_color(self, image):
        m = self.cfg["tile"]["color_mode"]
        if m == "manual":
            return self.cfg["tile"]["background_color"]
        return ac.tile_color_from_image(image, m, self.cfg["tile"]["color_darken"],
                                        self.cfg["tile"]["color_sat"])

    def _append_participant(self, spec):
        self.cfg["participants"].append(spec)
        self.sync()
        if self.parts:
            self.parts.append(ac.Participant(spec, self.cfg))
        self.refresh_list()
        self.refresh()

    def save_person_as_base(self, idx):
        p = self.P_at(idx)
        person = {"name": p["name"], "image": p["image"], "crop": p.get("crop"),
                  "color": p.get("color", ""), "aura_color": p.get("aura_color", "")}
        ac.add_base_person(person)
        self.rebuild_people_menu()
        self.status.configure(text=t("“{name}” saved as base person").format(name=p["name"]))

    def new_base_person(self):
        d = NewBasePersonDialog(self)
        self.wait_window(d)
        if d.result:
            ac.add_base_person(d.result)
            self.rebuild_people_menu()
            self.status.configure(text=t("Base person “{name}” created").format(name=d.result["name"]))

    def P_at(self, idx):
        return self.cfg["participants"][idx]

    def update_name(self, idx, newname):
        self.P_at(idx)["name"] = newname
        if idx < len(self.parts):                    # without re-decoding audio
            self.parts[idx].name = newname
            self.parts[idx]._base = (None, None)     # invalidate only the cached background
        self.refresh()

    def update_crop(self, idx, crop):
        self.P_at(idx)["crop"] = crop
        if idx < len(self.parts):
            self.parts[idx].crop = crop
            self.parts[idx]._avatar_cache.clear()
            self.parts[idx]._base = (None, None)
        self.refresh_list()
        self.refresh()

    def update_tile_color(self, idx, color):
        self.P_at(idx)["color"] = color
        if idx < len(self.parts):
            self.parts[idx].color = color
            self.parts[idx]._base = (None, None)
        self.refresh_list()
        self.refresh()

    def update_aura_color(self, idx, color):
        self.P_at(idx)["aura_color"] = color
        if idx < len(self.parts):
            self.parts[idx].aura_color = color
        self.refresh_list()
        self.refresh()

    def update_audio(self, idx, audio):
        self.P_at(idx)["audio"] = audio
        self.sync()
        if idx < len(self.parts):                    # rebuild only this person
            self.parts[idx] = ac.Participant(self.P_at(idx), self.cfg)
        self.refresh_list()
        self.refresh()

    def move(self, i, delta):
        j = i + delta
        ps = self.cfg["participants"]
        if 0 <= j < len(ps):
            ps[i], ps[j] = ps[j], ps[i]
            if self.parts and max(i, j) < len(self.parts):
                self.parts[i], self.parts[j] = self.parts[j], self.parts[i]
            self.refresh_list()
            self.refresh()

    def remove_person(self, idx):
        self.cfg["participants"].pop(idx)
        if idx < len(self.parts):
            self.parts.pop(idx)
        self.refresh_list()
        self.refresh()

    def recompute_colors(self):
        self.sync()
        m = self.mode.get()
        self.cfg["tile"]["color_mode"] = m
        for i, spec in enumerate(self.cfg["participants"]):
            col = (self.cfg["tile"]["background_color"] if m == "manual"
                   else ac.tile_color_from_image(spec["image"], m,
                        self.cfg["tile"]["color_darken"], self.cfg["tile"]["color_sat"]))
            spec["color"] = col
            if i < len(self.parts):
                self.parts[i].color = col
                self.parts[i]._base = (None, None)
        self.refresh_list()
        self.refresh()

    def refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        for i in range(len(self.cfg["participants"])):
            PersonCard(self.list_frame, self, i).pack(fill="x", pady=3)

    # ******************** preview refresh ********************
    def refresh(self, rebuild=False, clear_base=False):
        if not self.cfg["participants"]:
            self.canvas.configure(image="", text=t("Add people to see the preview"),
                                  foreground="#aaa")
            self.parts = []
            return
        self.sync()
        if rebuild:
            self.parts = []
        try:
            if not self.parts:
                self.parts = [ac.Participant(s, self.cfg) for s in self.cfg["participants"]]
            elif clear_base:
                for p in self.parts:
                    p._base = (None, None)
            font = ac.get_font(self.cfg)
            img = ac.render_frame(int(self.fv.get()), self.parts, self.cfg, font)
            if self.cfg["canvas"]["transparent"]:
                bg = Image.new("RGBA", img.size, (32, 32, 32, 255))
                bg.alpha_composite(img)
                img = bg
            img = img.convert("RGB")
            img.thumbnail(self._preview_size())
            self.preview_img = ImageTk.PhotoImage(img)
            self.canvas.configure(image=self.preview_img, text="")
        except Exception as e:  # noqa: BLE001
            self.canvas.configure(image="", text=f"Preview: {e}", foreground="#f66")

    def about_dialog(self):
        self.sync()
        messagebox.showinfo(
        title="About", 
        message="Made by: Diego Fischer\n\nLicensed under Creative Commons 4.0 BY (CC BY) International Licence", 
        parent=self
    )

    # ******************** presets and config ********************
    def save_preset_dialog(self):
        self.sync()
        name = simpledialog.askstring(t("Save preset"), t("Preset name:"), parent=self)
        if not name:
            return
        ac.save_preset(name, self.cfg)
        self.rebuild_presets_menu()
        self.status.configure(text=t("Preset “{name}” saved").format(name=name))

    def load_preset(self, name):
        settings = ac.load_preset(name)
        ac.apply_settings(self.cfg, settings)
        self._sync_widgets_from_cfg()
        self.recompute_colors()   # mode/colors may have changed
        self.status.configure(text=t("Preset “{name}” loaded").format(name=name))

    def load_cfg(self):
        f = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if f:
            self.cfg = ac.load_config(f)
            self._sync_widgets_from_cfg()
            self.parts = []
            self.refresh_list()
            self.refresh()

    def save_cfg(self):
        self.sync()
        f = filedialog.asksaveasfilename(defaultextension=".json",
                                         initialfile="config.json",
                                         filetypes=[("JSON", "*.json")])
        if f:
            ac.save_config(self.cfg, f)
            self.status.configure(text=t("Saved: {f}").format(f=os.path.basename(f)))

    def save_default(self):
        """Save the full config (settings + people) next to the software."""
        self.sync()
        try:
            ac.save_config(self.cfg)
            self.status.configure(text=t("Default settings saved (config.json)"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(t("Error"), str(exc))

    def _sync_widgets_from_cfg(self):
        """Push cfg -> UI variables after loading a preset/config."""
        self.mode.set(self.cfg["tile"]["color_mode"])
        self.namepos.set(self.cfg["name"].get("position", "bottom-left"))
        cur_mode = self.cfg["tile"].get("avatar_pop_mode", "reactive")
        self.v_popmode.set(next((k for k, v in self._popmode_opts.items() if v == cur_mode),
                                t("React to volume")))
        cur_ws = self.cfg["wave"].get("style", "bars")
        self.v_wavestyle.set(next((k for k, v in self._wavestyle_opts.items() if v == cur_ws),
                                  t("Bars (loudness)")))
        self.fmt.set(self.cfg["output"]["format"])
        self.v_transparent.set(self.cfg["canvas"]["transparent"])
        self.v_mux.set(self.cfg["output"]["mux_audio"])
        self.v_clean.set(self.cfg["output"]["cleanup_frames"])
        cur = str(self.cfg["output"].get("workers", "auto"))
        self.workers.set({"auto": t("auto (recommended)"), "all": t("all")}.get(cur, cur))
        self.v_w.set(self.cfg["canvas"]["width"])
        self.v_h.set(self.cfg["canvas"]["height"])
        self.v_fps.set(self.cfg["canvas"]["fps"])
        for (a, b), v in self.vars.items():
            try:
                v.set(self.cfg[a][b])
            except tk.TclError:
                pass

    # ******************** render ********************
    def render(self):
        if self._rendering:
            return
        if not self.cfg["participants"]:
            messagebox.showwarning(t("No people"), t("Add at least one person."))
            return
        if any(not p.get("audio") for p in self.cfg["participants"]):
            messagebox.showwarning(t("Missing audio"), t("Some people have no audio track assigned."))
            return
        self.sync()
        fmt = self.cfg["output"]["format"]
        if fmt == "png_sequence":
            outdir = filedialog.askdirectory(title=t("Output folder"))
            if not outdir:
                return
            self.cfg["output"]["dir"] = outdir
            out_path = None
        else:
            ext = "." + fmt
            path = filedialog.asksaveasfilename(
                title=t("Save video as"),
                defaultextension=ext,
                initialfile=f"aura_render{ext}",
                filetypes=[(fmt.upper(), "*" + ext)])
            if not path:
                return
            self.cfg["output"]["dir"] = os.path.dirname(path)
            out_path = path
        self._rendering = True
        self._render_start = time.time()
        self.status.configure(text=t("Rendering…"))

        def work():
            try:
                out = ac.render_all(self.cfg, progress=self._progress, out_path=out_path)
                self.after(0, lambda: self.status.configure(text=t("Done: {out}").format(out=out)))
                self.after(0, lambda o=out: messagebox.showinfo(t("Done"), o))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.after(0, lambda m=msg: messagebox.showerror(t("Error"), m))
                self.after(0, lambda: self.status.configure(text=t("Error")))
            finally:
                self._rendering = False

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _fmt_dur(secs):
        secs = int(max(0, secs))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _progress(self, done, total):
        now = time.time()
        elapsed = now - getattr(self, "_render_start", now)
        pct = int(done / total * 100) if total else 0
        eta = (elapsed / done) * (total - done) if done > 0 else 0.0
        wtot = len(str(total))
        txt = (f"{t('Rendering…')} {done:>{wtot}}/{total}  {pct:3d}%   "
               f"{t('elapsed')} {self._fmt_dur(elapsed)}   "
               f"{t('remaining')} {self._fmt_dur(eta)}")
        self.after(0, lambda: self.status.configure(text=txt))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    App().mainloop()