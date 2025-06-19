VERSION = "3.6 (Weighted Green Time)"
MODEL_NAME = "yoloe-11m-seg.pt"
AMBULANCE_MODEL_NAME = "C:\\Users\\harish\\Downloads\\last.pt"
AMBULANCE_CLASS_NAMES = ["ambulance","ambulanceSiren"]
TARGET_CLASSES = [
    'Bicycle',  'Motorcycle',
    'bus', 'car', 'mini truck', 'truck'
 ]
CONFIDENCE_THRESHOLD = 0.1
PROCESS_EVERY_N_FRAMES = 5
VEHICLE_TYPE_WEIGHTS = {
    'bus': 3.0,
    'truck': 2.0,
    'mini truck': 1.5,
    'car': 1.0,
    'Motorcycle': 0.75,
    'Bicycle': 0.5,
}
DEFAULT_VEHICLE_WEIGHT = 1.0
VIDEO_PATHS = [
    ("Northbound", "C:\\Users\\Harish\\Downloads\\vids\\vid1.mp4"),
    ("Eastbound","C:\\Users\\Harish\\Downloads\\vids\\crowd.mp4"),
    ("Westbound", "C:\\Users\\Harish\\Downloads\\vids\\amb2.mp4"),
    ("Southbound", "C:\\Users\\Harish\\Downloads\\vids\\vid4.mp4"),
]
TRAFFIC_LIGHT_CONFIG = {
    "Intersection1": {
        "phases": {
            "GreenForNorth": ["Northbound"],
            "GreenForEast": ["Eastbound"],
            "GreenForWest": ["Westbound"],
            "GreenForSouth": ["Southbound"]
        },
        "timings": {
            "min_green": 8,
            "yellow": 3,
            "all_red": 1,
            "gap_time": 3.5,
            "skip_threshold": 2.0,
            "emergency_green": 12,
            "ambulance_request_timeout": 8.0,
            "base_max_green": 20,
            "queued_weighted_demand_extension_factor": 0.5,
            "absolute_max_green": 45,
            "realtime_flow_extension_increment": 1.5,
            "realtime_flow_min_weighted_demand": 2.5,
        },
        "demand_threshold": 3.0
    },
}
QUEUE_CHECK_INTERVAL_MS = 100
TRAFFIC_LOGIC_UPDATE_INTERVAL_MS = 500
PLOT_UPDATE_INTERVAL_MS = 2000
DEFAULT_FONT_SIZE = 10
INITIAL_WINDOW_WIDTH = 1250
INITIAL_WINDOW_HEIGHT = 850
UI_COLUMN_WEIGHT_TRAFFIC_LIGHT = 3
UI_COLUMN_WEIGHT_APPROACH_MONITOR = 4
UI_APPROACH_MONITOR_COLS = 2
UI_TRAFFIC_LIGHT_COLS = 2
PLOT_HISTORY_SECONDS = 60
PLOT_MAX_POINTS = int((PLOT_HISTORY_SECONDS * 1000) / max(1, QUEUE_CHECK_INTERVAL_MS))
PLOT_ENABLE = True
ESP32_ENABLED = False
ESP32_PORT = "COM3"
ESP32_BAUDRATE = 115200
ESP32_APPROACH_MAPPING = {
    "Northbound": "N",
    "Eastbound": "E",
    "Westbound": "W",
    "Southbound": "S"
}