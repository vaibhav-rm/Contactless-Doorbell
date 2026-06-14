# Smart Contactless AI Doorbell & Access Control System

A complete IoT Access Control system using a **Raspberry Pi 4**, an **ESP32-CAM**, a **Spring Boot** backend database engine, and a premium **React + Vite** web dashboard. The system supports face recognition, automatic door unlock (via SG90 servo), proximity-based power saving (via IR sensor), and real-time remote monitoring via a web dashboard and **Blynk IoT**.

---

## 1. Hardware Interface Specification

### Raspberry Pi 4 Pin Allocations

| Component | Pin Function | GPIO Pin (BCM) | Physical Pin |
|---|---|---|---|
| **OLED (SSD1306)** | I2C Data (SDA) | `GPIO 2` | Pin 3 |
| **OLED (SSD1306)** | I2C Clock (SCL) | `GPIO 3` | Pin 5 |
| **IR Proximity Sensor** | Digital Input (Active Low) | `GPIO 17` | Pin 11 |
| **SG90 Servo Motor** | PWM Signal | `GPIO 18` | Pin 12 |
| **OLED VCC** | Power (3.3V) | - | Pin 1 |
| **OLED GND** | Ground | - | Pin 6 |
| **IR Sensor VCC** | Power (3.3V) | - | Pin 17 |
| **IR Sensor GND** | Ground | - | Pin 20 |
| **SG90 Servo VCC** | Power (5V) | - | Pin 2 (See Warning below) |
| **SG90 Servo GND** | Ground | - | Pin 9 |

> [!WARNING]
> **Servo Motor Power Supply Warning**
> Servos draw high current spikes during movement. Powering the SG90 servo directly from the Pi's 5V pin can cause the Pi to brownout, crash, or damage the GPIO pins.
> * **Recommended**: Use an external 5V/2A power supply for the SG90 Servo motor, sharing a common ground (GND) between the Pi and the external power supply.

---

## 2. ESP32-CAM Setup & Flashing

The ESP32-CAM runs an independent HTTP MJPEG stream server at IP `192.168.0.101`.

### Flashing the ESP32-CAM:
1. Open the [esp32_cam/esp32_cam.ino](esp32_cam/esp32_cam.ino) sketch in the Arduino IDE.
2. Replace `YOUR_WIFI_SSID` and `YOUR_WIFI_PASSWORD` with your credentials.
3. Connect the ESP32-CAM to your PC using an FTDI USB-to-TTL programmer:
   - ESP32-CAM **5V** ── FTDI **5V**
   - ESP32-CAM **GND** ── FTDI **GND**
   - ESP32-CAM **U0R** (RX) ── FTDI **TX**
   - ESP32-CAM **U0T** (TX) ── FTDI **RX**
   - **Bridge GPIO 0 to GND** on the ESP32-CAM to put it in flashing mode.
4. Set Board in Arduino IDE: **AI Thinker ESP32-CAM**, set upload speed to **115200**.
5. Press the reset button on the ESP32-CAM, then click **Upload**.
6. Remove the bridge between **GPIO 0 and GND**, and power cycle the board. It will boot up and print its IP on the Serial Monitor (should be reserved/bound to `192.168.0.101` in your router's DHCP settings).

---

## 3. Blynk Dashboard Configuration

You can monitor and control the door lock remotely from the Blynk mobile/web app:
1. Create a new template on Blynk Cloud named **Doorbell Access**.
2. Add the following **Datastreams**:
   - **V1 (Virtual Pin 1)**: Data Type: `Integer` (Min: 0, Max: 1). Represents Lock State (0 = Locked, 1 = Unlocked). Use a Button widget styled as a Switch.
   - **V2 (Virtual Pin 2)**: Data Type: `String`. Displays the name of the last visitor.
   - **V3 (Virtual Pin 3)**: Data Type: `Integer` (0 or 1). Represents Proximity Status (0 = Sleeping/Standby, 1 = Visitor Present/Scanning).
   - **V4 (Virtual Pin 4)**: Data Type: `String`. Displays System State ("SLEEPING", "AWAKE").
3. Copy your **Blynk Auth Token** and set it in `ai_device/main.py`:
   ```python
   BLYNK_AUTH_TOKEN = "your_blynk_auth_token_here"
   ```

---

## 4. Software Stack Deployment

### A. Database (Docker)
Start the PostgreSQL container (runs on port `5433`):
```bash
docker-compose up -d
```

### B. Spring Boot Backend
1. Navigate to the backend folder:
   ```bash
   cd backend
   ```
2. Build and run the service:
   ```bash
   ./mvnw spring-boot:run
   ```
   * The backend runs on `http://localhost:8080` and starts the WebSocket broker on `ws://localhost:8080/ws/doorbell`.

### C. React Frontend Web Dashboard
1. Navigate to the frontend folder:
   ```bash
   cd frontend
   ```
2. Install packages:
   ```bash
   npm install
   ```
3. Start the Vite development server:
   ```bash
   npm run dev
   ```
   * Open `http://localhost:5173` in your browser.

### D. Python AI & Hardware Agent (Raspberry Pi 4)
1. Install system dependencies on the Pi:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-opencv python3-pip
   ```
2. Install python packages:
   ```bash
   pip3 install -r ai_device/requirements.txt
   ```
   *(Optionally, install `dlib` and `face_recognition` libraries to unlock advanced AI recognition. If they are missing, the agent will fall back to Haar Cascades automatically).*
3. Run the Python Agent:
   ```bash
   python3 ai_device/main.py
   ```

---

## 5. Proximity-Based Power Saving Workflow

To protect the lifespan of the SSD1306 OLED screen and save Raspberry Pi processing resources:
1. **Sleeping State**: The Python agent runs in low-power mode. The OLED display is powered off (`set_display_power(False)`), and the camera stream is closed. The agent polls the IR sensor on GPIO 17 every 200ms.
2. **Awake State**: When a visitor approaches (IR sensor goes LOW), the system immediately wakes up, powers on the OLED showing `"VISITOR DETECTED"`, connects to the ESP32-CAM stream, and starts running active face recognition.
3. **Standby Transition**: If no visitor is detected near the sensor and no faces are present for 10 seconds, the OLED powers down, the video stream is closed, and the system transitions back to sleep mode.
