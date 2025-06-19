import cv2
import numpy as np
import os


_current_points_list = []
_frame_display = None
_original_frame = None
_window_name_global = ""

def draw_polygon_callback(event, x, y, flags, param):
    
    global _current_points_list, _frame_display, _window_name_global

    if _frame_display is None: return 

    if event == cv2.EVENT_LBUTTONDOWN:
        _current_points_list.append((x, y))
        
        cv2.circle(_frame_display, (x, y), 5, (0, 255, 0), -1) 
        if len(_current_points_list) > 1:
            
            cv2.line(_frame_display, _current_points_list[-2], _current_points_list[-1], (255, 255, 0), 2) 
        
        if len(_current_points_list) >= 3:
             cv2.line(_frame_display, _current_points_list[-1], _current_points_list[0], (0, 165, 255), 1) 

        cv2.imshow(_window_name_global, _frame_display)

def define_polygon_interactive(approach_name, video_path):
    
    global _current_points_list, _frame_display, _original_frame, _window_name_global

    video_filename = os.path.basename(video_path)
    window_name = f"Define Polygon for {approach_name} ({video_filename})"
    _window_name_global = window_name 

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[Polygon] Error: Could not open video file: {video_path}")
        return None

    ret, frame = cap.read()
    if not ret or frame is None:
        print(f"[Polygon] Error: Could not read first frame from: {video_path}")
        cap.release()
        return None

    _original_frame = frame.copy()
    _frame_display = frame.copy()
    _current_points_list = [] 

    
    font = cv2.FONT_HERSHEY_SIMPLEX
    instructions1 = "LClick=Add Point | RClick=Undo Last"
    instructions2 = "'d'/Enter=Done | 'r'=Reset | 'q'/Esc=Skip"
    y0, dy = 30, 30
    
    cv2.putText(_frame_display, instructions1, (10, y0), font, 0.6, (0, 0, 0), 3, cv2.LINE_AA) 
    cv2.putText(_frame_display, instructions1, (10, y0), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA) 
    cv2.putText(_frame_display, instructions2, (10, y0 + dy), font, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(_frame_display, instructions2, (10, y0 + dy), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.namedWindow(window_name)
    
    cv2.setMouseCallback(window_name, draw_polygon_callback) 

    print(f"\n--- Defining polygon for approach '{approach_name}' ({video_filename}) ---")
    print(f" INSTRUCTIONS: {instructions1} | {instructions2}")

    while True:
        cv2.imshow(window_name, _frame_display)
        key = cv2.waitKey(20) & 0xFF

        
        if key == ord('d') or key == 13:
            if len(_current_points_list) >= 3:
                print(f" -> Polygon defined for {approach_name} with {_current_points_list}")
                cap.release()
                cv2.destroyWindow(window_name)
                
                polygon_array = np.array(_current_points_list, dtype=np.int32).reshape(-1, 1, 2) 
                polygon_array = np.array(_current_points_list, dtype=np.int32) 
                
                _current_points_list = []
                _frame_display = None
                _original_frame = None
                _window_name_global = ""
                return polygon_array
            else:
                print(" -> Error: Need at least 3 points to define a polygon.")
                

        
        elif key == ord('r'):
            print(" -> Resetting points.")
            _current_points_list.clear()
            
            _frame_display = _original_frame.copy()
            cv2.putText(_frame_display, instructions1, (10, y0), font, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(_frame_display, instructions1, (10, y0), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(_frame_display, instructions2, (10, y0 + dy), font, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(_frame_display, instructions2, (10, y0 + dy), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)


        
        elif key == ord('q') or key == 27:
            print(f" -> Skipped defining polygon for {approach_name}")
            cap.release()
            cv2.destroyWindow(window_name)
            
            _current_points_list = []
            _frame_display = None
            _original_frame = None
            _window_name_global = ""
            return None

        
        
        
        
        elif key == ord('u'):
            if _current_points_list:
                 print(" -> Undoing last point.")
                 _current_points_list.pop()
                 
                 _frame_display = _original_frame.copy()
                 cv2.putText(_frame_display, instructions1, (10, y0), font, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
                 cv2.putText(_frame_display, instructions1, (10, y0), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
                 cv2.putText(_frame_display, instructions2, (10, y0 + dy), font, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
                 cv2.putText(_frame_display, instructions2, (10, y0 + dy), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
                 
                 for i, point in enumerate(_current_points_list):
                      cv2.circle(_frame_display, point, 5, (0, 255, 0), -1)
                      if i > 0:
                          cv2.line(_frame_display, _current_points_list[i-1], point, (255, 255, 0), 2)
                 if len(_current_points_list) >= 3:
                      cv2.line(_frame_display, _current_points_list[-1], _current_points_list[0], (0, 165, 255), 1)
            else:
                 print(" -> No points to undo.")


    
    cap.release()
    cv2.destroyWindow(window_name)
    _current_points_list = []
    _frame_display = None
    _original_frame = None
    _window_name_global = ""
    return None