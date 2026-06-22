#!/bin/bash

# Exit on any error
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== ESP32-CAM Auto-Flash Script ==="
echo "This script compiles and uploads your 'esp32_cam.ino' firmware."
echo ""

# 1. Check/Configure WiFi Credentials in .ino file
echo "[1/5] Checking WiFi configuration in esp32_cam.ino..."
SSID_LINE=$(grep "const char\* ssid = " esp32_cam.ino || true)
PASS_LINE=$(grep "const char\* password = " esp32_cam.ino || true)

if [[ "$SSID_LINE" == *"YOUR_WIFI_SSID"* ]]; then
    echo "⚠️  WiFi SSID and password are still set to defaults!"
    read -p "Enter your WiFi SSID: " wifi_ssid
    read -sp "Enter your WiFi Password: " wifi_pass
    echo ""
    
    # Escape special characters for sed
    escaped_ssid=$(echo "$wifi_ssid" | sed 's/[&/\]/\\&/g')
    escaped_pass=$(echo "$wifi_pass" | sed 's/[&/\]/\\&/g')
    
    sed -i "s/const char\* ssid = \"YOUR_WIFI_SSID\";/const char\* ssid = \"$escaped_ssid\";/" esp32_cam.ino
    sed -i "s/const char\* password = \"YOUR_WIFI_PASSWORD\";/const char\* password = \"$escaped_pass\";/" esp32_cam.ino
    echo "✅ WiFi configuration updated in esp32_cam.ino."
else
    echo "✅ WiFi configuration detected."
fi

# 2. Download and Setup arduino-cli locally
echo ""
echo "[2/5] Setting up arduino-cli tool locally..."
if [ ! -f "./arduino-cli" ]; then
    echo "Installing arduino-cli locally..."
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=. sh
    echo "✅ Installed arduino-cli successfully."
else
    echo "✅ arduino-cli is already installed."
fi

# 3. Setup ESP32 Core
echo ""
echo "[3/5] Updating board packages and cores..."
./arduino-cli config init --overwrite >/dev/null || true
./arduino-cli config set board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json >/dev/null

echo "Updating index..."
./arduino-cli core update-index

if ! ./arduino-cli core list | grep -q "esp32:esp32"; then
    echo "Installing ESP32 core (this may take a few minutes)..."
    ./arduino-cli core install esp32:esp32
    echo "✅ ESP32 Core installed."
else
    echo "✅ ESP32 Core already installed."
fi

# 4. Auto-detect Serial Port
echo ""
echo "[4/5] Detecting connected ESP32-CAM USB device..."
SERIAL_PORT=""
FORCED_PORT=""

# Look for standard Linux USB/ACM serial ports
PORTS=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true)

if [ -z "$PORTS" ]; then
    echo "❌ No USB serial devices detected (/dev/ttyUSB* or /dev/ttyACM*)."
    echo "Please connect your ESP32-CAM programmer now."
    read -p "Or type in your custom serial port path manually (e.g. /dev/ttyUSB0): " FORCED_PORT
    if [ -n "$FORCED_PORT" ]; then
        SERIAL_PORT="$FORCED_PORT"
    else
        echo "Exiting..."
        exit 1
    fi
else
    # Pick first detected port
    SERIAL_PORT=$(echo "$PORTS" | head -n 1)
    echo "Found serial device: $SERIAL_PORT"
fi

# Remind user about GPIO 0 to GND bridge
echo ""
echo "📢 IMPORTANT: Put the ESP32-CAM into flashing mode!"
echo "1. Connect 'GPIO 0' to 'GND' using a jumper wire."
echo "2. Press the 'RESET' button on the back of the ESP32-CAM."
echo ""
read -p "Press [Enter] when ready to compile and upload..."

# 5. Compile and Flash
echo ""
echo "[5/5] Compiling and uploading firmware..."
echo "Compiling..."
./arduino-cli compile --fqbn esp32:esp32:esp32cam esp32_cam.ino

echo "Uploading..."
./arduino-cli upload -p "$SERIAL_PORT" --fqbn esp32:esp32:esp32cam esp32_cam.ino

echo ""
echo "🎉 Firmware flashed successfully!"
echo "Now:"
echo "1. Remove the jumper connecting 'GPIO 0' to 'GND'."
echo "2. Press the 'RESET' button on the back of the ESP32-CAM to run the code."
echo "3. Open your serial monitor at 115200 baud to find the IP address."
