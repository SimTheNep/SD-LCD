import tkinter as tk
from tkinter import filedialog, messagebox, ttk, PhotoImage
import threading
import pygame
import soundfile as sf
import numpy as np
from scipy.signal import resample_poly
import math
import time
import os
import sys

script_dir = os.path.dirname(__file__)
font_path = os.path.join(script_dir, 'imageassets', 'sd-lcd.ttf')


NUM_SLOTS = 16

BLOCK_SIZE = 10
GRID_COLS = 127
GRID_ROWS = 64

WINDOW_W = GRID_COLS * BLOCK_SIZE
WINDOW_H = GRID_ROWS * BLOCK_SIZE

BAR_COLOR_NORMAL = (54, 66, 253) # dark blue grid (#2a38a8)   

BAR_COLOR_INVERT = (212, 218, 254)  # light blue grid (#b7c2ff)

BAR_WIDTH_BLOCKS = 6
BAR_MAX_HEIGHT_BLOCKS = 28

BAR_START_X_BLOCK = 5
BAR_BASELINE_Y_BLOCK = GRID_ROWS - 26  # baseline (26 blocks from bottom)
BAR_SPACING_BLOCKS = 1

SET_OPTIONS = ["SP 1", "SP 2", "CLASIC", "CONTEM", "SOLO", "ENHANC"]

class SD90Visualizer:
    def __init__(self):

        self.root = tk.Tk()
        self.root.title("Input Configuration")
        self.root.resizable(False, False)
        icon_img = tk.PhotoImage(file='imageassets/SD90.png')
        self.root.iconphoto(False, icon_img)

        self.wav_paths = []
        self.instrument_vars = []
        self.patch_vars = []
        self.variant_vars = []
        self.set_vars = []

        self.master_path = tk.StringVar()

        self.bar_sensitivity = tk.DoubleVar(value=1.0)  # Amplification gain
        self.bar_release = tk.DoubleVar(value=0.5)      # Release decay time (seconds)
        self.contrast_mode = tk.BooleanVar(value=False)
        self.grid_enabled = tk.BooleanVar(value=True)

        self.is_playing = False
        self.stop_flag = False
        self.channels_data = []
        self.channels_sr = []
        self.master_sr = 44100
        self.master_len = 0

        pygame.mixer.init(frequency=self.master_sr, channels=2, size=-16, buffer=512)

        self.render_thread = None
        self.master_sound = None  # pygame Sound object for master audio

        # For keyboard selection and downward pixel extension per bar
        self.selected_bar = 0
        self.bar_down_ext = [0] * NUM_SLOTS  # Downward pixel count below baseline per bar

        self.create_widgets()
        self.root.bind("<Left>", self.on_key_left)
        self.root.bind("<Right>", self.on_key_right)

        self.root.mainloop()

    def on_set_change(self, index, variant_var, variant_entry):
        idx = int(index)
        if idx in (0, 1):
            variant_var.set("---")
            variant_entry.config(state='readonly')
        else:
            if variant_entry['state'] == 'readonly':
                variant_entry.config(state='normal')
            if variant_var.get() == "---":
                variant_var.set("000")


    def create_widgets(self):
        left_frame = tk.Frame(self.root)
        left_frame.grid(row=0, column=0, padx=10, pady=10)

        headers = ["Channel", "WAV", "Name", "Inst", "Variat", "Set"]
        for col, header in enumerate(headers):
            lbl = tk.Label(left_frame, text=header, font=("Arial", 10, "bold"))
            lbl.grid(row=0, column=col, padx=5, pady=2)

        for i in range(NUM_SLOTS):
            row = i + 1
            slot_label = f"A{i+1:02}"

            lbl_slot = tk.Label(left_frame, text=slot_label, font=("Arial", 10))
            lbl_slot.grid(row=row, column=0, padx=(4, 6), sticky="w")

            path_var = tk.StringVar()
            self.wav_paths.append(path_var)
            ent_path = tk.Entry(left_frame, textvariable=path_var, width=30)
            ent_path.grid(row=row, column=1, padx=2, pady=1)
            btn_browse = tk.Button(left_frame, text="Browse", command=lambda v=path_var: self.browse_wav(v))
            btn_browse.grid(row=row, column=1, sticky="e", padx=2)

            # Special presets for A01, A02, A03, and A10
            if slot_label == "A01":
                instrument_val = "D.L.A.Pad"
                patch_val = "001"
                variant_val = "---"
                set_val = SET_OPTIONS[0]
                set_options = SET_OPTIONS
            elif slot_label == "A02":
                instrument_val = "Blown Bass"
                patch_val = "001"
                variant_val = "---"
                set_val = SET_OPTIONS[1]
                set_options = SET_OPTIONS
            elif slot_label == "A03":
                instrument_val = "SD Piano"
                patch_val = "001"
                variant_val = "---"
                set_val = SET_OPTIONS[5]
                set_options = SET_OPTIONS
            elif slot_label == "A10":
                instrument_val = "StandardSet2"
                patch_val = "001"
                variant_val = "---"
                set_options = SET_OPTIONS[2:]
                set_val = SET_OPTIONS[3]
            else:
                instrument_val = "Ac.Piano"
                patch_val = "001"
                variant_val = "000"
                set_options = SET_OPTIONS
                set_val = SET_OPTIONS[3]

            instrument_var = tk.StringVar(value=instrument_val)
            self.instrument_vars.append(instrument_var)
            ent_inst = tk.Entry(left_frame, textvariable=instrument_var, width=18)
            ent_inst.grid(row=row, column=2, padx=2, pady=1)
            ent_inst.config(validate="key",
                            validatecommand=(self.root.register(self.limit_instrument_len), '%P'))

            patch_var = tk.StringVar(value=patch_val)
            self.patch_vars.append(patch_var)
            ent_patch = tk.Entry(left_frame, textvariable=patch_var, width=5, justify='center')
            ent_patch.grid(row=row, column=3, padx=2, pady=1)
            ent_patch.config(validate="key",
                            validatecommand=(self.root.register(self.validate_three_digit), '%P'))
            ent_patch.bind("<FocusOut>", lambda e, v=patch_var: self.zero_pad(v))

            variant_var = tk.StringVar(value=variant_val)
            self.variant_vars.append(variant_var)
            ent_var = tk.Entry(left_frame, textvariable=variant_var, width=5, justify='center')
            ent_var.grid(row=row, column=4, padx=2, pady=1)

            set_var = tk.StringVar(value=set_val)
            self.set_vars.append(set_var)
            cmb_set = ttk.Combobox(left_frame, values=set_options, textvariable=set_var, width=8, state="readonly")
            cmb_set.grid(row=row, column=5, padx=2, pady=1)

            if slot_label == "A10":
                ent_var.config(state='readonly')
            else:
                cmb_set.bind(
                    "<<ComboboxSelected>>",
                    lambda e, sv=set_var, vv=variant_var, ve=ent_var:
                        self.on_set_change(SET_OPTIONS.index(sv.get()), vv, ve)
                )
                ent_var.config(validate="key",
                            validatecommand=(self.root.register(self.validate_three_digit), '%P'))
                ent_var.bind("<FocusOut>", lambda e, v=variant_var: self.zero_pad(v))

            if slot_label != "A10":
                self.on_set_change(SET_OPTIONS.index(set_var.get()), variant_var, ent_var)

        # Master WAV path
        tk.Label(left_frame, text="Master").grid(row=NUM_SLOTS + 1, column=0, sticky="w", padx=5, pady=10)
        ent_master = tk.Entry(left_frame, textvariable=self.master_path, width=30)
        ent_master.grid(row=NUM_SLOTS + 1, column=1, columnspan=2, sticky="w", padx=5, pady=10)
        btn_master_browse = tk.Button(left_frame, text="Browse", command=self.browse_master)
        btn_master_browse.grid(row=NUM_SLOTS + 1, column=2, sticky="w", padx=0, pady=10)

        # Control Buttons
        control_row = NUM_SLOTS + 2
        btn_master_reset = tk.Button(left_frame, text="Reset", command=self.master_reset)
        btn_master_reset.grid(row=control_row, column=1, padx=5, pady=10)

        btn_bulk_import = tk.Button(left_frame, text="Import Multiple", command=self.bulk_import_wavs)
        btn_bulk_import.grid(row=control_row, column=2, padx=5, pady=10)

        self.render_btn = tk.Button(left_frame, text="Render & Play", command=self.start_render)
        self.render_btn.grid(row=control_row, column=3, padx=5, pady=10)

        self.stop_btn = tk.Button(left_frame, text="Stop", state="disabled", command=self.stop_render)
        self.stop_btn.grid(row=control_row, column=4, padx=5, pady=10)

        right_frame = tk.Frame(self.root)
        right_frame.grid(row=0, column=1, sticky="n", padx=10, pady=10)

        tk.Label(right_frame, text="Settings", font=("Arial", 12, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 10)
        )

        tk.Label(right_frame, text="Bar Sensitivity (Amplification):").grid(
            row=1, column=0, sticky="w", padx=5, pady=5
        )
        bar_sens_scale = tk.Scale(
            right_frame, from_=0.1, to=10.0, resolution=0.1, orient=tk.HORIZONTAL,
            variable=self.bar_sensitivity, length=150
        )
        bar_sens_scale.grid(row=1, column=1, padx=5, pady=5)

        tk.Label(right_frame, text="Bar Release (seconds):").grid(
            row=2, column=0, sticky="w", padx=5, pady=5
        )
        bar_release_scale = tk.Scale(
            right_frame, from_=0.05, to=2.0, resolution=0.05, orient=tk.HORIZONTAL,
            variable=self.bar_release, length=150
        )
        bar_release_scale.grid(row=2, column=1, padx=5, pady=5)

        contrast_chk = tk.Checkbutton(right_frame, text="Contrast Mode (Invert Colors)", variable=self.contrast_mode)
        contrast_chk.grid(row=3, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        grid_chk = tk.Checkbutton(right_frame, text="Enable Grid", variable=self.grid_enabled)
        grid_chk.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        self.img1 = PhotoImage(file="imageassets/edirol.png")
        img_box1 = tk.Label(right_frame, image=self.img1)
        img_box1.grid(row=5, column=0, columnspan=2, pady=(70, 5), padx=5)

        self.img2 = PhotoImage(file="imageassets/creds.png")
        img_box2 = tk.Label(right_frame, image=self.img2)
        img_box2.grid(row=6, column=0, columnspan=2, pady=(55, 5), padx=5)


    def master_reset(self):
        python = sys.executable
        os.execl(python, python, * sys.argv)

    def limit_instrument_len(self, text):
        return len(text) <= 15

    def validate_three_digit(self, text):
        if text == "":
            return True 
        if len(text) > 3:
            return False
        return text.isdigit()

    def zero_pad(self, var):
        val = var.get()
        if val.isdigit():
            var.set(val.zfill(3))
        else:
            var.set("000")

    def browse_wav(self, var):
        path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if path:
            var.set(path)

    def browse_master(self):
        path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if path:
            self.master_path.set(path)

    def bulk_import_wavs(self):
        paths = filedialog.askopenfilenames(filetypes=[("WAV files", "*.wav")])
        for i, path in enumerate(paths):
            if i >= NUM_SLOTS:
                break
            self.wav_paths[i].set(path)

    def start_render(self):
        if self.is_playing:
            messagebox.showwarning("Already Running", "Rendering already in progress.")
            return

        self.channels_data = []
        self.channels_sr = []

        for i in range(NUM_SLOTS):
            path = self.wav_paths[i].get()
            if path == "":
                self.channels_data.append(None)
                self.channels_sr.append(0)
                continue
            try:
                data, sr = sf.read(path)
                if len(data.shape) > 1:
                    data = data.mean(axis=1)  # convert to mono for analysis
                self.channels_data.append(data)
                self.channels_sr.append(sr)
            except Exception as e:
                messagebox.showerror("Error", f"Error loading {path}: {e}")
                return

        # Load master WAV 
        master_path = self.master_path.get()
        if master_path == "":
            messagebox.showerror("Error", "Please select a master WAV file.")
            return

        try:
            master_data, master_sr = sf.read(master_path)
            self.master_sr = master_sr
            self.master_len = len(master_data)
            pygame.mixer.quit()  # Re-init mixer for master sample rate
            pygame.mixer.init(frequency=master_sr, channels=2, size=-16, buffer=512)
            self.master_sound = pygame.mixer.Sound(master_path)
        except Exception as e:
            messagebox.showerror("Error", f"Error loading master WAV: {e}")
            return

        self.is_playing = True
        self.stop_flag = False
        self.render_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        self.render_thread = threading.Thread(target=self.render_loop, daemon=True)
        self.render_thread.start()

    def stop_render(self):
        self.stop_flag = True
        self.is_playing = False
        self.render_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        if self.master_sound:
            self.master_sound.stop()
        pygame.mixer.stop()
        pygame.mixer.quit()

    def render_loop(self):
        pygame.display.init()
        icon = pygame.image.load('imageassets/SD90.png')
        pygame.display.set_icon(icon)
        screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption("SD-90 LCD Visualizer")

        self.bg_image_normal = pygame.image.load("imageassets/base.png").convert()
        self.bg_image_invert = pygame.image.load("imageassets/contrast.png").convert()

        pygame.font.init()
        font = pygame.font.Font(font_path, 70)

        if self.contrast_mode.get():
            bg_image = self.bg_image_invert
            bar_color = BAR_COLOR_INVERT
            grid_color = BAR_COLOR_INVERT
            text_color = BAR_COLOR_INVERT
        else:
            bg_image = self.bg_image_normal
            bar_color = BAR_COLOR_NORMAL
            grid_color = BAR_COLOR_NORMAL
            text_color = BAR_COLOR_NORMAL

        # Resample all data to match master sample rate
        for i in range(NUM_SLOTS):
            data = self.channels_data[i]
            sr = self.channels_sr[i]
            if data is None:
                continue
            if sr != self.master_sr:
                gcd = math.gcd(sr, self.master_sr)
                up = self.master_sr // gcd
                down = sr // gcd
                self.channels_data[i] = resample_poly(data, up, down)
                self.channels_sr[i] = self.master_sr

        # Normalize amplitudes
        max_vals = [np.max(np.abs(d)) if d is not None and len(d) > 0 else 1.0 for d in self.channels_data]
        max_vals = [mv if mv > 0 else 1.0 for mv in max_vals]

        bar_heights = [0.0] * NUM_SLOTS
        last_update_time = time.time()

        if self.master_sound:
            self.master_sound.play()

        play_start_time = time.time()
        clock = pygame.time.Clock()

        while not self.stop_flag:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.stop_flag = True
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_LEFT:
                        self.selected_bar = (self.selected_bar - 1) % NUM_SLOTS
                    elif event.key == pygame.K_RIGHT:
                        self.selected_bar = (self.selected_bar + 1) % NUM_SLOTS

            screen.blit(bg_image, (0, 0))

            sel = self.selected_bar
            label = f"A{sel+1:02}"
            patch = self.patch_vars[sel].get()
            variant = self.variant_vars[sel].get()
            instrument = self.instrument_vars[sel].get()
            set_text = self.set_vars[sel].get()

            text_color = BAR_COLOR_NORMAL if not self.contrast_mode.get() else BAR_COLOR_INVERT

            label_surf = font.render(label, True, text_color)
            patch_surf = font.render(instrument, True, text_color)
            instr_surf = font.render(patch, True, text_color)
            vari_surf = font.render(variant, True, text_color)
            set_surf = font.render(set_text, True, text_color)

            instr_lbl = font.render("INST", True, text_color)
            vari_lbl = font.render("VARIAT", True, text_color)
            set_lbl = font.render("SET", True, text_color)

            # First row: A00 + patch
            screen.blit(label_surf, (6*BLOCK_SIZE, 41*BLOCK_SIZE))
            screen.blit(patch_surf, (36*BLOCK_SIZE, 41*BLOCK_SIZE))

            # Second row: instrument, variant, set (below A00 row)
            screen.blit(instr_surf, (18*BLOCK_SIZE, 49*BLOCK_SIZE))
            screen.blit(vari_surf, (60*BLOCK_SIZE, 49*BLOCK_SIZE))
            screen.blit(set_surf, (90*BLOCK_SIZE, 49*BLOCK_SIZE))


            if self.grid_enabled.get():
                for x in range(0, WINDOW_W, BLOCK_SIZE):
                    pygame.draw.line(screen, grid_color, (x, 0), (x, WINDOW_H))
                for y in range(0, WINDOW_H, BLOCK_SIZE):
                    pygame.draw.line(screen, grid_color, (0, y), (WINDOW_W, y))

            now = time.time()
            dt = now - last_update_time
            last_update_time = now

            elapsed = time.time() - play_start_time
            cursor = int(elapsed * self.master_sr)

            if cursor >= self.master_len:
                self.stop_flag = True
                continue

            step_size = int(self.master_sr / 50)  # 50 FPS

            for i in range(NUM_SLOTS):
                data = self.channels_data[i]
                height_blocks = 0
                if data is not None and len(data) > 0:
                    start_idx = cursor
                    end_idx = min(cursor + step_size, len(data))
                    window = data[start_idx:end_idx]
                    amplitude = np.sqrt(np.mean(window ** 2)) if len(window) > 0 else 0.0
                    norm_amp = min(amplitude / max_vals[i] * self.bar_sensitivity.get(), 1.0)

                    target = norm_amp * BAR_MAX_HEIGHT_BLOCKS

                    if target >= BAR_MAX_HEIGHT_BLOCKS * 0.98:
                        bar_heights[i] = BAR_MAX_HEIGHT_BLOCKS
                    elif target > bar_heights[i]:
                        bar_heights[i] = target
                    else:
                        decay = math.exp(-dt / max(self.bar_release.get(), 1e-4))
                        bar_heights[i] *= decay

                    height_blocks = int(bar_heights[i])

                base_x = BAR_START_X_BLOCK + i * (BAR_WIDTH_BLOCKS + BAR_SPACING_BLOCKS) + 1
                base_y = BAR_BASELINE_Y_BLOCK - 1

                for h in range(height_blocks):
                    rect = pygame.Rect(
                        base_x * BLOCK_SIZE,
                        (base_y - h) * BLOCK_SIZE,
                        BAR_WIDTH_BLOCKS * BLOCK_SIZE,
                        BLOCK_SIZE
                    )
                    pygame.draw.rect(screen, bar_color, rect)

                if self.bar_down_ext[i] > 0:
                    dark_color = tuple(max(c - 80, 0) for c in bar_color)
                    for h in range(self.bar_down_ext[i]):
                        rect = pygame.Rect(
                            base_x * BLOCK_SIZE,
                            (base_y + 1 + h) * BLOCK_SIZE,
                            BAR_WIDTH_BLOCKS * BLOCK_SIZE,
                            BLOCK_SIZE
                        )
                        pygame.draw.rect(screen, dark_color, rect)

                # Selected bar indicator
                if i == self.selected_bar:
                    rect = pygame.Rect(
                        base_x * BLOCK_SIZE,
                        (base_y + 1) * BLOCK_SIZE,
                        BAR_WIDTH_BLOCKS * BLOCK_SIZE,
                        BLOCK_SIZE
                    )
                    pygame.draw.rect(screen, bar_color, rect)


            pygame.display.flip()
            clock.tick(50)

        pygame.display.quit()
        if self.master_sound:
            self.master_sound.stop()

        self.is_playing = False
        self.render_btn.config(state="normal")
        self.stop_btn.config(state="disabled")


    # Keyboard event handlers
    def on_key_left(self, event):
        if not self.is_playing:
            return
        self.selected_bar = (self.selected_bar - 1) % NUM_SLOTS

    def on_key_right(self, event):
        if not self.is_playing:
            return
        self.selected_bar = (self.selected_bar + 1) % NUM_SLOTS

    def on_closing(self):
        if self.is_playing:
            self.stop_flag = True
            if self.render_thread:
                self.render_thread.join()
        self.root.destroy()

if __name__ == "__main__":
    SD90Visualizer()
