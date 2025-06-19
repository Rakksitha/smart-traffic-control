// --- ESP32 Traffic Light Controller for 4 Lanes ---

// Corrected LED pins according to user-specified setup

// North Lane
const int NR_PIN = 23;
const int NY_PIN = 22;
const int NG_PIN = 21;

// East Lane
const int ER_PIN = 17;
const int EY_PIN = 18;
const int EG_PIN = 19;

// South Lane (Corrected pins)
const int SR_PIN = 13;  // Red
const int SY_PIN = 12;  // Yellow
const int SG_PIN = 14;  // Green

// West Lane
const int WR_PIN = 25;
const int WY_PIN = 26;
const int WG_PIN = 27;



// Structure to hold pins for a single lane
struct LaneLeds {
  int redPin;
  int yellowPin;
  int greenPin;
  char currentLed; // 'R', 'Y', 'G', or 'O' (Off)
};

// Declare lanes - map short codes to LaneLeds
LaneLeds northLane = {NR_PIN, NY_PIN, NG_PIN, 'R'};
LaneLeds eastLane  = {ER_PIN, EY_PIN, EG_PIN, 'R'};
LaneLeds southLane = {SR_PIN, SY_PIN, SG_PIN, 'R'};
LaneLeds westLane  = {WR_PIN, WY_PIN, WG_PIN, 'R'};

// Buffer for incoming serial data
const int SERIAL_BUFFER_SIZE = 64; // Max command length "N:R,E:R,S:R,W:R\n" is well within this
char serialBuffer[SERIAL_BUFFER_SIZE];
int serialBufferIndex = 0;

// Baud rate for serial communication (must match Python script)
const long BAUD_RATE = 115200;

void setup() {
  Serial.begin(BAUD_RATE);
  Serial.println("ESP32 Traffic Light Controller Initialized.");
  Serial.println("Waiting for commands (e.g., N:G,E:R,S:R,W:R\\n)...");

  // Initialize LED pins as outputs
  pinMode(NR_PIN, OUTPUT);
  pinMode(NY_PIN, OUTPUT);
  pinMode(NG_PIN, OUTPUT);

  pinMode(ER_PIN, OUTPUT);
  pinMode(EY_PIN, OUTPUT);
  pinMode(EG_PIN, OUTPUT);

  pinMode(SR_PIN, OUTPUT);
  pinMode(SY_PIN, OUTPUT);
  pinMode(SG_PIN, OUTPUT);

  pinMode(WR_PIN, OUTPUT);
  pinMode(WY_PIN, OUTPUT);
  pinMode(WG_PIN, OUTPUT);

  // Initialize all lights to RED by default
  setLaneState(northLane, 'R');
  setLaneState(eastLane, 'R');
  setLaneState(southLane, 'R');
  setLaneState(westLane, 'R');
}

void loop() {
  if (Serial.available() > 0) {
    char incomingChar = Serial.read();

    if (incomingChar == '\n') { // End of command
      serialBuffer[serialBufferIndex] = '\0'; // Null-terminate the string
      processCommand(serialBuffer);
      serialBufferIndex = 0; // Reset buffer for next command
    } else if (serialBufferIndex < SERIAL_BUFFER_SIZE - 1) {
      serialBuffer[serialBufferIndex++] = incomingChar;
    } else {
      // Buffer overflow, reset (shouldn't happen with expected command length)
      Serial.println("Error: Serial buffer overflow. Command ignored.");
      serialBufferIndex = 0;
    }
  }
}

void processCommand(char* command) {
  Serial.print("Received command: ");
  Serial.println(command);

  // Example command: "N:G,E:R,S:R,W:R"
  char* part = strtok(command, ","); // Split by comma

  while (part != NULL) {
    // Each part is like "N:G"
    if (strlen(part) == 3 && part[1] == ':') {
      char laneCode = part[0];
      char lightState = part[2];

      switch (laneCode) {
        case 'N':
          setLaneState(northLane, lightState);
          break;
        case 'E':
          setLaneState(eastLane, lightState);
          break;
        case 'S':
          setLaneState(southLane, lightState);
          break;
        case 'W':
          setLaneState(westLane, lightState);
          break;
        default:
          Serial.print("Unknown lane code: ");
          Serial.println(laneCode);
          break;
      }
    } else {
      Serial.print("Malformed command part: ");
      Serial.println(part);
    }
    part = strtok(NULL, ","); // Get next part
  }
}

// Function to set the state of LEDs for a given lane
void setLaneState(LaneLeds &lane, char state) {
  // Turn off all LEDs for this lane first
  digitalWrite(lane.redPin, LOW);
  digitalWrite(lane.yellowPin, LOW);
  digitalWrite(lane.greenPin, LOW);
  lane.currentLed = 'O'; // Off

  // Turn on the specified LED
  switch (state) {
    case 'R': // Red
      digitalWrite(lane.redPin, HIGH);
      lane.currentLed = 'R';
      break;
    case 'Y': // Yellow
      digitalWrite(lane.yellowPin, HIGH);
      lane.currentLed = 'Y';
      break;
    case 'G': // Green
      digitalWrite(lane.greenPin, HIGH);
      lane.currentLed = 'G';
      break;
    default:
      Serial.print("Unknown light state '");
      Serial.print(state);
      Serial.println("' for a lane. Turning all off.");
      // All already off from above
    break;
  }
}