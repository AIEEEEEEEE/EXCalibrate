import json
import time
import os
import pyautogui
import pytesseract
import re
import cv2
import threading
import keyboard
import ctypes
import pygetwindow as gw
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from whenever import Instant
from PIL import Image, ImageGrab

DATA = "data.json"

REGIONS = ["Quick Selection", "Calibrate", "Stat One Old", "Stat One New", "Stat Two Old", "Stat Two New", "Stat Three Old", "Stat Three New", "Stat Four Old", "Stat Four New", "Restore", "Confirm", "Don't Show", "Don't Show Confirm"]

# 

def load_data():
    if os.path.exists(DATA):
        try:
            with open(DATA, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_data(data):
    with open(DATA, "w") as f:
        json.dump(data, f, indent=4)

def rect_to_center(rect):
    x1, y1, x2, y2 = rect
    cx = int((x1 + x2) / 2)
    cy = int((y1 + y2) / 2)
    return [cx, cy]

def normalize_rect(x1, y1, x2, y2):
    return [int(min(x1, x2)), int(min(y1, y2)), int(max(x1, x2)), int(max(y1, y2))]

#

class OverlayEditor:

    HANDLE_SIZE = 8

    def __init__(self, parent, regions, data_ref, on_closed=None):
        self.parent = parent
        self.regions = regions
        self.data = data_ref
        self.on_closed = on_closed

        self.root = tk.Toplevel()
        self.root.withdraw()
        
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.35)
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{self.screen_w}x{self.screen_h}+0+0")

        self.canvas = tk.Canvas(self.root, bg="gray", highlightthickness=0, cursor="tcross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.items = {}
        self.active_label = None
        self.drag_mode = None
        self.drag_offset = (0, 0)

        self._init_items()

        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        self.root.bind("<Escape>", self._on_escape)

        self._hint_id = self.canvas.create_text(
            self.screen_w // 2, self.screen_h - 30,
            text="Drag to move. Drag corners to resize. Press Esc to open/close overlay.",
            anchor="s",
            fill="white",
            font=("Segoe UI", 20, "bold")
        )        

    def _init_items(self):
        for idx, label in enumerate(self.regions):
            rect = None
            entry = self.data.get(label)
            if isinstance(entry, list) and len(entry) == 2:
                rect = entry[0]
            elif isinstance(entry, list) and len(entry) == 4:
                rect = entry
            if rect is None:
                w, h = 180, 60
                x = 60 + (idx % 6) *  (w + 20)
                y = 60 + (idx // 6) * (h + 40)
                rect = [x, y, x + w, y + h]
            self._create_item(label, rect)

    def _create_item(self, label, rect):
        x1, y1, x2, y2 = rect
        rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline="gold", width = 2)
        handles = []
        for (hx, hy) in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
            hid = self.canvas.create_rectangle(
                hx - self.HANDLE_SIZE // 2, hy - self.HANDLE_SIZE // 2,
                hx + self.HANDLE_SIZE // 2, hy + self.HANDLE_SIZE // 2, 
                outline="white", width=2, fill=""
            )
            handles.append(hid)
        
        label_id = self.canvas.create_text(
            (x1 + x2) // 2, (y1 + y2) // 2,
            text=label, fill="white", font=("Segoe UI", 11, "bold")
        )
        self.items[label] = {"rect": rect, "rect_id": rect_id, "handles": handles, "label_id": label_id}

    def _hit_test(self, x, y):
        """
            Return (label, mode),
                mode = (
                        ("resize", handle_index), 
                        ("move", None), 
                        (None, None)
                        )
        """
        for label, info in self.items.items():
            for i, hid in enumerate(info["handles"]):
                x1, y1, x2, y2 = self.canvas.coords(hid)
                if x1 <= x <= x2 and y1 <= y <= y2:
                    return label, ("resize", i)
        for label, info in self.items.items():
            x1, y1, x2, y2 = self.canvas.coords(info["rect_id"])
            if x1 <= x <= x2 and y1 <= y <= y2:
                return label, ("move", None)
        return None, (None, None)
    
    def on_down(self, event):
        label, mode = self._hit_test(event.x, event.y)
        self.active_label = label
        self.drag_mode = mode
        self.drag_origin = (event.x, event.y)
        if self.active_label and mode[0] == "move":
            x1, y1, x2, y2 = self.items[label]["rect"]
            self.drag_offset = (event.x - x1, event.y - y1)

    def on_drag(self, event):
        info = self.items[self.active_label]
        x1, y1, x2, y2 = info["rect"]

        if self.drag_mode[0] == "move":
            dx = event.x - self.drag_offset[0]
            dy = event.y - self.drag_offset[1]
            w = x2 - x1
            h = y2 - y1
            new = normalize_rect(dx, dy, dx + w, dy + h)
        else:
            corner = self.drag_mode[1]
            nx1, ny1, nx2, ny2 = x1, y1, x2, y2
            if corner == 0: # top left
                nx1, ny1 = event.x, event.y
            elif corner == 1: # top right
                nx2, ny1 = event.x, event.y
            elif corner == 2: # bottom right
                nx2, ny2 = event.x, event.y
            elif corner == 3: # bottom left
                nx1, ny2 = event.x, event.y
            new = normalize_rect(nx1, ny1, nx2, ny2)

        self._apply_rect(self.active_label, new)
                
    def on_up(self, _event):
        self.drag_mode = (None, None)
        self.drag_offset = (0, 0)

    def _apply_rect(self, label, rect):
        # rect update
        self.items[label]["rect"] = rect
        x1, y1, x2, y2 = rect
        # canvas rect update
        self.canvas.coords(self.items[label]["rect_id"], x1, y1, x2, y2)
        # handle update
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        for hid, (hx, hy) in zip(self.items[label]["handles"], corners):
            self.canvas.coords(
                hid,
                hx - self.HANDLE_SIZE // 2, hy - self.HANDLE_SIZE // 2,
                hx + self.HANDLE_SIZE // 2, hy + self.HANDLE_SIZE // 2, 
            )
        # label update
        self.canvas.coords(self.items[label]["label_id"], (x1 + x2)//2, (y1 + y2)//2)

    def _on_escape(self, _event=None):
        self.close()

    def close(self):
        for label, info in self.items.items():
            rect = [int(v) for v in info["rect"]]
            center = rect_to_center(rect)
            self.data[label] = [rect, center]
        save_data(self.data)

        try:
            self.root.destroy()
        except tk.TclError:
            pass

        if self.on_closed:
            self.on_closed()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

#

class App(tk.Tk):
    def __init__(self):
        super().__init__() 
        self.title("Autocalibrate")
        self.geometry("420x220")
        self.resizable(False, False)

        self.data = load_data()
        self.overlay = None
        self.automation_running = False
        self.automation_thread = None
        self.automation_interval = 2.0
        
        keyboard.add_hotkey('esc', lambda: self.after(0, self.stop_automation))

        # Overlay
        row = ttk.Frame(self)
        row.pack(fill="x", padx=12, pady=(12, 6))
        self.overlay_btn = ttk.Button(row, text="Start overlay", command=self.toggle_overlay)
        self.overlay_btn.pack(side="left")
        ttk.Label(row, text="(Drag/resize boxes, Esc to close)").pack(side="left", padx=8)

        # Automation
        row2 = ttk.Frame(self)
        row2.pack(fill="x", padx=12, pady=(12, 6))
        self.run_btn = ttk.Button(row2, text="Run", command=self.toggle_automation)
        self.run_btn.pack(side="left", padx=(0, 8))
        self.status_var = tk.StringVar(value="Status: idle")
        ttk.Label(row2, textvariable=self.status_var).pack(side="left")

        # Minimum Calibration
        row3 = ttk.Frame(self)
        row3.pack(fill="x", padx=12, pady=(12, 6))
        self.target_var = tk.StringVar(value="")
        self.calibtration_target = ttk.Entry(row3, width=12, textvariable=self.target_var)
        self.calibtration_target.pack(side="left", padx=(0, 8))
        self.note = tk.StringVar(value="Minimum calibration %#")
        ttk.Label(row3, textvariable=self.note).pack(side="left")

        # OCR Log
        row_log = ttk.Frame(self)
        row_log.pack(fill='both', expand=True, padx=12, pady=(6, 12))
        ttk.Label(row_log, text="Log").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(row_log, height=6, width=48, state="disabled", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)

        # Close
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def toggle_overlay(self):
        if self.overlay is None or not self.overlay.root.winfo_exists():
            self.overlay = OverlayEditor(self, REGIONS, self.data, on_closed=self._overlay_closed)
            self.overlay.show()
            self.overlay_btn.config(text="Stop Overlay")
            return
        self.overlay.close()

    def missing_regions(self):
        missing = [r for r in REGIONS if r not in self.data]
        return (bool(missing), missing)
    
    def parse_target(self):
        raw = self.target_var.get().strip()
        if raw == "":
            return None
        try:
            v = int(raw)
            return v if v > 0 else None
        except ValueError:
            return False

    def toggle_automation(self):
        if not self.automation_running:  
            nonempty, missing = self.missing_regions()
            if nonempty:
                messagebox.showwarning("Missing Regions", 
                                       f"Please set these regions first:\n{'\n'.join(missing)}")
                return
            
            parsed = self.parse_target()
            if parsed is False:
                messagebox.showwarning("Invalid Calibration Target", "Invalid Calibration Target")
                return
            self.target_value = parsed

            self.start_automation()
        else:
            self.stop_automation()

    def start_automation(self):
        if self.automation_running:
            return
        self.automation_running = True
        self.status_var.set("Status: running")
        self.run_btn.config(text="Stop")
        self.attributes('-topmost', False)

        if not (ok := self.focus_window()):
            self.status_var.set('Status: could not focus')
            self.automation_running = False
            return

        self.automation_thread = threading.Thread(target=self._automation_loop, daemon=True)
        self.automation_thread.start()

    def focus_window(self):
        windows = gw.getWindowsWithTitle("EXILIUM")
        if not windows:
            return False
        win = windows[0]
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.1)
            return True
        except Exception as e:
            print('Failed to focus', e)
            return False

    def stop_automation(self):
        if not self.automation_running:
            return
        self.automation_running = False
        self.automation_thread = None
        self.deiconify()

    def _automation_loop(self):
        while self.automation_running:
            self._automation_single()
        self.after(0, lambda: (self.status_var.set("Status: idle"),
                               self.run_btn.config(text="Run")))
    
    def _automation_single(self):
        stat_values = {}
        for label, (rect, center) in ((k, v) for k, v in list(self.data.items()) if k != "time"):
            if not self.automation_running:
                return
            
            if label == "Calibrate":
                if not self.safe_move_click(center, 0.2):
                    return
                self.safe_sleep(5)
                continue
            if label.startswith("Stat"):
                stat_values[label] = self.ocr_value(rect)
                continue
            if label == "Restore":
                total = 0
                diff = 0
                extreme = True
                valid_stats = {k: v for k,v in stat_values.items() if v is not None}
                stat_iter = iter(valid_stats.items())
                for (old_key, old_val), (new_key, new_val) in zip(stat_iter, stat_iter):
                    total += new_val
                    diff += new_val - old_val
                    if new_val < 100:
                        extreme = False
                self.log_ocr(list(valid_stats.values())[1::2], total, diff)
                if diff < 0 or not extreme:
                    if not self.safe_move_click(center, 0.2):
                        return
                continue
            if label == "Confirm":
                if diff > 0 and extreme:
                    if not self.safe_move_click(center, 0.2):
                        return
                if self.target_value is not None and total >= self.target_value:
                    self.automation_running = False
                    return
                continue
            if label == "Don't Show":
                if self.reset():
                    if not self.safe_move_click(center, 0.2):
                        return
                    if not self.safe_move_click(self.data["Don't Show Confirm"][1], 0.2):
                        return
                    
                    self.data["time"] = Instant.now().format_common_iso()
                    save_data(self.data)
                continue
            if label == "Don't Show Confirm":
                continue

            if not self.safe_move_click(center, 0.2):
                return
            
        # else:
        #     self.automation_running = False
        #     self.status_var.set("Status: idle")

    def safe_move_click(self, center, move_time):
        if not self.automation_running:
            return False
        pyautogui.moveTo(*center, duration=move_time)
        if not self.automation_running:
            return False
        pyautogui.click()
        return True
    
    def safe_sleep(self, total):
        step = 0.05
        waited = 0
        while self.automation_running and waited < total:
            time.sleep(step)
            waited += step
        return self.automation_running

    def reset(self):
        time = self.data.get("time")
        if not time:
            return True
        return Instant.now() >= Instant.parse_common_iso(time).add(hours=24)
    
    def ocr_value(self, rect):
        self.focus_window()
        x1, y1, x2, y2 = rect
        img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        scale = 3
        resized = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)

        config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789%'
        text = pytesseract.image_to_string(resized, config=config)

        m = re.findall(r"\d+", text)
        return int(''.join(m)) if m else None
    
    def log_ocr(self, values, total, diff):
        nums = [str(v) for v in values]
        line = f'{' + '.join(nums)} = {total}, d = {diff}'
        self.after(0, self.append_log_line, line)

    def append_log_line(self, line: str):
        self.log.configure(state='normal')
        self.log.insert('end', line + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def _overlay_closed(self):
        self.overlay = None
        self.overlay_btn.config(text="Start Overlay")
    
    def on_close(self):
        save_data(self.data)
        keyboard.clear_all_hotkeys()
        if self.overlay is not None:
            self.overlay.destroy()
        self.destroy()

if __name__ == "__main__":
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    App().mainloop()