import os
import time
import traceback
import sys
import numpy as np
import cv2
import torch
from ultralytics import YOLOE 
from collections import defaultdict

def process_video_worker(
    approach_name,
    video_path,
    general_model_name,
    ambulance_model_name,
    target_classes, 
    ambulance_class_names, 
    conf_threshold,
    process_every_n,
    device_str,
    results_queue,
    lane_polygon
    
):
    process_id = os.getpid()
    video_filename = os.path.basename(video_path)
    general_model = None
    ambulance_model = None
    print(f"[Worker {process_id} | {approach_name}] Starting for video: {video_filename}")

    
    if isinstance(target_classes, str):
        target_classes_list = [target_classes]
    else:
        target_classes_list = list(target_classes)

    if isinstance(ambulance_class_names, str):
        ambulance_classes_list = [ambulance_class_names]
    elif ambulance_class_names is None:
        ambulance_classes_list = []
    else:
        ambulance_classes_list = list(ambulance_class_names)

    
    if not isinstance(lane_polygon, np.ndarray) or lane_polygon.ndim != 2 or lane_polygon.shape[1] != 2:
         error_msg = f"Invalid lane polygon format for {approach_name}. Expected Nx2 numpy array."
         print(f"[Worker {process_id} | {approach_name}] Error: {error_msg}")
         results_queue.put({'type': 'error','approach': approach_name, 'filename': video_filename,'message': error_msg})
         return 

    
    try:
        print(f"[Worker {process_id} | {approach_name}] Loading general model '{general_model_name}' onto '{device_str}'...")
        general_model = YOLOE(general_model_name)
        general_model.to(device_str)
        if target_classes_list:
            print(f"[Worker {process_id} | {approach_name}] Setting general model classes using text embeddings for: {target_classes_list}")
            general_text_embeddings = general_model.get_text_pe(target_classes_list)
            general_model.set_classes(target_classes_list, general_text_embeddings)
        else:
             print(f"[Worker {process_id} | {approach_name}] No target classes specified for general model.")

        if ambulance_model_name and ambulance_classes_list:
            print(f"[Worker {process_id} | {approach_name}] Loading ambulance model '{ambulance_model_name}' onto '{device_str}'...")
            
            ambulance_model = YOLOE(ambulance_model_name)
            ambulance_model.to(device_str)
            print(f"[Worker {process_id} | {approach_name}] Ambulance model loaded. Predictions will be filtered for classes: {ambulance_classes_list}")
        elif not ambulance_model_name and ambulance_classes_list:
            print(f"[Worker {process_id} | {approach_name}] Ambulance classes defined but no model name provided. Skipping.")
            ambulance_model = None
        else:
            print(f"[Worker {process_id} | {approach_name}] No ambulance classes specified. Skipping ambulance model load.")
            ambulance_model = None

        print(f"[Worker {process_id} | {approach_name}] Model loading sequence complete.")
        
        results_queue.put({'type': 'status_update', 'approach': approach_name, 'status': 'Models Loaded'})
        

    except Exception as e_init:
        print(f"\n!!! [Worker {process_id} | {approach_name}] MODEL INIT ERROR: {e_init} !!!")
        traceback.print_exc()
        error_message = f"Model initialization failed: {e_init}"
        results_queue.put({'type': 'error', 'approach': approach_name, 'filename': video_filename, 'message': error_message})
        return 

    
    frame_index = -1
    total_counts_by_type_in_lane = defaultdict(int) 
    total_general_detections_outside_lane = 0
    total_ambulance_detections_outside_lane = 0 
    processed_frames_overall = 0
    processing_start_time = time.time()
    video_processed_flag = False 
    error_occurred = False

    try:
        if not os.path.exists(video_path):
             raise FileNotFoundError(f"Video file not found: {video_path}")

        
        results_queue.put({'type': 'status_update', 'approach': approach_name, 'status': 'Processing...'})

        general_results_generator = general_model.predict(video_path, conf=conf_threshold, stream=True, device=device_str, verbose=False)
        video_processed_flag = True
        print(f"[Worker {process_id} | {approach_name}] Starting prediction stream for general model...")

        for general_results_for_frame in general_results_generator:
            

            
            frame_index += 1
            ambulance_detected_this_frame_in_lane = False 

            if process_every_n <= 1 or frame_index % process_every_n == 0:
                processed_frames_overall += 1
                detected_in_lane_agg_this_frame = 0
                detected_counts_by_type_this_frame = defaultdict(int)
                current_frame_image = general_results_for_frame.orig_img

                
                if general_results_for_frame.boxes is not None and hasattr(general_results_for_frame, 'names'):
                    gen_model_class_map = general_results_for_frame.names
                    boxes = general_results_for_frame.boxes.xyxy.cpu().numpy()
                    class_indices = general_results_for_frame.boxes.cls.cpu().numpy().astype(int)
                    for i, box in enumerate(boxes):
                        class_idx = class_indices[i]; class_name_detected = gen_model_class_map.get(class_idx, None)
                        if class_name_detected and class_name_detected in target_classes_list:
                             x1, y1, x2, y2 = box[:4]; ref_x = int((x1 + x2) / 2); ref_y = int(y2)
                             if cv2.pointPolygonTest(lane_polygon, (ref_x, ref_y), False) >= 0:
                                 detected_in_lane_agg_this_frame += 1
                                 detected_counts_by_type_this_frame[class_name_detected] += 1
                                 total_counts_by_type_in_lane[class_name_detected] += 1
                             else: total_general_detections_outside_lane += 1

                
                if ambulance_model and ambulance_classes_list:
                    ambulance_model_results_list = ambulance_model.predict(current_frame_image, conf=conf_threshold, device=device_str, verbose=False)
                    if ambulance_model_results_list and isinstance(ambulance_model_results_list, list):
                        ambulance_results_for_frame = ambulance_model_results_list[0]
                        if ambulance_results_for_frame.boxes is not None and hasattr(ambulance_results_for_frame, 'names'):
                            amb_model_class_map = ambulance_results_for_frame.names
                            amb_boxes = ambulance_results_for_frame.boxes.xyxy.cpu().numpy()
                            amb_class_indices = ambulance_results_for_frame.boxes.cls.cpu().numpy().astype(int)
                            for i_amb, box_amb in enumerate(amb_boxes):
                                amb_class_idx = amb_class_indices[i_amb]; amb_class_name_detected = amb_model_class_map.get(amb_class_idx, None)
                                if amb_class_name_detected and amb_class_name_detected in ambulance_classes_list:
                                    x1_amb, y1_amb, x2_amb, y2_amb = box_amb[:4]; ref_x_amb = int((x1_amb + x2_amb) / 2); ref_y_amb = int(y2_amb)
                                    if cv2.pointPolygonTest(lane_polygon, (ref_x_amb, ref_y_amb), False) >= 0:
                                        ambulance_detected_this_frame_in_lane = True; break
                                    else: total_ambulance_detections_outside_lane += 1

                
                results_queue.put({
                    'type': 'lane_update',
                    'approach': approach_name,
                    'filename': video_filename,
                    'frame_index': frame_index,
                    'in_lane_current_frame_agg': detected_in_lane_agg_this_frame,
                    'counts_by_type': dict(detected_counts_by_type_this_frame),
                    'ambulance_detected': ambulance_detected_this_frame_in_lane
                })

    except FileNotFoundError as fnf_error:
        print(f"\n!!! [Worker {process_id} | {approach_name}] FNF ERROR: {fnf_error} !!!")
        error_occurred = True
        results_queue.put({'type': 'error', 'approach': approach_name, 'filename': video_filename, 'message': str(fnf_error)})
    except StopIteration:
        print(f"[Worker {process_id} | {approach_name}] Video stream ended (StopIteration). Normal.")
    except Exception as e_proc:
        print(f"\n!!! [Worker {process_id} | {approach_name}] PROCESSING ERROR: {e_proc} !!!")
        traceback.print_exc()
        error_occurred = True
        results_queue.put({'type': 'error', 'approach': approach_name, 'filename': video_filename, 'message': f"Processing error: {e_proc}"})
    finally:
        processing_end_time = time.time(); total_processing_duration = processing_end_time - processing_start_time
        actual_frames_read = frame_index + 1 if frame_index >= 0 else 0
        avg_reading_fps = actual_frames_read / total_processing_duration if total_processing_duration > 0.01 else 0
        avg_processing_rate_fps = processed_frames_overall / total_processing_duration if total_processing_duration > 0.01 else 0
        total_aggregate_general_vehicles_in_lane = sum(total_counts_by_type_in_lane.values())

        if not error_occurred and video_processed_flag :
            summary_data = {
                'type': 'final_summary', 'approach': approach_name, 'filename': video_filename,
                'total_frames_read': actual_frames_read, 'processed_frames_counted': processed_frames_overall,
                'total_vehicles_in_lane_agg': total_aggregate_general_vehicles_in_lane,
                'total_counts_by_type': dict(total_counts_by_type_in_lane),
                'total_general_vehicles_outside_lane': total_general_detections_outside_lane,
                'total_ambulances_outside_lane': total_ambulance_detections_outside_lane,
                'processing_time_sec': total_processing_duration,
                'avg_reading_fps': avg_reading_fps, 'avg_processing_rate_fps': avg_processing_rate_fps
            }
            results_queue.put(summary_data)
            print(f"[Worker {process_id} | {approach_name}] Processing finished. Sent summary. Read {actual_frames_read} frames.")
        elif not error_occurred and not video_processed_flag and os.path.exists(video_path):
             results_queue.put({ 'type': 'final_summary', 'approach': approach_name, 'filename': video_filename, 'total_frames_read': 0, 'processed_frames_counted': 0,
                 'total_vehicles_in_lane_agg': 0, 'total_counts_by_type': {}, 'total_vehicles_outside': 0, 'total_ambulances_outside_lane':0,
                 'processing_time_sec': total_processing_duration, 'avg_reading_fps': 0, 'avg_processing_rate_fps': 0,
                 'message': 'Video stream did not start or yielded no frames.' })
             print(f"[Worker {process_id} | {approach_name}] Video stream empty/failed. Sent empty summary.")

        print(f"[Worker {process_id} | {approach_name}] Cleaning up models...")
        del general_model
        if ambulance_model: del ambulance_model
        if device_str == 'cuda':
            try: torch.cuda.empty_cache(); print(f"[Worker {process_id} | {approach_name}] CUDA cache cleared.")
            except Exception as cache_e: print(f"[Worker {process_id} | {approach_name}] Warning: Error clearing CUDA cache: {cache_e}")
        print(f"[Worker {process_id} | {approach_name}] Exiting worker function.")