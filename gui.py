import tkinter as tk
from tkinter import ttk, font, messagebox, scrolledtext
import multiprocessing as mp
from queue import Empty
import time
import os
import traceback
from collections import defaultdict, deque 
import datetime as dt 
import torch 
from functools import partial 

try:
    import matplotlib
    matplotlib.use('TkAgg') 
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
    print("[GUI] Matplotlib found and loaded.")
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("\nWARNING: Matplotlib not found. Install it ('pip install matplotlib') to enable plots.\n")

import config 
from video_processor import process_video_worker 
from traffic_logic import TrafficLightController
from polygon_utils import define_polygon_interactive

if config.ESP32_ENABLED:
    try:
        from esp32_controller import ESP32SerialController
        ESP32_CONTROLLER_AVAILABLE = True
        print("[GUI] ESP32SerialController found and will be used.")
    except ImportError:
        ESP32_CONTROLLER_AVAILABLE = False
        print("\nWARNING: esp32_controller.py not found or has issues. ESP32 communication will be disabled.\n")
    except Exception as e_esp_import: 
        ESP32_CONTROLLER_AVAILABLE = False
        print(f"\nWARNING: Error importing esp32_controller.py: {e_esp_import}. ESP32 communication will be disabled.\n")
else:
    ESP32_CONTROLLER_AVAILABLE = False
    print("[GUI] ESP32 communication is disabled in config.py.")

class LaneCounterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Adaptive Traffic Light Control - {config.VERSION}")
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(size=config.DEFAULT_FONT_SIZE)
        self.root.option_add("*Font", default_font)

        self.center_window(config.INITIAL_WINDOW_WIDTH, config.INITIAL_WINDOW_HEIGHT)

        self.style = ttk.Style()
        try:
            default_trough = self.style.lookup("Horizontal.TProgressbar", "troughcolor")
            sys_default_bar_bg = self.style.lookup("Horizontal.TProgressbar", "background")
            default_bar_bg = "blue" if sys_default_bar_bg in ['green', 'forest green', '#008000', '#228B22'] else sys_default_bar_bg
            if default_bar_bg is None: default_bar_bg = "blue"
        except tk.TclError:
            default_trough = "lightgrey"
            default_bar_bg = "blue"
            print("[GUI Style] TclError looking up Progressbar style, using hardcoded fallbacks.")
        
        self.style.configure("green.Horizontal.TProgressbar", background='forest green', troughcolor=default_trough)
        self.style.configure("yellow.Horizontal.TProgressbar", background='darkorange', troughcolor=default_trough)
        self.style.configure("red.Horizontal.TProgressbar", background='red', troughcolor=default_trough)
        self.style.configure("default.Horizontal.TProgressbar", background=default_bar_bg, troughcolor=default_trough)

        self.defined_polygons = {}
        self.skipped_approaches = []
        self.processes = []
        self.process_map = {}
        self.final_summaries = {}
        self.approach_widgets = {}
        self.traffic_light_ui = {}
        self.finished_workers = 0
        self.active_workers_initial_count = 0
        self.traffic_logic_timer_id = None
        self.plot_update_timer_id = None
        self.esp32_controller = None
        self.manual_overrides_gui_state = defaultdict(bool) 

        self.approach_history = defaultdict(lambda: deque(maxlen=config.PLOT_MAX_POINTS))
        self.manager = mp.Manager()
        self.results_queue = self.manager.Queue()

        if config.ESP32_ENABLED and ESP32_CONTROLLER_AVAILABLE:
            try:
                configured_video_approaches = [name for name, path in config.VIDEO_PATHS]
                valid_esp32_mapping = {}
                for gui_approach, esp_code in config.ESP32_APPROACH_MAPPING.items():
                    if gui_approach in configured_video_approaches:
                        valid_esp32_mapping[gui_approach] = esp_code
                    else:
                        print(f"[GUI Warning] ESP32_APPROACH_MAPPING contains key '{gui_approach}' which is not in VIDEO_PATHS. It will be ignored for ESP32.")
                
                if not valid_esp32_mapping and config.ESP32_APPROACH_MAPPING:
                    messagebox.showwarning("ESP32 Config Warning",
                                           "ESP32_APPROACH_MAPPING in config.py does not contain any "
                                           "approach names currently defined in VIDEO_PATHS. "
                                           "ESP32 communication might not work as expected.")
                    print("[GUI Warning] ESP32_APPROACH_MAPPING is empty after filtering against VIDEO_PATHS. ESP32 commands may be ineffective.")

                self.esp32_controller = ESP32SerialController(
                    port=config.ESP32_PORT,
                    baudrate=config.ESP32_BAUDRATE,
                    approach_mapping=valid_esp32_mapping
                )
                if not self.esp32_controller.is_connected:
                    messagebox.showwarning("ESP32 Connection Failed",
                                           f"Failed to connect to ESP32 on {config.ESP32_PORT}.\n"
                                           "The simulation will run without hardware control.\n"
                                           "Check ESP32 connection and port settings in config.py.")
            except Exception as e_esp_init:
                messagebox.showerror("ESP32 Init Error",
                                     f"Failed to initialize ESP32 controller: {e_esp_init}\n"
                                     "The simulation will run without hardware control.")
                print(f"[GUI Error] Failed to initialize ESP32 controller: {e_esp_init}")
                traceback.print_exc()
                self.esp32_controller = None 
        elif config.ESP32_ENABLED and not ESP32_CONTROLLER_AVAILABLE:
             messagebox.showwarning("ESP32 Init Warning",
                                     "ESP32 is enabled in config, but the ESP32 controller module "
                                     "could not be loaded. Hardware control will be disabled.")

        try:
            self.controller = TrafficLightController(
                config.TRAFFIC_LIGHT_CONFIG,
                config.VEHICLE_TYPE_WEIGHTS,
                config.DEFAULT_VEHICLE_WEIGHT
            )
        except Exception as e:
             messagebox.showerror("Initialization Error", f"Failed to initialize TrafficLightController:\n{e}\n\nCheck traffic light configuration in config.py.")
             print(f"[GUI Init Error] Failed to initialize TrafficLightController: {e}")
             traceback.print_exc()
             self.root.quit()
             return

        self._setup_ui_frames()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        print("[GUI] LaneCounterApp initialized.")

    def _setup_ui_frames(self):
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(expand=True, fill=tk.BOTH)
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ttk.Label(self.main_frame, text="Initializing...", font=("Helvetica", 12, "bold"))
        self.status_label.grid(row=0, column=0, pady=5, sticky="ew")

        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.grid(row=1, column=0, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=config.UI_COLUMN_WEIGHT_TRAFFIC_LIGHT)
        self.content_frame.grid_columnconfigure(1, weight=config.UI_COLUMN_WEIGHT_APPROACH_MONITOR)
        self.content_frame.grid_rowconfigure(0, weight=1)

        self.traffic_light_frame = ttk.LabelFrame(self.content_frame, text="Traffic Light Simulation", padding="10")
        self.traffic_light_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.approaches_frame = ttk.LabelFrame(self.content_frame, text="Approach Monitoring & Trends", padding="10")
        self.approaches_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        for i in range(config.UI_APPROACH_MONITOR_COLS):
             self.approaches_frame.grid_columnconfigure(i, weight=1)

    def initialize_application(self):
        print("[GUI] Starting application initialization...")
        if not self._run_polygon_definition():
            try: self.root.destroy()
            except: pass
            return False
        self._create_widgets()
        self._start_processing()
        return True

    def center_window(self, width=800, height=600):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _run_polygon_definition(self):
        self.status_label.config(text="Define Lane Polygons for Approaches...")
        self.root.update()
        print("[GUI] Starting interactive polygon definition...")
        self.defined_polygons.clear()
        self.skipped_approaches.clear()
        defined_count = 0
        approaches_to_define = list(config.VIDEO_PATHS)
        if not approaches_to_define:
             messagebox.showerror("Configuration Error", "No video paths defined in config.py.")
             return False
        controller_approaches = self.controller.get_all_approach_names()
        valid_approaches_for_definition = [(name, path) for name, path in approaches_to_define if name in controller_approaches]
        skipped_due_to_config = [name for name, path in approaches_to_define if name not in controller_approaches]
        if skipped_due_to_config:
            print(f"[GUI Warning] Approaches skipped (not in TrafficLightConfig): {skipped_due_to_config}")
            self.skipped_approaches.extend(skipped_due_to_config)
        initial_approach_count = len(valid_approaches_for_definition)
        if initial_approach_count == 0:
             messagebox.showerror("Configuration Error", "No configured video paths match approaches in the traffic controller.")
             return False
        for i, (approach_name, video_path) in enumerate(valid_approaches_for_definition):
            self.status_label.config(text=f"Define Polygon: Approach {i+1}/{initial_approach_count} ({approach_name})")
            self.root.update()
            if not os.path.exists(video_path):
                print(f"[GUI Warning] Video file not found for {approach_name}: {video_path}. Skipping.")
                messagebox.showwarning("File Not Found", f"Video file not found for approach '{approach_name}':\n{video_path}\n\nSkipping this approach.")
                self.skipped_approaches.append(approach_name)
                continue
            polygon = define_polygon_interactive(approach_name, video_path)
            if polygon is not None: self.defined_polygons[approach_name] = polygon; defined_count += 1
            else: self.skipped_approaches.append(approach_name)
        if not self.defined_polygons:
            messagebox.showerror("Error", "No lane polygons were defined. Cannot start.")
            print("\n[GUI] No polygons defined. Exiting.")
            return False
        print(f"\n[GUI] Polygon definition complete. {defined_count} polygons defined.")
        self.status_label.config(text=f"Polygons defined for {defined_count} approaches.")
        self.root.update()
        time.sleep(0.5)
        return True

    def _toggle_manual_override(self, intersection_name, approach_name):
        is_currently_forced_red_gui = self.manual_overrides_gui_state.get(approach_name, False)
        new_override_state = not is_currently_forced_red_gui
        
        self.manual_overrides_gui_state[approach_name] = new_override_state
        success = self.controller.set_manual_override(intersection_name, approach_name, new_override_state)

        if not success:
            messagebox.showerror("Override Error", f"Failed to set override for {approach_name} in {intersection_name}.")
            self.manual_overrides_gui_state[approach_name] = is_currently_forced_red_gui 
            if approach_name in self.approach_widgets:
                override_button = self.approach_widgets[approach_name].get("override_button")
                if override_button and override_button.winfo_exists():
                    override_button.config(text="Release Red" if is_currently_forced_red_gui else "Force Red")
            return

        if approach_name in self.approach_widgets:
            override_button = self.approach_widgets[approach_name].get("override_button")
            if override_button and override_button.winfo_exists():
                override_button.config(text="Release Red" if new_override_state else "Force Red")
        
        action_str = "FORCED RED" if new_override_state else "RELEASED from manual red"
        print(f"[GUI] User toggled manual override for '{approach_name}' in '{intersection_name}' to: {action_str}")
        
        self._update_traffic_light_display()

    def _create_widgets(self):
        self.status_label.config(text="Preparing UI...")
        self.root.update()

        for widget in self.approaches_frame.winfo_children(): widget.destroy()
        self.approach_widgets.clear()
        for widget in self.traffic_light_frame.winfo_children(): widget.destroy()
        self.traffic_light_ui.clear()

        max_cols_approaches = config.UI_APPROACH_MONITOR_COLS
        active_approach_names = sorted(list(self.defined_polygons.keys()))
        
        approach_to_intersection_map = {}
        for int_name, int_data in self.controller.intersections.items():
            for managed_appr in int_data.get("managed_approaches", []):
                approach_to_intersection_map[managed_appr] = int_name

        for i, approach_name in enumerate(active_approach_names):
            video_path = next((path for name, path in config.VIDEO_PATHS if name == approach_name), "N/A")
            video_filename = os.path.basename(video_path)

            approach_outer_frame = ttk.Frame(self.approaches_frame, padding=0)
            row = i // max_cols_approaches
            col = i % max_cols_approaches
            approach_outer_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            approach_outer_frame.grid_rowconfigure(1, weight=1) 
            approach_outer_frame.grid_columnconfigure(0, weight=1) 
            self.approaches_frame.grid_columnconfigure(col, weight=1)

            approach_info_frame = ttk.LabelFrame(approach_outer_frame, text=f"{approach_name} ({video_filename})", padding="5")
            approach_info_frame.grid(row=0, column=0, sticky="new")
            approach_info_frame.grid_columnconfigure(0, weight=1) 
            approach_info_frame.grid_columnconfigure(1, weight=0) 

            vars_dict = {
                "status": tk.StringVar(value="Initializing..."),
                "frame_idx": tk.StringVar(value="Frame: -"),
                "agg_detect": tk.StringVar(value="Detected Now (All): 0"),
                "ambulance_status": tk.StringVar(value=""),
                "class_counts": {}
            }
            label_dict = {} 

            text_elements_frame = ttk.Frame(approach_info_frame)
            text_elements_frame.grid(row=0, column=0, sticky="nw")

            status_fg = "grey"; status_font = ("TkDefaultFont", config.DEFAULT_FONT_SIZE - 1, "italic")
            status_label_widget = ttk.Label(text_elements_frame, textvariable=vars_dict["status"], foreground=status_fg, font=status_font)
            status_label_widget.pack(anchor=tk.W)
            
            ambulance_label = ttk.Label(text_elements_frame, textvariable=vars_dict["ambulance_status"], foreground="red", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))
            ambulance_label.pack(anchor=tk.W)
            
            ttk.Label(text_elements_frame, textvariable=vars_dict["frame_idx"]).pack(anchor=tk.W, pady=1)
            ttk.Label(text_elements_frame, textvariable=vars_dict["agg_detect"], font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold")).pack(anchor=tk.W, pady=1)

            class_frame = ttk.Frame(text_elements_frame) 
            class_frame.pack(anchor=tk.W, fill=tk.X, pady=(5,0))
            for class_index, class_name_cfg in enumerate(config.TARGET_CLASSES):
                class_var = tk.StringVar(value=f"{class_name_cfg.title()}: 0")
                vars_dict["class_counts"][class_name_cfg] = class_var
                class_label_widget = ttk.Label(class_frame, textvariable=class_var, font=("TkDefaultFont", config.DEFAULT_FONT_SIZE - 1))
                label_col_cls = class_index % 2; label_row_cls = class_index // 2 
                class_label_widget.grid(row=label_row_cls, column=label_col_cls, sticky='w', padx=(0, 10))
                label_dict[class_name_cfg] = class_label_widget

            intersection_name_for_approach = approach_to_intersection_map.get(approach_name)
            override_button_widget = None
            if intersection_name_for_approach:
                initial_override_state = self.manual_overrides_gui_state.get(approach_name, False) 
                
                
                initial_button_text = "Release Red" if initial_override_state else "Force Red"
                
                override_button_cmd = partial(self._toggle_manual_override, intersection_name_for_approach, approach_name)
                override_button_widget = ttk.Button(approach_info_frame, text=initial_button_text, command=override_button_cmd, width=12)
                override_button_widget.grid(row=0, column=1, padx=(10,0), pady=(5,0), sticky="ne")
            
            plot_info = None
            if config.PLOT_ENABLE and MATPLOTLIB_AVAILABLE:
                try:
                    plot_frame = ttk.Frame(approach_outer_frame, borderwidth=1, relief="sunken")
                    plot_frame.grid(row=1, column=0, sticky="nsew", pady=(5, 0))

                    fig = Figure(figsize=(4, 2.2), dpi=85) 
                    ax = fig.add_subplot(111)
                    ax.set_title("Recent Count Trend", fontsize=8)
                    ax.set_ylabel("Count", fontsize=7)
                    ax.tick_params(axis='both', which='major', labelsize=6)
                    ax.grid(True, linestyle='--', alpha=0.6)
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                    fig.autofmt_xdate(rotation=30, ha='right')
                    fig.tight_layout(pad=0.8)

                    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
                    canvas_widget = canvas.get_tk_widget()
                    canvas_widget.pack(fill=tk.BOTH, expand=True)
                    canvas.draw()
                    plot_info = {'fig': fig, 'ax': ax, 'canvas': canvas}
                except Exception as plot_e:
                     print(f"[GUI Error] Failed to create plot for {approach_name}: {plot_e}")
                     ttk.Label(approach_outer_frame, text="Plot Error", foreground="red").grid(row=1, column=0, sticky="nsew", pady=(5,0))

            self.approach_widgets[approach_name] = {
                'frame': approach_info_frame, 'vars': vars_dict, 'status_label': status_label_widget,
                'ambulance_label': ambulance_label, 'class_labels': label_dict, 'plot': plot_info,
                'override_button': override_button_widget 
            }
        
        last_row_approaches = (len(active_approach_names) - 1) // max_cols_approaches if active_approach_names else -1
        if last_row_approaches >= 0:
             
             
            self.approaches_frame.grid_rowconfigure(last_row_approaches + 1, weight=1) 


        intersection_names = self.controller.get_intersection_names()
        for intersection_name_tl in intersection_names: 
            int_frame = ttk.Frame(self.traffic_light_frame, padding="5")
            int_frame.pack(pady=10, fill=tk.X) 
            ttk.Label(int_frame, text=f"{intersection_name_tl}:", font=("Helvetica", config.DEFAULT_FONT_SIZE + 1, "bold")).pack(anchor=tk.CENTER)
            
            initial_int_status = self.controller.get_intersection_status(intersection_name_tl)
            status_vars = { "phase": tk.StringVar(value=f"Phase: {initial_int_status.get('phase', 'N/A')}"),
                            "state": tk.StringVar(value=f"State: {initial_int_status.get('state', 'N/A')}"),
                            "timer": tk.StringVar(value=f"Timer: {initial_int_status.get('timer', 0.0):.1f}s"),
                            "progress": tk.DoubleVar(value=0.0),
                            "timer_widget": None, "progress_bar_widget": None }
            status_frame = ttk.Frame(int_frame)
            status_frame.pack(pady=5)
            ttk.Label(status_frame, textvariable=status_vars["phase"]).pack(side=tk.LEFT, padx=5)
            ttk.Label(status_frame, textvariable=status_vars["state"]).pack(side=tk.LEFT, padx=5)
            timer_label_widget = ttk.Label(status_frame, textvariable=status_vars["timer"])
            timer_label_widget.pack(side=tk.LEFT, padx=5)
            status_vars["timer_widget"] = timer_label_widget

            progress_bar = ttk.Progressbar(int_frame, orient="horizontal", length=200, mode="determinate", 
                                           variable=status_vars["progress"], style="default.Horizontal.TProgressbar")
            progress_bar.pack(pady=2, fill=tk.X, padx=10)
            status_vars["progress_bar_widget"] = progress_bar

            lights_frame = ttk.Frame(int_frame) 
            lights_frame.pack(pady=5, fill=tk.X, expand=True)
            self.traffic_light_ui[intersection_name_tl] = {"status_vars": status_vars, "approaches": {}}

            approaches_for_this_light = self.controller.get_approaches_for_intersection(intersection_name_tl)
            num_approaches_this_int = len(approaches_for_this_light)
            cols_this_int_lights = config.UI_TRAFFIC_LIGHT_COLS if num_approaches_this_int > 1 else 1
            initial_approach_statuses_all = self.controller.get_all_approach_statuses() 

            for idx_appr_tl, approach_name_iter_tl in enumerate(approaches_for_this_light): 
                 if approach_name_iter_tl not in self.defined_polygons: 
                     continue

                 approach_status_info = initial_approach_statuses_all.get(approach_name_iter_tl, {})
                 approach_ui_container_frame = ttk.Frame(lights_frame, borderwidth=1, relief="groove", padding=3)
                 grid_row_tl = idx_appr_tl // cols_this_int_lights; grid_col_tl = idx_appr_tl % cols_this_int_lights
                 approach_ui_container_frame.grid(row=grid_row_tl, column=grid_col_tl, padx=3, pady=3, sticky="nsew")
                 lights_frame.grid_columnconfigure(grid_col_tl, weight=1)

                 initial_light_state = approach_status_info.get('state', 'RED')
                 light_color = {'GREEN': 'green', 'YELLOW': 'yellow', 'RED': 'red'}.get(initial_light_state, 'grey')
                 light_canvas = tk.Canvas(approach_ui_container_frame, width=20, height=20, bg=light_color, highlightthickness=0)
                 light_canvas.pack(side=tk.LEFT, padx=(0,5))

                 demand_and_bar_frame = ttk.Frame(approach_ui_container_frame)
                 demand_and_bar_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))

                 demand_val_raw = approach_status_info.get('demand', 0)
                 demand_val_weighted = approach_status_info.get('weighted_demand', 0.0)
                 is_man_red = approach_status_info.get('is_manually_red', False)
                 
                 demand_var_text_val = f"{approach_name_iter_tl}\nDemand: {demand_val_raw} (W: {demand_val_weighted:.1f})"
                 if is_man_red: demand_var_text_val += "\n(MANUAL RED)"
                 demand_var = tk.StringVar(value=demand_var_text_val)
                 ttk.Label(demand_and_bar_frame, textvariable=demand_var, justify=tk.LEFT, font=("TkDefaultFont", config.DEFAULT_FONT_SIZE -1)).pack(anchor=tk.W)

                 demand_canvas = tk.Canvas(demand_and_bar_frame, width=50, height=10, bg="lightgrey", highlightthickness=0)
                 demand_canvas.pack(anchor=tk.W, pady=(2,0))
                 demand_bar = demand_canvas.create_rectangle(0, 0, 0, 10, fill="dodgerblue", outline="")
                 
                 self.traffic_light_ui[intersection_name_tl]["approaches"][approach_name_iter_tl] = {
                     "frame": approach_ui_container_frame, 
                     "canvas": light_canvas, "demand_var": demand_var,
                     "demand_bar_canvas": demand_canvas, "demand_bar_item": demand_bar
                 }
        print("[GUI] Widgets created.")
        self.root.update()


    def _start_processing(self):
        self.status_label.config(text="Starting Worker Processes...")
        print(f"[GUI] Starting parallel processing for {len(self.defined_polygons)} approaches...")
        self.root.update()
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"[GUI] Using device hint '{device}' for workers.")
        self.active_workers_initial_count = 0
        self.processes.clear()
        self.process_map.clear()
        self.finished_workers = 0
        self.final_summaries.clear()

        for approach_name, polygon in self.defined_polygons.items():
            video_path = next((path for name, path in config.VIDEO_PATHS if name == approach_name), None)
            if not video_path: print(f"[GUI Error] Missing video path for {approach_name}. Skipping."); continue
            
            p = mp.Process( target=process_video_worker, args=(
                    approach_name, video_path, config.MODEL_NAME, config.AMBULANCE_MODEL_NAME,
                    config.TARGET_CLASSES, config.AMBULANCE_CLASS_NAMES, config.CONFIDENCE_THRESHOLD,
                    config.PROCESS_EVERY_N_FRAMES, device, self.results_queue, polygon
                ), daemon=True )
            self.processes.append(p)
            try:
                 p.start(); self.process_map[p.pid] = approach_name
                 print(f"[GUI] Launched worker PID: {p.pid} for: {approach_name}")
                 self.active_workers_initial_count += 1
                 if approach_name in self.approach_widgets:
                     self.approach_widgets[approach_name]['vars']['status'].set("Processing...")
                     self.approach_widgets[approach_name]['status_label'].config(foreground="blue", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))
            except Exception as e:
                 print(f"[GUI Error] Failed to start process for {approach_name}: {e}"); traceback.print_exc()
                 if approach_name in self.approach_widgets:
                      self.approach_widgets[approach_name]['vars']['status'].set("ERROR: Start Failed")
                      self.approach_widgets[approach_name]['status_label'].config(foreground="red", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))

        if self.active_workers_initial_count == 0:
            messagebox.showerror("Error", "No worker processes started."); self.status_label.config(text="Error: No workers."); return

        self.status_label.config(text=f"Processing {self.active_workers_initial_count} approaches...")
        self._check_queue()
        self._run_traffic_logic_loop()
        if config.PLOT_ENABLE and MATPLOTLIB_AVAILABLE: self._update_plots()
        print("[GUI] Processing started.")

    def _check_queue(self):
        try:
            while True:
                result = self.results_queue.get_nowait()
                approach_name = result.get('approach', None)

                if approach_name and approach_name in self.approach_widgets:
                    widget_info = self.approach_widgets[approach_name]
                    vars_dict = widget_info['vars']
                    status_label = widget_info['status_label']
                    current_status_val = vars_dict['status'].get()
                    msg_type = result.get('type')

                    if msg_type == 'lane_update':
                        aggregate_count = result.get('in_lane_current_frame_agg', 0)
                        counts_by_type = result.get('counts_by_type', {}) 
                        ambulance_detected = result.get('ambulance_detected', False)
                        frame_idx = result.get('frame_index', '-')
                        timestamp = time.time() 

                        self.approach_history[approach_name].append((timestamp, aggregate_count)) 

                        if "Finished" not in current_status_val and "ERROR" not in current_status_val and "Paused" not in current_status_val:
                             vars_dict['frame_idx'].set(f"Frame: {frame_idx}")
                             vars_dict['agg_detect'].set(f"Detected Now (All): {aggregate_count}")
                             if "Processing" not in current_status_val:
                                 vars_dict['status'].set("Processing...")
                                 status_label.config(foreground="blue", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))

                        for class_name_ui in config.TARGET_CLASSES:
                            if class_name_ui in vars_dict['class_counts']:
                                count = counts_by_type.get(class_name_ui, 0)
                                vars_dict['class_counts'][class_name_ui].set(f"{class_name_ui.title()}: {count}")

                        vars_dict['ambulance_status'].set("AMBULANCE!" if ambulance_detected else "")
                        
                        self.controller.update_demand(approach_name, aggregate_count, timestamp, ambulance_detected)
                        self.controller.update_weighted_demand(approach_name, counts_by_type, timestamp)


                    elif msg_type == 'status_update':
                         new_status = result.get('status', 'Unknown')
                         if "Finished" not in current_status_val and "ERROR" not in current_status_val:
                             vars_dict['status'].set(new_status)
                             if "Paused" in new_status: status_label.config(foreground="orange", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE - 1, "italic"))
                             elif "Processing" in new_status: status_label.config(foreground="blue", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))
                             else: status_label.config(foreground="grey", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE - 1, "italic"))
                    elif msg_type == 'final_summary':
                        print(f"[GUI] Received final summary for: {approach_name}")
                        self.final_summaries[approach_name] = result; self.finished_workers += 1
                        vars_dict['status'].set("Finished OK"); vars_dict['agg_detect'].set("Detected Now (All): 0")
                        vars_dict['ambulance_status'].set("")
                        for class_name_ui in config.TARGET_CLASSES:
                             if class_name_ui in vars_dict['class_counts']: vars_dict['class_counts'][class_name_ui].set(f"{class_name_ui.title()}: 0")
                        status_label.config(foreground="green", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))
                    elif msg_type == 'error':
                        print(f"[GUI Error] Received error for: {approach_name} - {result.get('message', 'Unknown error')}")
                        self.final_summaries[approach_name] = result; self.finished_workers += 1
                        error_msg_short = str(result.get('message', 'Unknown error'))[:40] + '...'; vars_dict['status'].set(f"ERROR: {error_msg_short}")
                        vars_dict['ambulance_status'].set(""); status_label.config(foreground="red", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))

        except Empty: self._check_dead_processes()

        if self.active_workers_initial_count > 0 and self.finished_workers >= self.active_workers_initial_count:
            self.status_label.config(text=f"All {self.active_workers_initial_count} video processing tasks finished.")
            print("[GUI] All worker processes accounted for.")
            
            
            self.display_final_summaries() 
        
        self.root.after(config.QUEUE_CHECK_INTERVAL_MS, self._check_queue)


    def _check_dead_processes(self):
        if self.finished_workers < self.active_workers_initial_count:
            pids_to_check = list(self.process_map.keys())
            active_pids = {p.pid for p in self.processes if p.is_alive()}
            for pid in pids_to_check:
                 if pid not in active_pids:
                     if pid in self.process_map:
                         dead_approach_name = self.process_map[pid]
                         if dead_approach_name not in self.final_summaries:
                             print(f"\n!!! [GUI Error] Worker PID {pid} for {dead_approach_name} terminated unexpectedly. !!!")
                             self.final_summaries[dead_approach_name] = {'type':'error', 'error': 'Process terminated unexpectedly', 'approach': dead_approach_name}
                             self.finished_workers += 1
                             if dead_approach_name in self.approach_widgets:
                                 self.approach_widgets[dead_approach_name]['vars']['status'].set("ERROR: Terminated")
                                 self.approach_widgets[dead_approach_name]['status_label'].config(foreground="red", font=("TkDefaultFont", config.DEFAULT_FONT_SIZE, "bold"))
                                 self.approach_widgets[dead_approach_name]['vars']['ambulance_status'].set("")
                         del self.process_map[pid]


    def _run_traffic_logic_loop(self):
        state_changed = self.controller.update_state(time.time())
        self._update_traffic_light_display()
        self.traffic_logic_timer_id = self.root.after(config.TRAFFIC_LOGIC_UPDATE_INTERVAL_MS, self._run_traffic_logic_loop)



    def _update_traffic_light_display(self):
        all_approach_statuses = self.controller.get_all_approach_statuses()
        intersection_names = self.controller.get_intersection_names()
        light_color_map = {'GREEN': 'green', 'YELLOW': 'yellow', 'RED': 'red'}

        for int_name in intersection_names:
            if int_name not in self.traffic_light_ui: continue
            ui_info = self.traffic_light_ui[int_name]
            int_status = self.controller.get_intersection_status(int_name)

            current_intersection_gui_state = int_status.get('state', 'N/A')
            ui_info['status_vars']['phase'].set(f"Phase: {int_status.get('phase', 'N/A')}")
            ui_info['status_vars']['state'].set(f"State: {current_intersection_gui_state}")
            timer_val = int_status.get('timer', 0.0)
            timer_text = f"Timer: {timer_val:.1f}s"
            if int_status.get('is_emergency', False): timer_text += " (EMERGENCY)"
            ui_info['status_vars']['timer'].set(timer_text)

            timer_widget = ui_info['status_vars'].get("timer_widget")
            progress_bar_widget = ui_info['status_vars'].get("progress_bar_widget")

            pb_style_to_apply = "default.Horizontal.TProgressbar"
            timer_fg_color = "black"

            if current_intersection_gui_state == "YELLOW":
                timer_fg_color = "darkorange"; pb_style_to_apply = "yellow.Horizontal.TProgressbar"
            elif current_intersection_gui_state == "ALL_RED":
                timer_fg_color = "red"; pb_style_to_apply = "red.Horizontal.TProgressbar"
            elif current_intersection_gui_state == "GREEN":
                timer_fg_color = "forest green"; pb_style_to_apply = "green.Horizontal.TProgressbar"

            if timer_widget and timer_widget.winfo_exists(): timer_widget.config(foreground=timer_fg_color)
            if progress_bar_widget and progress_bar_widget.winfo_exists(): progress_bar_widget.configure(style=pb_style_to_apply)

            max_duration = int_status.get('max_duration', 0.0)
            progress_percent = min(max(timer_val, 0) / max_duration, 1.0) * 100 if max_duration > 0 else 0
            ui_info['status_vars']['progress'].set(progress_percent)

            for approach_name, approach_ui_elems in ui_info['approaches'].items():
                approach_status = all_approach_statuses.get(approach_name, {})
                current_light_state_from_logic = approach_status.get('state', 'RED')
                current_raw_demand = approach_status.get('demand', 0)
                current_weighted_demand = approach_status.get('weighted_demand', 0.0)
                amb_req = approach_status.get('ambulance_request_active', False)
                is_man_red_from_logic = approach_status.get('is_manually_red', False)

                demand_text_tl = f"{approach_name}\nDemand: {current_raw_demand} (W: {current_weighted_demand:.1f})"
                if amb_req: demand_text_tl += "\n(AMB REQ!)"
                if is_man_red_from_logic: demand_text_tl += "\n(MANUAL RED)"
                approach_ui_elems['demand_var'].set(demand_text_tl)

                new_color = light_color_map.get(current_light_state_from_logic, 'grey')
                if approach_ui_elems.get('canvas') and approach_ui_elems['canvas'].winfo_exists():
                    if approach_ui_elems['canvas'].cget('bg') != new_color:
                        approach_ui_elems['canvas'].config(bg=new_color)

                demand_canvas = approach_ui_elems.get('demand_bar_canvas')
                bar_item = approach_ui_elems.get('demand_bar_item')
                if demand_canvas and bar_item and demand_canvas.winfo_exists():
                    try:
                        max_demand_vis_raw = 20
                        bar_fill_value = current_raw_demand
                        bar_width = min(50, (bar_fill_value / max_demand_vis_raw) * 50) if bar_fill_value > 0 else 0
                        bar_width = max(0, bar_width)
                        demand_canvas.coords(bar_item, 0, 0, bar_width, 10)
                    except tk.TclError: pass
        
       
        for approach_name_stat, stat_widget_info in self.approach_widgets.items():
            approach_status_stat = all_approach_statuses.get(approach_name_stat, {})
            is_man_red_stat = approach_status_stat.get('is_manually_red', False)
            override_button_stat = stat_widget_info.get("override_button")
            if override_button_stat and override_button_stat.winfo_exists():
                expected_button_text_stat = "Release Red" if is_man_red_stat else "Force Red"
                if override_button_stat.cget("text") != expected_button_text_stat:
                    override_button_stat.config(text=expected_button_text_stat)
            
            self.manual_overrides_gui_state[approach_name_stat] = is_man_red_stat


        if self.esp32_controller and self.esp32_controller.is_connected:
            current_statuses_for_esp = self.controller.get_all_approach_statuses()
            if current_statuses_for_esp:
                esp_light_states = {appr: {'state': data['state']} for appr, data in current_statuses_for_esp.items()}
                self.esp32_controller.update_lights(esp_light_states)




    def _update_plots(self):
        if not config.PLOT_ENABLE or not MATPLOTLIB_AVAILABLE:
             return 

        try:
            current_time = time.time()
            history_cutoff_time = current_time - config.PLOT_HISTORY_SECONDS

            for approach_name, widget_info in self.approach_widgets.items():
                 plot_info = widget_info.get('plot')
                 if not plot_info: continue 

                 ax = plot_info['ax']
                 canvas = plot_info['canvas']
                 history_deque = self.approach_history.get(approach_name)

                 if not history_deque: continue 

                 plot_data = [(dt.datetime.fromtimestamp(ts), count) for ts, count in list(history_deque) if ts >= history_cutoff_time]

                 ax.clear() 

                 if plot_data:
                     timestamps, counts = zip(*plot_data)
                     ax.plot(timestamps, counts, marker='.', linestyle='-', markersize=3, color='tab:blue')
                     ax.set_ylim(bottom=-0.5) 
                     max_count = max(counts) if counts else 0
                     ax.set_ylim(top=max(max_count * 1.2, 5)) 
                 else:
                     now_dt = dt.datetime.fromtimestamp(current_time)
                     then_dt = dt.datetime.fromtimestamp(history_cutoff_time)
                     ax.plot([then_dt, now_dt], [0, 0], color='grey', alpha=0) 
                     ax.set_ylim(0, 5)
                     ax.text(0.5, 0.5, 'No data in window', horizontalalignment='center', verticalalignment='center', transform=ax.transAxes, fontsize=8, color='grey')

                 ax.set_title("Recent Count Trend", fontsize=9, pad=2)
                 ax.set_ylabel("Count", fontsize=8)
                 ax.tick_params(axis='x', labelsize=7)
                 ax.tick_params(axis='y', labelsize=7)
                 ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                 ax.grid(True, linestyle=':', linewidth=0.5, alpha=0.7) 
                 plot_info['fig'].tight_layout(pad=0.8) 

                 canvas.draw() 

        except Exception as e:
            print(f"[GUI Plot Error] Failed to update plots: {e}")

        self.plot_update_timer_id = self.root.after(config.PLOT_UPDATE_INTERVAL_MS, self._update_plots)


    def display_final_summaries(self):
        summary_window = tk.Toplevel(self.root)
        summary_window.title("Final Summaries (Per Approach)")
        try:
            self.root.update_idletasks(); parent_geo_str = self.root.geometry(); parent_geo = parent_geo_str.split('+')
            parent_w_h = parent_geo[0].split('x'); parent_w, parent_h = int(parent_w_h[0]), int(parent_w_h[1])
            parent_x, parent_y = int(parent_geo[1]), int(parent_geo[2]); win_w, win_h = 750, 650
            x = parent_x + (parent_w // 2) - (win_w // 2); y = parent_y + (parent_h // 2) - (win_h // 2)
            x = max(0, x); y = max(0, y); summary_window.geometry(f"{win_w}x{win_h}+{x}+{y}")
        except Exception as e: print(f"[GUI] Could not center summary window: {e}"); summary_window.geometry("750x650")
        summary_window.grab_set()
        text_area = scrolledtext.ScrolledText(summary_window, wrap=tk.WORD, width=90, height=35, font=("Courier New", 10))
        text_area.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        summary_text = "==================== FINAL SUMMARIES (Per Approach) ====================\n\n"
        processed_ok_count = 0; processed_err_count = 0; missing_summary_count = 0
        skipped_approach_names = set(self.skipped_approaches)
        skipped_count = len(skipped_approach_names)
        defined_polygons_set = set(self.defined_polygons.keys())

        for approach_name_sum, video_path_sum in config.VIDEO_PATHS:
            filename_base = os.path.basename(video_path_sum)
            summary_text += f"--- Summary for Approach: {approach_name_sum} ({filename_base}) ---\n"

            if approach_name_sum in skipped_approach_names:
                summary_text += "  STATUS: Skipped (Initialization/Polygon definition failed or skipped)\n\n"
            elif approach_name_sum not in defined_polygons_set:
                summary_text += "  STATUS: Not Processed (No polygon defined or filtered out)\n\n"
            elif approach_name_sum in self.final_summaries:
                data = self.final_summaries[approach_name_sum]
                if data.get('type') == 'error' or data.get('error'):
                    summary_text += f"  STATUS: ERROR\n"; summary_text += f"  Message: {data.get('error', data.get('message', 'Unknown Error'))}\n\n"
                    processed_err_count += 1
                elif data.get('type') == 'final_summary':
                    summary_text += f"  STATUS: Completed OK\n"
                    summary_text += f"  Total frames read: {data.get('total_frames_read', 'N/A')}\n"
                    summary_text += f"  Frames processed: {data.get('processed_frames_counted', 'N/A')} (Every {config.PROCESS_EVERY_N_FRAMES})\n"
                    summary_text += f"  Vehicles IN LANE (Total Agg): {data.get('total_vehicles_in_lane_agg', 'N/A')}\n"
                    total_counts_by_type = data.get('total_counts_by_type', {})
                    if total_counts_by_type:
                         summary_text += "  Total Counts by Type (In Lane):\n"
                         for class_key, count_val in sorted(total_counts_by_type.items()): summary_text += f"    - {class_key.title()}: {count_val}\n"
                    else: summary_text += "  Total Counts by Type (In Lane): None Recorded\n"
                    summary_text += f"  General Vehicles Outside Lane: {data.get('total_general_detections_outside_lane', 'N/A')}\n"
                    summary_text += f"  Ambulances Detected Outside Lane: {data.get('total_ambulances_outside_lane', 'N/A')}\n"
                    proc_time = data.get('processing_time_sec', 0)
                    summary_text += f"  Processing time: {proc_time:.2f} sec\n"
                    avg_read_fps = data.get('avg_reading_fps', 0); avg_proc_fps = data.get('avg_processing_rate_fps', 0)
                    summary_text += f"  Avg reading FPS: {avg_read_fps:.2f}\n"; summary_text += f"  Avg processing rate: {avg_proc_fps:.2f} fps\n\n"
                    processed_ok_count += 1
                else: 
                    summary_text += f"  STATUS: Incomplete Final Data\n"; summary_text += f"  Data Received: {str(data)[:150]}...\n\n"
                    processed_err_count += 1 
            else:
                 summary_text += f"  STATUS: Missing Final Summary (Process might have crashed/terminated)\n\n"
                 missing_summary_count += 1

        summary_text += "----------------------------------------------------------------------\n"
        summary_text += f"Overall Processed: {processed_ok_count} OK, {processed_err_count} Error, {missing_summary_count} Missing Summary. Skipped Initially: {skipped_count}.\n"
        summary_text += "======================================================================\n"

        text_area.insert(tk.INSERT, summary_text); text_area.config(state=tk.DISABLED)
        close_button = ttk.Button(summary_window, text="Close", command=summary_window.destroy)
        close_button.pack(pady=10)


    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? This will stop processing and traffic simulation."):
            print("[GUI] Termination requested by user.")

            if self.traffic_logic_timer_id:
                try: self.root.after_cancel(self.traffic_logic_timer_id); print("[GUI] Cancelled traffic logic timer.")
                except: pass
            if self.plot_update_timer_id:
                try: self.root.after_cancel(self.plot_update_timer_id); print("[GUI] Cancelled plot update timer.")
                except: pass
            self.traffic_logic_timer_id = None
            self.plot_update_timer_id = None

            if self.esp32_controller:
                print("[GUI] Closing ESP32 connection...")
                try:
                    self.esp32_controller.close()
                    print("[GUI] ESP32 connection closed.")
                except Exception as e_esp_close:
                    print(f"[GUI Error] Error closing ESP32 connection: {e_esp_close}")

            active_processes = [p for p in self.processes if p.is_alive()]
            if active_processes:
                 print(f"[GUI] Terminating {len(active_processes)} worker process(es)...")
                 for p in active_processes:
                     try: p.terminate(); p.join(timeout=1.0)
                     except Exception as e: print(f"[GUI] Error terminating PID {p.pid if p else '?'}: {e}")

            try: 
                if hasattr(self.manager, '_process') and self.manager._process and self.manager._process.is_alive():
                    print("[GUI] Shutting down manager..."); self.manager.shutdown(); print("[GUI] Manager shut down.")
                elif not hasattr(self.manager, '_process') or not self.manager._process:
                     print("[GUI] Manager shutdown (no process attribute or process already down).")
                else: 
                     print("[GUI] Manager already shut down or not in expected state.")


            except Exception as e: print(f"[GUI Error] shutting down manager: {e}")

            self.root.destroy()
            print("[GUI] Application closed.")