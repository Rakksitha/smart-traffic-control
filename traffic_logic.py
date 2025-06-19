import time
from collections import defaultdict
import math
import traceback

class TrafficLightController:
    def __init__(self, config_data, vehicle_type_weights=None, default_vehicle_weight=1.0):
        self.intersections = {}
        self.config = config_data
        self.all_approach_names = set()
        self.vehicle_type_weights = vehicle_type_weights if vehicle_type_weights is not None else {}
        self.default_vehicle_weight = default_vehicle_weight

        if not config_data:
            print("[TrafficLogic Error] No configuration data provided.")
            raise ValueError("Traffic light configuration cannot be empty.")

        print("[TrafficLogic] Initializing intersections...")
        for name, int_config in config_data.items():
            try:
                self._initialize_intersection_state(name, int_config)
            except ValueError as e:
                 print(f"[TrafficLogic Error] Failed to initialize intersection '{name}': {e}")
                 raise

        if not self.intersections:
             print("[TrafficLogic Error] No intersections were successfully initialized. Check config.")
             raise ValueError("No valid intersections configured.")

        print(f"[TrafficLogic] Controller initialized for intersections: {list(self.intersections.keys())}")
        print(f"[TrafficLogic] Managing approaches: {sorted(list(self.all_approach_names))}")
        print(f"[TrafficLogic] Using vehicle weights: {self.vehicle_type_weights} (Default: {self.default_vehicle_weight})")


    def _validate_phase_config(self, name, phases_config):
        if not phases_config or not isinstance(phases_config, dict):
            raise ValueError(f"'{name}': 'phases' dictionary is missing or invalid.")
        all_phase_approaches = set()
        for phase_name, approaches in phases_config.items():
            if not isinstance(approaches, list):
                raise ValueError(f"'{name}', phase '{phase_name}': Approaches must be a list.")
            if len(approaches) != 1:
                raise ValueError(
                    f"Intersection '{name}', phase '{phase_name}': Must contain exactly one approach name "
                    f"for single-approach green logic. Found {len(approaches)}: {approaches}. "
                    "Please ensure each phase in TRAFFIC_LIGHT_CONFIG maps to a list with a single approach string."
                )
            all_phase_approaches.update(approaches)
        return all_phase_approaches

    def _initialize_intersection_state(self, name, config):
        phases_config = config.get('phases', {})
        intersection_approaches = self._validate_phase_config(name, phases_config)
        phase_names_list = list(phases_config.keys())
        if not phase_names_list:
             raise ValueError(f"No phase names found for intersection '{name}'.")

        self.all_approach_names.update(intersection_approaches)
        timings = config.get('timings', {})
        required_keys = ['min_green', 'yellow', 'all_red', 'gap_time', 'skip_threshold',
                         'emergency_green', 'ambulance_request_timeout',
                         'base_max_green', 'queued_weighted_demand_extension_factor', 'absolute_max_green',
                         'realtime_flow_extension_increment', 'realtime_flow_min_weighted_demand'
                         ]
        missing_keys = [k for k in required_keys if k not in timings]
        if missing_keys:
             raise ValueError(f"Missing timing keys in config for intersection '{name}': {missing_keys}")

        demand_threshold = config.get('demand_threshold', 1)
        if not isinstance(demand_threshold, (int, float)) or demand_threshold < 0:
             print(f"[TrafficLogic Warning] Invalid 'demand_threshold' for '{name}'. Using default 1.")
             demand_threshold = 1

        self.intersections[name] = {
            "config": config,
            "phases": phase_names_list,
            "current_phase_index": 0,
            "current_state": "ALL_RED",
            "state_timer": 0.0,
            "green_timer": 0.0,
            "current_cycle_max_green": timings.get('base_max_green', 20),
            "last_update_time": time.time(),
            "approach_demand": defaultdict(int),
            "approach_weighted_demand": defaultdict(float),
            "last_detection_time_green": defaultdict(float),
            "last_weighted_flow_green": defaultdict(float),
            "name": name,
            "managed_approaches": list(intersection_approaches),
            "demand_threshold": demand_threshold,
            "ambulance_request_active": defaultdict(bool),
            "last_ambulance_detection_time": defaultdict(float),
            "emergency_preemption_active": False,
            "target_emergency_phase_key": None,
            "is_current_phase_emergency": False,
            "manual_override_red": defaultdict(bool), 
        }
        print(f"[TrafficLogic]   - Initialized '{name}': Starting ALL_RED, first phase '{phase_names_list[0]}'. Managed approaches: {sorted(list(intersection_approaches))}")

    
    def set_manual_override(self, intersection_name, approach_name, is_forced_red):
        if intersection_name in self.intersections:
            state = self.intersections[intersection_name]
            if approach_name in state["managed_approaches"]:
                state["manual_override_red"][approach_name] = is_forced_red
                action = "FORCED RED" if is_forced_red else "RELEASED from manual red"
                print(f"[{state['name']}] Manual override for approach '{approach_name}' set to: {action}")

                
                
                return True
        print(f"[TrafficLogic Warning] Could not set manual override for '{approach_name}' in '{intersection_name}' (Intersection or approach not found).")
        return False
    

    def update_demand(self, approach_name, count, current_time, ambulance_detected=False):
        for int_state in self.intersections.values():
            if approach_name in int_state["managed_approaches"]:
                current_phase_key = int_state['phases'][int_state['current_phase_index']]
                current_phase_approaches = int_state['config']['phases'].get(current_phase_key, [])
                is_in_active_phase = (approach_name in current_phase_approaches)
                is_green_or_yellow = is_in_active_phase and (int_state['current_state'] in ["GREEN", "YELLOW"])

                if count > 0: 
                    if is_green_or_yellow:
                        int_state['last_detection_time_green'][approach_name] = current_time
                    else: 
                        int_state['approach_demand'][approach_name] += count 
                
                if ambulance_detected:
                    int_state['ambulance_request_active'][approach_name] = True
                    int_state['last_ambulance_detection_time'][approach_name] = current_time
                return

    def update_weighted_demand(self, approach_name, counts_by_type, current_time):
        current_weighted_value_this_update = 0
        for vehicle_type, count in counts_by_type.items():
            weight = self.vehicle_type_weights.get(vehicle_type, self.default_vehicle_weight)
            current_weighted_value_this_update += count * weight
        
        for int_state in self.intersections.values():
            if approach_name in int_state["managed_approaches"]:
                current_phase_key = int_state['phases'][int_state['current_phase_index']]
                current_phase_approaches = int_state['config']['phases'].get(current_phase_key, [])
                is_in_active_phase = (approach_name in current_phase_approaches)
                is_green = is_in_active_phase and (int_state['current_state'] == "GREEN")

                if is_green:
                    int_state['last_weighted_flow_green'][approach_name] = max(
                        int_state['last_weighted_flow_green'].get(approach_name, 0.0),
                        current_weighted_value_this_update
                    )
                elif not (is_in_active_phase and int_state['current_state'] == "YELLOW"):
                    int_state['approach_weighted_demand'][approach_name] += current_weighted_value_this_update
                return

    def update_state(self, current_time):
        any_state_changed = False
        for name, state in self.intersections.items():
            try:
                if self._update_single_intersection_state(state, current_time):
                    any_state_changed = True
            except Exception as e:
                 print(f"[TrafficLogic Error] Unhandled exception updating state for intersection '{name}': {e}")
                 traceback.print_exc()
        return any_state_changed

    def _update_ambulance_request_timeouts(self, state, current_time):
        timeout_duration = state['config']['timings']['ambulance_request_timeout']
        for approach_name in list(state['ambulance_request_active'].keys()):
            if state['ambulance_request_active'][approach_name]:
                last_det_time = state['last_ambulance_detection_time'].get(approach_name, 0)
                if current_time - last_det_time > timeout_duration:
                    print(f"[{state['name']}] Ambulance request for {approach_name} timed out.")
                    state['ambulance_request_active'][approach_name] = False

    def _check_for_emergency_preemption_need(self, state):
        if state['emergency_preemption_active'] and state['target_emergency_phase_key']:
            return None 
        phases_config = state['config']['phases']
        phase_keys_list = state['phases']
        for p_key in phase_keys_list: 
            phase_approaches = phases_config.get(p_key, []) 
            if not phase_approaches: continue
            the_single_approach_for_this_phase = phase_approaches[0]

            
            if state["manual_override_red"].get(the_single_approach_for_this_phase, False):
                continue

            if state['ambulance_request_active'].get(the_single_approach_for_this_phase, False):
                is_current_green_for_this_amb_phase = (
                    state['current_state'] == "GREEN" and
                    phase_keys_list[state['current_phase_index']] == p_key and
                    state['is_current_phase_emergency']
                )
                if not is_current_green_for_this_amb_phase:
                    return p_key 
        return None


    def _update_single_intersection_state(self, state, current_time):
        config = state['config']
        timings = config['timings']
        phases_config = config['phases']
        phase_keys_list = state['phases']
        
        delta_time = current_time - state['last_update_time']
        max_delta = 5.0
        if delta_time < 0: delta_time = 0 
        if delta_time > max_delta:
            print(f"[{state['name']}] Warning: Large time delta ({delta_time:.1f}s). Clamping to {max_delta}s.")
            delta_time = max_delta
            
        state['state_timer'] += delta_time
        if state['current_state'] == "GREEN":
            state['green_timer'] += delta_time

        self._update_ambulance_request_timeouts(state, current_time) 

        next_state = None
        switch_reason = ""
        state_did_change = False

        if not state['emergency_preemption_active']: 
            emergency_phase_needed = self._check_for_emergency_preemption_need(state)
            if emergency_phase_needed:
                state['emergency_preemption_active'] = True
                state['target_emergency_phase_key'] = emergency_phase_needed
                state['is_current_phase_emergency'] = False 
                print(f"[{state['name']}] EMERGENCY PREEMPTION ACTIVATED for phase '{emergency_phase_needed}'.")
                if state['current_state'] == "GREEN" and phase_keys_list[state['current_phase_index']] != emergency_phase_needed:
                    next_state = "YELLOW"
                    switch_reason = f"Emergency Preemption for '{emergency_phase_needed}'"

        current_phase_key_on_entry = phase_keys_list[state['current_phase_index']]
        current_phase_actual_approaches_on_entry = phases_config.get(current_phase_key_on_entry, [])
        the_current_green_approach_on_entry = current_phase_actual_approaches_on_entry[0] if current_phase_actual_approaches_on_entry else None


        if next_state is None: 
            if state['current_state'] == "GREEN":
                
                if the_current_green_approach_on_entry and \
                   state["manual_override_red"].get(the_current_green_approach_on_entry, False):
                    next_state = "YELLOW"
                    switch_reason = f"Current green approach '{the_current_green_approach_on_entry}' MANUALLY FORCED TO RED."
                
                elif state['is_current_phase_emergency']: 
                    if state['green_timer'] >= timings['emergency_green']:
                        next_state = "YELLOW"
                        switch_reason = f"Emergency Green ({timings['emergency_green']}s) for '{current_phase_key_on_entry}' ({the_current_green_approach_on_entry}) finished."
                else: 
                    if the_current_green_approach_on_entry and \
                       state['last_weighted_flow_green'].get(the_current_green_approach_on_entry, 0.0) >= timings['realtime_flow_min_weighted_demand'] and \
                       state['current_cycle_max_green'] < timings['absolute_max_green']:
                        
                        new_max_green = min(state['current_cycle_max_green'] + timings['realtime_flow_extension_increment'], timings['absolute_max_green'])
                        if new_max_green > state['current_cycle_max_green']:
                            print(f"[{state['name']}] Approach '{the_current_green_approach_on_entry}' real-time flow (W.Flow: {state['last_weighted_flow_green'].get(the_current_green_approach_on_entry, 0.0):.1f}) extending max green to {new_max_green:.1f}s.")
                            state['current_cycle_max_green'] = new_max_green
                        state['last_weighted_flow_green'][the_current_green_approach_on_entry] = 0.0 

                    if state['green_timer'] >= state['current_cycle_max_green']:
                        next_state = "YELLOW"
                        switch_reason = f"Calculated Max Green ({state['current_cycle_max_green']:.1f}s) reached for {the_current_green_approach_on_entry}"
                    elif state['green_timer'] >= timings['min_green']:
                        max_conflicting_weighted_demand = 0.0
                        conflicting_approach_display_name = "N/A"
                        for other_phase_idx, other_p_key in enumerate(phase_keys_list):
                            if other_phase_idx != state['current_phase_index']:
                                approaches_in_other_phase = phases_config.get(other_p_key, [])
                                if not approaches_in_other_phase: continue
                                the_other_approach = approaches_in_other_phase[0]
                                
                                if state["manual_override_red"].get(the_other_approach, False):
                                    continue
                                demand_on_other_approach = state['approach_weighted_demand'].get(the_other_approach, 0.0)
                                if demand_on_other_approach > max_conflicting_weighted_demand:
                                     max_conflicting_weighted_demand = demand_on_other_approach
                                     conflicting_approach_display_name = the_other_approach
                        
                        conflicting_demand_met = (max_conflicting_weighted_demand >= state['demand_threshold'])
                        last_green_det_time_for_current = state['last_detection_time_green'].get(the_current_green_approach_on_entry, 0.0)
                        time_since_last_green = current_time - last_green_det_time_for_current if last_green_det_time_for_current > 0 else timings['gap_time'] + 1
                        
                        if conflicting_demand_met and time_since_last_green > timings['gap_time']:
                            next_state = "YELLOW"
                            switch_reason = (f"Gap-Out on '{the_current_green_approach_on_entry}' (Gap: {time_since_last_green:.1f}s > {timings['gap_time']}s | "
                                             f"Conflict: Approach '{conflicting_approach_display_name}' W.Demand={max_conflicting_weighted_demand:.1f})")

            elif state['current_state'] == "YELLOW":
                if state['state_timer'] >= timings['yellow']:
                    next_state = "ALL_RED"
                    switch_reason = f"Yellow time for '{the_current_green_approach_on_entry}' finished"

            elif state['current_state'] == "ALL_RED":
                if state['state_timer'] >= timings['all_red']:
                    switch_reason_prefix = "All Red finished. "
                    if state['emergency_preemption_active'] and state['target_emergency_phase_key']:
                        try:
                            target_emergency_approach_name = phases_config.get(state['target_emergency_phase_key'], ["Unknown"])[0]
                            
                            if state["manual_override_red"].get(target_emergency_approach_name, False):
                                print(f"[{state['name']}] Emergency target '{target_emergency_approach_name}' (Phase '{state['target_emergency_phase_key']}') is MANUALLY FORCED RED. Cannot service emergency.")
                                
                                
                                state['emergency_preemption_active'] = False 
                                state['target_emergency_phase_key'] = None
                                
                                new_emergency_target = self._check_for_emergency_preemption_need(state)
                                if new_emergency_target:
                                    state['emergency_preemption_active'] = True
                                    state['target_emergency_phase_key'] = new_emergency_target
                                    
                                else: 
                                    pass
                            else: 
                                state['current_phase_index'] = phase_keys_list.index(state['target_emergency_phase_key'])
                                next_state = "GREEN"
                                switch_reason = switch_reason_prefix + f"Starting EMERGENCY Phase '{state['target_emergency_phase_key']}' for approach '{target_emergency_approach_name}'"
                                state['is_current_phase_emergency'] = True 
                                
                                emergency_approaches_served = phases_config.get(state['target_emergency_phase_key'], [])
                                if emergency_approaches_served:
                                    served_approach_name = emergency_approaches_served[0]
                                    if state['ambulance_request_active'].get(served_approach_name, False):
                                        print(f"[{state['name']}] Servicing ambulance for {served_approach_name} on phase '{state['target_emergency_phase_key']}'. Clearing request.")
                                        state['ambulance_request_active'][served_approach_name] = False
                        except ValueError:
                            print(f"[{state['name']}] ERROR: Target emergency phase '{state['target_emergency_phase_key']}' not found. Reverting.")
                            state['emergency_preemption_active'] = False; state['target_emergency_phase_key'] = None; state['is_current_phase_emergency'] = False
                    
                    if not next_state: 
                        skipped_phases_count = 0; next_phase_idx_candidate = state['current_phase_index']; original_starting_idx_for_search = state['current_phase_index']
                        num_phases = len(phase_keys_list)
                        selected_approach_for_green_candidate = None
                        found_eligible_phase = False

                        for _ in range(num_phases): 
                            next_phase_idx_candidate = (next_phase_idx_candidate + 1) % num_phases
                            next_p_key_to_check_candidate = phase_keys_list[next_phase_idx_candidate]
                            approaches_to_check_candidate = phases_config.get(next_p_key_to_check_candidate, [])
                            if not approaches_to_check_candidate: continue 
                            
                            the_single_approach_to_check_candidate = approaches_to_check_candidate[0]
                            
                            
                            if state["manual_override_red"].get(the_single_approach_to_check_candidate, False):
                                print(f"[{state['name']}] Phase '{next_p_key_to_check_candidate}' for approach '{the_single_approach_to_check_candidate}' is MANUALLY FORCED RED. Skipping.")
                                skipped_phases_count += 1
                                
                                state['approach_demand'][the_single_approach_to_check_candidate] = 0 
                                state['approach_weighted_demand'][the_single_approach_to_check_candidate] = 0.0
                                continue 

                            
                            if state['ambulance_request_active'].get(the_single_approach_to_check_candidate, False):
                                print(f"[{state['name']}] Approach '{the_single_approach_to_check_candidate}' (Phase '{next_p_key_to_check_candidate}') has ambulance and is NOT overridden. Selecting.")
                                selected_approach_for_green_candidate = the_single_approach_to_check_candidate
                                found_eligible_phase = True
                                break 
                            
                            
                            weighted_demand_for_next_approach_candidate = state['approach_weighted_demand'].get(the_single_approach_to_check_candidate, 0.0)
                            if weighted_demand_for_next_approach_candidate <= timings['skip_threshold']:
                                print(f"[{state['name']}] Skipping phase '{next_p_key_to_check_candidate}' for approach '{the_single_approach_to_check_candidate}' (W.Demand: {weighted_demand_for_next_approach_candidate:.1f} <= {timings['skip_threshold']})")
                                skipped_phases_count += 1
                                state['approach_demand'][the_single_approach_to_check_candidate] = 0 
                                state['approach_weighted_demand'][the_single_approach_to_check_candidate] = 0.0
                            else: 
                                selected_approach_for_green_candidate = the_single_approach_to_check_candidate
                                found_eligible_phase = True
                                break 
                        
                        if not found_eligible_phase:
                            
                            
                            
                            print(f"[{state['name']}] Warning: All non-overridden phases met skip criteria or no eligible phase. Advancing to phase after original or staying ALL_RED if all overridden.")
                            
                            
                            
                            next_phase_idx_candidate = (original_starting_idx_for_search + 1) % num_phases
                            selected_approach_for_green_candidate = phases_config.get(phase_keys_list[next_phase_idx_candidate], ["Unknown"])[0]
                            

                        state['current_phase_index'] = next_phase_idx_candidate 
                        next_state = "GREEN"
                        next_phase_key_selected = phase_keys_list[state['current_phase_index']]
                        
                        queued_w_demand = state['approach_weighted_demand'].get(selected_approach_for_green_candidate, 0.0) if selected_approach_for_green_candidate else 0.0
                        calculated_max_g = timings['base_max_green'] + (queued_w_demand * timings['queued_weighted_demand_extension_factor'])
                        state['current_cycle_max_green'] = min(calculated_max_g, timings['absolute_max_green'])
                        state['current_cycle_max_green'] = max(state['current_cycle_max_green'], timings['min_green'])

                        switch_reason = switch_reason_prefix + f"Starting Phase '{next_phase_key_selected}' for approach '{selected_approach_for_green_candidate}' (Est. Max Green: {state['current_cycle_max_green']:.1f}s)"
                        state['is_current_phase_emergency'] = False 

                        if state['emergency_preemption_active'] and phase_keys_list[state['current_phase_index']] != state['target_emergency_phase_key']:
                             print(f"[{state['name']}] Emergency preemption for '{state['target_emergency_phase_key']}' concluded as normal phase '{phase_keys_list[state['current_phase_index']]}' starts.")
                             state['emergency_preemption_active'] = False
                             state['target_emergency_phase_key'] = None

        if next_state and next_state != state['current_state']:
            current_phase_key_display = phase_keys_list[state['current_phase_index']]
            current_approach_display = phases_config.get(current_phase_key_display, ["Unknown"])[0]
            print(f"[{state['name']}] State Change: {state['current_state']} -> {next_state}. (Phase: {current_phase_key_display} for Appr: {current_approach_display}, Reason: {switch_reason})")
            state_did_change = True

            if state['current_state'] == "YELLOW" and next_state == "ALL_RED":
                 finished_approaches = phases_config.get(current_phase_key_on_entry, []) 
                 if finished_approaches:
                     the_finished_approach = finished_approaches[0]
                     
                     if not state["manual_override_red"].get(the_finished_approach, False):
                         state['approach_demand'][the_finished_approach] = 0 
                         state['approach_weighted_demand'][the_finished_approach] = 0.0
                     if the_finished_approach in state['last_detection_time_green']:
                         del state['last_detection_time_green'][the_finished_approach]
                     if the_finished_approach in state['last_weighted_flow_green']:
                         del state['last_weighted_flow_green'][the_finished_approach]
                 
                 if state['is_current_phase_emergency']:
                     print(f"[{state['name']}] Emergency phase '{current_phase_key_on_entry}' for approach '{current_approach_display}' cycle completed.")
                     state['is_current_phase_emergency'] = False 
                     if state['emergency_preemption_active'] and state['target_emergency_phase_key'] == current_phase_key_on_entry:
                         another_emergency = self._check_for_emergency_preemption_need(state)
                         if not another_emergency:
                             print(f"[{state['name']}] No further pending emergencies. Deactivating preemption mode.")
                             state['emergency_preemption_active'] = False
                             state['target_emergency_phase_key'] = None
                         else:
                             print(f"[{state['name']}] Another emergency for '{another_emergency}' detected. Preemption remains active.")
                             state['target_emergency_phase_key'] = another_emergency 

            state['current_state'] = next_state
            state['state_timer'] = 0.0
            if next_state == "GREEN":
                state['green_timer'] = 0.0
                new_green_approach_key = phase_keys_list[state['current_phase_index']]
                new_green_approach = phases_config.get(new_green_approach_key, ["Unknown"])[0]
                if new_green_approach != "Unknown":
                    state['last_weighted_flow_green'][new_green_approach] = 0.0
        
        state['last_update_time'] = current_time
        return state_did_change


    def get_intersection_names(self):
        return list(self.intersections.keys())

    def get_approaches_for_intersection(self, intersection_name):
        state = self.intersections.get(intersection_name)
        return state["managed_approaches"] if state else []

    def get_all_approach_names(self):
        return sorted(list(self.all_approach_names))

    def get_intersection_status(self, intersection_name):
        state = self.intersections.get(intersection_name)
        if not state: return {}
        
        current_phase_key = state['phases'][state['current_phase_index']]
        approach_for_current_phase_list = state['config']['phases'].get(current_phase_key, [])
        approach_for_current_phase = "N/A"
        is_current_phase_manually_red = False
        if approach_for_current_phase_list:
            approach_for_current_phase = approach_for_current_phase_list[0]
            is_current_phase_manually_red = state["manual_override_red"].get(approach_for_current_phase, False)
        
        timer_val = state['green_timer'] if state['current_state'] == 'GREEN' else state['state_timer']
        
        max_duration_for_progress = 0
        current_s = state['current_state']
        timings = state['config']['timings']

        if current_s == 'GREEN':
            
            
            max_duration_for_progress = state['current_cycle_max_green'] if not state['is_current_phase_emergency'] else timings['emergency_green']
            if is_current_phase_manually_red : 
                 max_duration_for_progress = 0.1 
        elif current_s == 'YELLOW':
            max_duration_for_progress = timings['yellow']
        elif current_s == 'ALL_RED':
            max_duration_for_progress = timings['all_red']
        
        return {
            'phase': current_phase_key,
            'active_approach': approach_for_current_phase, 
            'state': current_s, 
            'timer': timer_val,
            'max_duration': max_duration_for_progress,
            'is_emergency': state['is_current_phase_emergency'] or state['emergency_preemption_active']
        }

    def get_all_approach_statuses(self):
        statuses = {}
        for int_name, int_state in self.intersections.items():
            current_phase_key = int_state['phases'][int_state['current_phase_index']]
            current_green_approach_list = int_state['config']['phases'].get(current_phase_key, [])
            current_intersection_actual_state = int_state['current_state']

            for approach_name in int_state["managed_approaches"]:
                light_state_for_approach = 'RED' 
                
                
                is_manually_forced_red = int_state["manual_override_red"].get(approach_name, False)
                if is_manually_forced_red:
                    light_state_for_approach = 'RED'
                elif current_intersection_actual_state in ['GREEN', 'YELLOW']:
                    
                    if current_green_approach_list and approach_name == current_green_approach_list[0]:
                        light_state_for_approach = current_intersection_actual_state
                
                
                statuses[approach_name] = {
                    'state': light_state_for_approach,
                    'demand': int_state['approach_demand'].get(approach_name, 0),
                    'weighted_demand': int_state['approach_weighted_demand'].get(approach_name, 0.0),
                    'ambulance_request_active': int_state['ambulance_request_active'].get(approach_name, False),
                    'is_manually_red': is_manually_forced_red 
                }
        return statuses