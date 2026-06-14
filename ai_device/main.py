import os
import cv2
import time
import json
import threading
import requests
import numpy as np
from flask import Flask, Response
import websocket

from face_engine import FaceEngine
from device_controller import DeviceController

app = Flask(__name__)

# --- CONFIGURATION ---
BACKEND_HTTP_URL = "http://localhost:8080/api"
BACKEND_WS_URL = "ws://localhost:8080/ws/doorbell"

# ESP32-CAM camera IP (the user's ESP32-CAM is running on 192.168.0.101)
CAMERA_SOURCE = "http://192.168.0.101"
STREAM_PORT = 8081

# Blynk IoT Cloud Integration
# Update this with your actual Blynk Auth Token to enable Blynk mobile control
BLYNK_AUTH_TOKEN = "" 

# --- GLOBALS ---
latest_frame = None
frame_lock = threading.Lock()
device_ctrl = None
face_eng = None
ws_client = None

system_state = "SLEEPING" # "SLEEPING" or "AWAKE"
last_visitor_name = "None"
is_locked = True

def get_fallback_frame(width=640, height=480):
    """
    Generates a synthetic status frame if the camera stream is offline.
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = [30, 15, 8] # Deep dark blue background
    
    # Grid lines
    for y in range(0, height, 40):
        cv2.line(frame, (0, y), (width, y), (40, 25, 12), 1)
    for x in range(0, width, 40):
        cv2.line(frame, (x, 0), (x, height), (40, 25, 12), 1)
        
    # Text
    cv2.putText(frame, "ESP32-CAM FEEDING...", (40, 60), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, f"TIME: {time.strftime('%X')}", (40, 100), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (148, 163, 184), 1)
    cv2.putText(frame, "Waiting for Face Detection...", (40, 140), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (16, 185, 129), 1)
    
    return frame

def open_esp32_cam_stream(base_url):
    """
    Attempts multiple standard ESP32-CAM streaming endpoints to ensure connection.
    """
    endpoints = [
        base_url,
        base_url + "/stream",
        base_url.rstrip('/') + ":81/stream",
        base_url + "/mjpeg",
        base_url + "/video"
    ]
    
    for url in endpoints:
        print(f"[Main] Attempting connection to stream URL: {url}")
        try:
            cap = cv2.VideoCapture(url)
            if cap.isOpened():
                print(f"[Main] Successfully connected to video stream: {url}")
                return cap
        except Exception as e:
            print(f"[Main] Connection failed for {url}: {e}")
    return None

def video_capture_loop():
    """
    State machine controlling hardware wakeup, face detection, 
    and energy savings.
    """
    global latest_frame, system_state, last_visitor_name
    print("[Main] Video capture thread started.")
    
    cap = None
    last_active_time = 0
    cooldown_seconds = 10
    last_ring_time = 0
    
    while True:
        # Check Proximity Sensor (IR Pin 17 - active LOW)
        visitor_present = device_ctrl.read_ir_sensor()
        
        if visitor_present:
            last_active_time = time.time()
            if system_state == "SLEEPING":
                print("[Main] IR Proximity sensor triggered. Waking up system.")
                system_state = "AWAKE"
                device_ctrl.set_display_power(True)
                device_ctrl.display_oled("VISITOR DETECTED", "SCANNING FACE...")
                
                # Start ESP32-CAM Capture
                cap = open_esp32_cam_stream(CAMERA_SOURCE)
                if not cap:
                    print("[Main] WARNING: Camera stream could not be opened. Using fallback feed.")
        
        # State: Awake
        if system_state == "AWAKE":
            frame = None
            if cap is not None:
                ret, frame = cap.read()
                if not ret:
                    print("[Main] Failed to read frame from stream. Reconnecting...")
                    cap.release()
                    cap = open_esp32_cam_stream(CAMERA_SOURCE)
                    if cap:
                        ret, frame = cap.read()
            
            # If camera stream is offline/failed, generate a placeholder frame
            if frame is None:
                frame = get_fallback_frame()
                time.sleep(0.04) # ~25fps throttle
                
            # Run Face Recognition
            processed_frame, detected_names = face_eng.process_frame(frame)
            
            with frame_lock:
                latest_frame = processed_frame.copy()
                
            # Handle Face Match Decisions
            if len(detected_names) > 0:
                last_active_time = time.time() # Reset sleep timer
                current_time = time.time()
                
                if current_time - last_ring_time > cooldown_seconds:
                    name = detected_names[0]
                    last_visitor_name = name
                    last_ring_time = current_time
                    
                    if name != "Unknown":
                        trigger_automatic_unlock(name, processed_frame)
                    else:
                        trigger_unknown_alert(processed_frame)
            
            # Handle Sleep timeout (10 seconds without IR/Face trigger)
            if time.time() - last_active_time > 10.0:
                print("[Main] Inactivity limit reached. Putting system into sleep mode.")
                system_state = "SLEEPING"
                device_ctrl.display_oled("SYSTEM STANDBY", "")
                time.sleep(1.0)
                device_ctrl.set_display_power(False) # Turn off SSD1306 OLED panel
                
                if cap is not None:
                    cap.release()
                    cap = None
                with frame_lock:
                    latest_frame = None # Release memory
        else:
            # Sleeping: low frequency polling to save Pi CPU
            time.sleep(0.2)

def trigger_automatic_unlock(name, frame):
    global is_locked
    print(f"[Main] Authorized resident '{name}' detected! Access granted.")
    device_ctrl.display_oled("ACCESS GRANTED", f"WELCOME {name.upper()}")
    device_ctrl.set_lock_state(False) # Unlock door (GPIO 18)
    is_locked = False
    
    # Save snapshot and record log
    try:
        temp_img_path = "temp_auth.jpg"
        cv2.imwrite(temp_img_path, frame)
        
        with open(temp_img_path, 'rb') as f:
            files = {'image': (temp_img_path, f, 'image/jpeg')}
            data = {
                'recognitionResult': name,
                'decision': 'APPROVED',
                'approvedBy': 'AUTOMATIC'
            }
            res = requests.post(f"{BACKEND_HTTP_URL}/visitors/ring", data=data, files=files)
            print("[Main] Event logged to database status:", res.status_code)
            
        os.remove(temp_img_path)
    except Exception as e:
        print(f"[Main] Failed to log automatic entry log: {e}")
        
    # Schedule automatic locking
    threading.Thread(target=auto_relock_timer).start()

def trigger_unknown_alert(frame):
    print("[Main] Unknown face detected. Dispatching alert to Web dashboard and Blynk.")
    device_ctrl.display_oled("UNKNOWN VISIT", "WAITING FOR ADMIN")
    
    try:
        temp_img_path = "temp_unknown.jpg"
        cv2.imwrite(temp_img_path, frame)
        
        with open(temp_img_path, 'rb') as f:
            files = {'image': (temp_img_path, f, 'image/jpeg')}
            data = {
                'recognitionResult': 'Unknown',
                'decision': 'PENDING',
                'approvedBy': 'PENDING'
            }
            res = requests.post(f"{BACKEND_HTTP_URL}/visitors/ring", data=data, files=files)
            print("[Main] Unknown visitor alert logged to database status:", res.status_code)
            
        os.remove(temp_img_path)
    except Exception as e:
        print(f"[Main] Failed to post unknown alert: {e}")

def auto_relock_timer():
    global is_locked
    time.sleep(5)
    print("[Main] Locking door automatically.")
    device_ctrl.set_lock_state(True)
    is_locked = True
    
    try:
        requests.post(f"{BACKEND_HTTP_URL}/lock/lock?source=SYSTEM")
    except Exception:
        pass

# Blynk IoT Sync Loop
def blynk_sync_loop():
    global is_locked, last_visitor_name, system_state
    if not BLYNK_AUTH_TOKEN:
        print("[Blynk] BLYNK_AUTH_TOKEN is empty. Blynk dashboard sync disabled.")
        return
        
    print(f"[Blynk] Blynk dashboard listener thread active using token: {BLYNK_AUTH_TOKEN[:6]}...")
    
    while True:
        try:
            # 1. Sync local variables to Blynk Cloud
            # V1: Lock status (1 = Unlocked, 0 = Locked)
            v1_val = "1" if not is_locked else "0"
            requests.get(f"https://blynk.cloud/external/api/update?token={BLYNK_AUTH_TOKEN}&v1={v1_val}", timeout=3)
            
            # V2: Last visitor name
            requests.get(f"https://blynk.cloud/external/api/update?token={BLYNK_AUTH_TOKEN}&v2={last_visitor_name}", timeout=3)
            
            # V3: Proximity detection (1 = Awake/Present, 0 = Standby)
            v3_val = "1" if system_state == "AWAKE" else "0"
            requests.get(f"https://blynk.cloud/external/api/update?token={BLYNK_AUTH_TOKEN}&v3={v3_val}", timeout=3)
            
            # V4: System state description
            requests.get(f"https://blynk.cloud/external/api/update?token={BLYNK_AUTH_TOKEN}&v4={system_state}", timeout=3)
            
            # 2. Poll Blynk V1 for manual unlock overrides
            res = requests.get(f"https://blynk.cloud/external/api/get?token={BLYNK_AUTH_TOKEN}&v1", timeout=3)
            if res.status_code == 200:
                blynk_val = res.text.strip()
                if blynk_val in ("0", "1"):
                    blynk_is_locked = blynk_val == "0"
                    if blynk_is_locked != is_locked:
                        print(f"[Blynk] Blynk app control event: Lock={blynk_is_locked}")
                        device_ctrl.set_lock_state(blynk_is_locked)
                        is_locked = blynk_is_locked
                        
                        # Notify Spring Boot backend
                        action = "lock" if blynk_is_locked else "unlock"
                        try:
                            requests.post(f"{BACKEND_HTTP_URL}/lock/{action}?source=BLYNK", timeout=2)
                        except Exception:
                            pass
        except Exception as e:
            # Silence connection losses
            pass
            
        time.sleep(1.5)

# Spring Boot WebSocket Client
def on_ws_message(ws, message):
    global is_locked
    try:
        data = json.loads(message)
        print("[WS Client] Received message from Backend:", data)
        
        if data.get("type") == "LOCK_CONTROL":
            action = data.get("action")
            if action == "UNLOCK":
                device_ctrl.set_lock_state(False)
                is_locked = False
            elif action == "LOCK":
                device_ctrl.set_lock_state(True)
                is_locked = True
                
        elif data.get("type") == "RELOAD_FACES":
            face_eng.load_known_faces()
            
        elif data.get("type") == "TAMPER_ALERT":
            device_ctrl.display_oled("TAMPER ALARM!", "FORCED ENTRY")
            print("[WS Client] TAMPER ALARM TRIGGERED!")
            
    except Exception as e:
        print("[WS Client] Error parsing packet:", e)

def on_ws_error(ws, error):
    print("[WS Client] Error:", error)

def on_ws_close(ws, status, msg):
    print("[WS Client] Connection closed. Retrying connection in 5s...")
    time.sleep(5)
    start_websocket_client()

def start_websocket_client():
    global ws_client
    print(f"[WS Client] Connecting to: {BACKEND_WS_URL}")
    websocket.enableTrace(False)
    ws_client = websocket.WebSocketApp(
        BACKEND_WS_URL,
        on_message=on_ws_message,
        on_error=on_ws_error,
        on_close=on_ws_close
    )
    wst = threading.Thread(target=ws_client.run_forever)
    wst.daemon = True
    wst.start()

# Flask Stream Server
def gen_frames():
    global latest_frame
    while True:
        with frame_lock:
            if latest_frame is None:
                time.sleep(0.1)
                continue
            ret, buffer = cv2.imencode('.jpg', latest_frame)
            frame_bytes = buffer.tobytes()
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.04)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def forward_oled_to_ws(text):
    if ws_client and ws_client.sock and ws_client.sock.connected:
        try:
            ws_client.send(json.dumps({
                "type": "SIMULATOR_OLED",
                "text": text
            }))
        except Exception:
            pass

if __name__ == "__main__":
    print("=== Smart Contactless Doorbell AI Agent ===")
    
    # Initialize devices & model
    device_ctrl = DeviceController(websocket_callback=forward_oled_to_ws)
    face_eng = FaceEngine()
    
    # Connect Spring Boot Websocket broker
    start_websocket_client()
    
    # Connect Blynk dashboard loop
    blynk_thread = threading.Thread(target=blynk_sync_loop)
    blynk_thread.daemon = True
    blynk_thread.start()
    
    # Start Camera monitoring loop
    capture_thread = threading.Thread(target=video_capture_loop)
    capture_thread.daemon = True
    capture_thread.start()
    
    # Start flask video server
    print(f"[Flask] Video server running on: http://0.0.0.0:{STREAM_PORT}/video_feed")
    app.run(host='0.0.0.0', port=STREAM_PORT, debug=False, use_reloader=False)
