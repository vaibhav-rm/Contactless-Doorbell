# Smart Contactless Doorbell - Pi 4 Setup & Configuration Guide

This guide describes how to set up the Smart Contactless AI Doorbell & Access Control System on your physical **Raspberry Pi 4** and connect it to your **ESP32-CAM** and **Blynk Cloud**.

---

## 1. Hardware Connections (Wiring Specification)

Connect the hardware modules to the Raspberry Pi 4 pins as shown in the table below.

### GPIO Wiring Table

| Device | Pin Name | Raspberry Pi 4 GPIO | Physical Pin Number | Wire Color (Typical) |
|---|---|---|---|---|
| **SSD1306 OLED** | VCC | 3.3V Power | Pin 1 | Red |
| **SSD1306 OLED** | GND | Ground | Pin 6 | Black |
| **SSD1306 OLED** | SDA | GPIO 2 (SDA) | Pin 3 | Green / Blue |
| **SSD1306 OLED** | SCL | GPIO 3 (SCL) | Pin 5 | Yellow / White |
| **IR Proximity** | VCC | 3.3V Power | Pin 17 | Red |
| **IR Proximity** | GND | Ground | Pin 20 | Black |
| **IR Proximity** | OUT | GPIO 17 | Pin 11 | Yellow / Orange |
| **SG90 Servo** | PWM | GPIO 18 (PWM) | Pin 12 | Orange (Signal) |
| **SG90 Servo** | GND | Ground | Pin 9 (Common GND) | Brown |
| **SG90 Servo** | VCC | External 5V (+) | External PSU (+) | Red |

### SG90 Servo Powering Best Practice:
* **IMPORTANT**: Do not connect the Red (VCC) wire of the servo to the Pi's 5V pin. The Pi cannot supply enough current when the servo moves, which will cause browser/system crashes or reboot loops.
* Use an external **5V/2A DC power supply** (like a mobile charger adapter or battery pack) for the servo.
* Connect the **External 5V positive (+)** directly to the Servo's Red wire.
* Connect the **External GND (-)** to both the Servo's Brown wire **AND** the Raspberry Pi's GND Pin 9 to form a common ground.

---

## 2. Raspberry Pi System Configuration

Before running the code, you must enable the I2C interface on the Raspberry Pi so it can communicate with the OLED screen.

1. Open the terminal on the Raspberry Pi and run:
   ```bash
   sudo raspi-config
   ```
2. Navigate to **Interface Options** -> **I2C** and select **Yes** to enable it.
3. Reboot the Pi:
   ```bash
   sudo reboot
   ```
4. Verify the OLED is recognized on the I2C bus:
   ```bash
   sudo apt-get install -y i2c-tools
   sudo i2cdetect -y 1
   ```
   * You should see a grid with `3c` shown at row `30`, column `c`. This confirms your OLED screen is wired and detected.

---

## 3. Pre-Requisites & Package Installation

Run these commands to install the compiler tools, OpenCV dependencies, and compilation libraries on your Pi:

```bash
# Update Pi OS repositories
sudo apt-get update && sudo apt-get upgrade -y

# Install Java 21 JDK (required for Spring Boot)
sudo apt-get install -y openjdk-21-jdk

# Install Node.js & NPM (required for React Frontend)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install Docker & Docker Compose (required for PostgreSQL)
sudo apt-get install -y docker.io docker-compose

# Install Python requirements and build essentials (for dlib/face_recognition)
sudo apt-get install -y cmake gcc g++ python3-dev python3-pip libopencv-dev libatlas-base-dev libjpeg-dev
```

---

## 4. Deploying the Software Stack

Clone the repository to your Raspberry Pi 4 workspace (e.g. `/home/pi/contact_less_doorbell`).

### Step A: Start Database Container
1. Move to the root project directory:
   ```bash
   cd contact_less_doorbell
   ```
2. Start the PostgreSQL database:
   ```bash
   docker-compose up -d
   ```
3. Confirm it's running on port `5433`:
   ```bash
   docker ps
   ```

### Step B: Build and Start the Spring Boot Backend
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Build and run the project:
   ```bash
   ./mvnw spring-boot:run
   ```
   * Leave this running. It hosts the API server on `http://localhost:8080` and the WebSocket endpoint.

### Step C: Build and Start the React Web Dashboard
1. Open a new terminal tab and navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```
2. Install packages:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev -- --host
   ```
   * The `--host` flag allows you to view the dashboard from other devices on your local network by going to `http://<pi-ip-address>:5173`.

### Step D: Set Up and Run the Python AI Agent
1. Open a new terminal tab and navigate to the python agent directory:
   ```bash
   cd ../ai_device
   ```
2. Install the python dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```
3. (Optional but Recommended) Install the high-accuracy dlib face recognition library. If skipped, the system uses Haar Cascade fallback automatically:
   ```bash
   pip3 install face_recognition
   ```
4. Configure your credentials. Open `main.py` and set your **Blynk Auth Token**:
   ```python
   BLYNK_AUTH_TOKEN = "YOUR_BLYNK_AUTH_TOKEN"
   ```
5. Run the python hardware agent:
   ```bash
   python3 main.py
   ```

---

## 5. Blynk Mobile App Dashboard Configurations

Configure these widgets in the Blynk IoT mobile/web console to monitor and actuate the door lock from your phone:

1. **V1 Widget (Lock Control)**:
   - Type: **Button**
   - Datastream: `V1 (Integer, 0-1)`
   - Mode: **Switch** (0 = Locked, 1 = Unlocked)
   - Labels: ON: `Unlocked` / OFF: `Locked`
2. **V2 Widget (Last Visitor)**:
   - Type: **Value Display**
   - Datastream: `V2 (String)`
   - Title: `Last Detected`
3. **V3 Widget (Visitor Proximity Indicator)**:
   - Type: **LED** or **Value Display**
   - Datastream: `V3 (Integer, 0-1)`
   - Title: `Motion / Proximity`
4. **V4 Widget (System Status)**:
   - Type: **Value Display**
   - Datastream: `V4 (String)`
   - Title: `System State`

---

## 6. How the Proximity Power Saving Works

1. **Standby Mode**: When nobody is near the door, the system enters a low-power loop. The Python agent shuts the ESP32-CAM video capture stream and powers off the SSD1306 OLED (`set_display_power(False)`). The system only polls the IR sensor (GPIO 17) every 200ms, which consumes less than 1% CPU.
2. **Visitor Approach**: When a visitor steps in front of the door, the IR sensor goes LOW. The Pi immediately:
   - Powers on the OLED panel.
   - Prints `"VISITOR DETECTED"` / `"SCANNING FACE..."` on the OLED screen.
   - Connects to the ESP32-CAM MJPEG server (`http://192.168.0.101`) and streams frames.
   - Runs face recognition matching.
3. **Standby Transition**: If the visitor walks away (IR sensor remains HIGH) and no face is detected for 10 seconds, the agent closes the stream, clears the screen, powers off the OLED, and returns to Standby Mode.
