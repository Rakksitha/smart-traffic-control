import serial
import time
import traceback

class ESP32SerialController:
    def __init__(self, port, baudrate, approach_mapping):
        self.port = port
        self.baudrate = baudrate
        self.approach_mapping = approach_mapping 
        self.serial_connection = None
        self.is_connected = False
        self._connect()

    def _connect(self):
        try:
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()
            
            self.serial_connection = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2) 
            self.is_connected = True
            print(f"[ESP32] Successfully connected to {self.port} at {self.baudrate} baud.")
        except serial.SerialException as e:
            print(f"[ESP32 Error] Failed to connect to {self.port}: {e}")
            self.serial_connection = None 
            self.is_connected = False
        except Exception as e_generic: 
            print(f"[ESP32 Error] A generic error occurred during connection to {self.port}: {e_generic}")
            traceback.print_exc()
            self.serial_connection = None
            self.is_connected = False


    def update_lights(self, approach_statuses):
        
        if not self.is_connected or not self.serial_connection: 
            return

        command_parts = []
        for approach_name, status_info in approach_statuses.items():
            short_code = self.approach_mapping.get(approach_name)
            if short_code:
                
                light_state_char = status_info.get('state', 'RED')[0].upper() 
                if light_state_char not in ('R', 'Y', 'G'): 
                    light_state_char = 'R' 
                command_parts.append(f"{short_code}:{light_state_char}")
        
        if not command_parts:
            
            return

        command_string = ",".join(command_parts) + "\n"
        self.send_command(command_string)

    def send_command(self, command_string):
        """ Sends a formatted command string to the ESP32. """
        if not self.is_connected or not self.serial_connection:
            print("[ESP32 Error] Attempted to send command while not connected.")
            return

        try:
            
            print(f"[ESP32 Sending] > {command_string.strip()}")
            
            bytes_written = self.serial_connection.write(command_string.encode('ascii'))
            self.serial_connection.flush() 
            
        except serial.SerialTimeoutException:
            print(f"[ESP32 Error] Serial write timeout on {self.port}.")
            
        except serial.SerialException as e:
            print(f"[ESP32 Error] Failed to write to serial port {self.port}: {e}")
            self.is_connected = False 
            self.close() 
        except Exception as e_gen: 
            print(f"[ESP32 Error] Unexpected error during send to {self.port}: {e_gen}")
            traceback.print_exc()
            self.is_connected = False
            self.close()


    def close(self):
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.close()
                print(f"[ESP32] Serial connection to {self.port} closed.")
            except Exception as e:
                print(f"[ESP32 Error] Error closing serial port {self.port}: {e}")
        self.is_connected = False
        self.serial_connection = None 

    def reconnect(self): 
        if not self.is_connected:
            print(f"[ESP32] Attempting to reconnect to {self.port}...")
            self.close() 
            self._connect()
        return self.is_connected
