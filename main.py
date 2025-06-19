import tkinter as tk
import multiprocessing as mp
import os
import sys
import cv2 
from gui import LaneCounterApp

if __name__ == '__main__':
    
    try:
        
        current_method = mp.get_start_method(allow_none=True)
        if current_method is None:
             mp.set_start_method('spawn', force=True)
             print("[Main] Set multiprocessing start method to 'spawn'.")
        elif current_method != 'spawn':
             
             try:
                 mp.set_start_method('spawn', force=True)
                 print("[Main] Forcing multiprocessing start method to 'spawn'.")
             except RuntimeError as re:
                 print(f"[Main] Warning: Could not force 'spawn' ({re}). Using existing '{current_method}'.")
        else:
            print(f"[Main] Multiprocessing start method already set to 'spawn'.")
    except Exception as e: 
        print(f"[Main] Warning: Issue setting start method ('{mp.get_start_method(allow_none=True)}'): {e}.")


    if os.name == 'nt':
        try:
            from ctypes import windll
            
            PROCESS_SYSTEM_DPI_AWARE = 1
            windll.shcore.SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE)
            print("[Main] Set DPI Awareness (shcore System Aware)")
        except (ImportError, AttributeError, OSError):
            try:
                
                windll.user32.SetProcessDPIAware()
                print("[Main] Set DPI Awareness (user32)")
            except Exception as e2:
                 print(f"[Main] Could not set DPI awareness: {e2}")

    
    root = tk.Tk()
    app = LaneCounterApp(root) 

    
    
    if app.initialize_application(): 
         print("[Main] Initialization complete. Starting main loop...")
         root.mainloop() 
         print("[Main] Main loop exited.")
    else:
        print("[Main] Application initialization failed or was cancelled. Exiting.")
        
        try:
            root.destroy()
        except tk.TclError:
            pass 
    cv2.destroyAllWindows()
    print("[Main] Script finished.")