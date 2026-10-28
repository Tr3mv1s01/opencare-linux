"""Load installed application icons; never download images or execute launchers."""
import base64
from pathlib import Path
import tkinter as tk


class AppIcons:
    def __init__(self, master):
        self.master = master
        self.cache = {}
        self.loaded = set()
        self.theme = None
        self.pixbuf = None
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk, GdkPixbuf
            ok, _ = Gtk.init_check(None)
            if ok:
                self.theme = Gtk.IconTheme.get_default()
                self.pixbuf = GdkPixbuf
        except (ImportError, ValueError, RuntimeError):
            pass

    def get(self, name):
        if name in self.cache:
            return self.cache[name]
        image = None
        try:
            path = name if Path(name).is_absolute() else None
            if self.theme and path is None:
                info = self.theme.lookup_icon(name, 32, 0)
                if info:
                    path = info.get_filename()
            if path and self.pixbuf:
                pixbuf = self.pixbuf.Pixbuf.new_from_file_at_scale(path, 32, 32, True)
                ok, data = pixbuf.save_to_bufferv('png', [], [])
                if ok:
                    image = tk.PhotoImage(master=self.master, data=base64.b64encode(data))
            elif path and Path(path).suffix.lower() == '.png':
                image = tk.PhotoImage(master=self.master, file=path)
                factor = max(1, (max(image.width(), image.height()) + 31) // 32)
                image = image.subsample(factor)
        except Exception:
            image = None
        if image is not None:
            self.loaded.add(name)
        if image is None:
            image = tk.PhotoImage(master=self.master, width=32, height=32)
            image.put('#e6edfb', to=(0, 0, 32, 32))
            for x, y in [(7, 7), (18, 7), (7, 18), (18, 18)]:
                image.put('#527dd8', to=(x, y, x+7, y+7))
        self.cache[name] = image
        return image
