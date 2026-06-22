import os
import cv2
import time
import json
import threading
import requests
import numpy as np
import collections
from flask import Flask, Response
import websocket

from face_engine import FaceEngine
from device_controller import DeviceController

app = Flask(__name__)

# --- CONFIGURATION ---
BACKEND_HTTP_URL = "http://localhost:8080/api"
BACKEND_WS_URL = "ws://localhost:8080/ws/doorbell"

# ESP32-CAM camera IP (the user's ESP32-CAM is running on 192.168.0.110)
CAMERA_SOURCE = "http://192.168.0.110/stream"
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
last_active_time = 0
frame_buffer = collections.deque(maxlen=100) # stores last 100 processed frames (~5 seconds at 20fps)

def get_fallback_frame(width=640, height=480):
    """
    Generates a synthetic status frame if the camera stream is offline.
    Supports file-based face simulation for local testing.
    """
    sim_file = "simulate_face.txt"
    if os.path.exists(sim_file):
        try:
            with open(sim_file, "r") as f:
                mode = f.read().strip().lower()
            
            # Remove/clear file so it only triggers once
            try:
                os.remove(sim_file)
            except Exception:
                pass
                
            dir_path = os.path.dirname(os.path.abspath(__file__))
            
            if mode == "alice":
                # Load Alice's registered image
                img_path = os.path.join(dir_path, "../stored_faces/alice_smith_1782085593746.png")
                if os.path.exists(img_path):
                    img = cv2.imread(img_path)
                    if img is not None:
                        return cv2.resize(img, (width, height))
            elif mode == "unknown":
                # Load unknown visitor image
                img_path = os.path.join(dir_path, "unknown_visitor.png")
                if os.path.exists(img_path):
                    img = cv2.imread(img_path)
                    if img is not None:
                        return cv2.resize(img, (width, height))
            elif mode == "multiple":
                # Composite Alice and unknown visitor side-by-side
                img1_path = os.path.join(dir_path, "../stored_faces/alice_smith_1782085593746.png")
                img2_path = os.path.join(dir_path, "unknown_visitor.png")
                if os.path.exists(img1_path) and os.path.exists(img2_path):
                    img1 = cv2.imread(img1_path)
                    img2 = cv2.imread(img2_path)
                    if img1 is not None and img2 is not None:
                        # Resize both to half-width, full-height
                        hw = width // 2
                        img1_res = cv2.resize(img1, (hw, height))
                        img2_res = cv2.resize(img2, (hw, height))
                        # Concatenate horizontally
                        return np.hstack((img1_res, img2_res))
        except Exception as e:
            print(f"[Main] Error reading face simulation: {e}")

    # Standard fallback grid
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

def get_standby_frame(width=640, height=480):
    """
    Generates a synthetic standby frame to display when system is sleeping.
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = [30, 20, 15] # Slate violet background
    
    # Grid lines
    for y in range(0, height, 40):
        cv2.line(frame, (0, y), (width, y), (45, 30, 22), 1)
    for x in range(0, width, 40):
        cv2.line(frame, (x, 0), (x, height), (45, 30, 22), 1)
        
    # Draw simple standby text message
    cv2.putText(frame, "DOOR MONITOR", (width // 2 - 100, height // 2 - 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(frame, "SYSTEM SLEEPING (STANDBY)", (width // 2 - 170, height // 2 + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (148, 163, 184), 1)
    cv2.putText(frame, "Trigger IR sensor or ring to wake", (width // 2 - 180, height // 2 + 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (16, 185, 129), 1)
    return frame

class HTTPVideoCapture:
    """
    Fallback class that implements OpenCV's VideoCapture interface using 
    requests and manual MJPEG stream parsing. Bypasses FFMPEG library load issues on Pi.
    """
    def __init__(self, url):
        self.url = url
        self.response = None
        self.bytes_buf = bytearray()
        self.is_opened = False
        self.open()

    def open(self):
        try:
            self.response = requests.get(self.url, stream=True, timeout=5)
            self.is_opened = (self.response.status_code == 200)
        except Exception as e:
            self.is_opened = False

    def isOpened(self):
        return self.is_opened

    def read(self):
        if not self.is_opened or not self.response:
            return False, None
        try:
            # We read in chunks. MJPEG streams contain multiple JPEG frames.
            # Each JPEG frame starts with b'\xff\xd8' and ends with b'\xff\xd9'.
            for chunk in self.response.iter_content(chunk_size=4096):
                if not chunk:
                    break
                self.bytes_buf.extend(chunk)
                
                a = self.bytes_buf.find(b'\xff\xd8')
                b = self.bytes_buf.find(b'\xff\xd9')
                if a != -1 and b != -1 and b > a:
                    jpg = self.bytes_buf[a:b+2]
                    # Keep the remainder of the buffer for the next frame
                    del self.bytes_buf[0:b+2]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
        except Exception as e:
            print(f"[HTTPVideoCapture] Error reading stream: {e}")
            self.is_opened = False
        return False, None

    def release(self):
        if self.response:
            try:
                self.response.close()
            except Exception:
                pass
        self.is_opened = False

def open_esp32_cam_stream(base_url):
    """
    Attempts multiple standard ESP32-CAM streaming endpoints to ensure connection.
    """
    # Start with the configured base_url
    endpoints = [base_url]
    
    # Extract host/IP to build fallback URLs dynamically
    from urllib.parse import urlparse
    try:
        parsed = urlparse(base_url)
        host = parsed.hostname
        scheme = parsed.scheme or "http"
        if host:
            fallback_endpoints = [
                f"{scheme}://{host}:81/stream",
                f"{scheme}://{host}/stream",
                f"{scheme}://{host}:81/",
                f"{scheme}://{host}/",
                f"{scheme}://{host}/mjpeg",
                f"{scheme}://{host}/video"
            ]
            for ep in fallback_endpoints:
                if ep not in endpoints:
                    endpoints.append(ep)
    except Exception as parse_err:
        print(f"[Main] Error parsing base URL '{base_url}': {parse_err}")

    # 1. First try OpenCV's standard VideoCapture (runs if FFMPEG behaves)
    for url in endpoints:
        print(f"[Main] Attempting connection to stream URL: {url}")
        try:
            cap = cv2.VideoCapture(url)
            if cap.isOpened():
                print(f"[Main] Successfully connected to video stream: {url}")
                return cap
        except Exception as e:
            print(f"[Main] Connection failed for {url}: {e}")

    # 2. Fallback: Try pure python HTTP stream reader (resilient to FFMPEG/GStreamer linkage issues)
    print("[Main] OpenCV VideoCapture failed to load the network stream. Attempting HTTP requests fallback...")
    for url in endpoints:
        print(f"[Main] Attempting HTTP requests fallback stream URL: {url}")
        try:
            cap = HTTPVideoCapture(url)
            if cap.isOpened():
                print(f"[Main] Successfully connected to video stream via HTTP fallback: {url}")
                return cap
        except Exception as e:
            print(f"[Main] HTTP fallback failed for {url}: {e}")
            
    return None

def video_capture_loop():
    """
    State machine controlling hardware wakeup, face detection, 
    and energy savings.
    """
    global latest_frame, system_state, last_visitor_name, last_active_time
    print("[Main] Video capture thread started.")
    
    cap = None
    cooldown_seconds = 10
    last_ring_time = 0
    last_triggered_visitor = None
    last_triggered_time = 0
    
    while True:
        # Check Proximity Sensor (IR Pin 17 - active LOW)
        visitor_present = device_ctrl.read_ir_sensor() or os.path.exists("simulate_face.txt")
        
        if visitor_present:
            last_active_time = time.time()
            if system_state == "SLEEPING":
                print("[Main] IR Proximity sensor triggered. Waking up system.")
                system_state = "AWAKE"
                device_ctrl.set_display_power(True)
                device_ctrl.display_oled("VISITOR DETECTED", "SCANNING FACE...")
                frame_buffer.clear()
                
                # Start ESP32-CAM Capture
                from device_controller import ON_PI
                if ON_PI:
                    cap = open_esp32_cam_stream(CAMERA_SOURCE)
                else:
                    print("[Main] SIMULATION MODE active. Skipping camera stream connection.")
                    cap = None
                if ON_PI and not cap:
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
                
            # Store frame in the rolling buffer
            frame_buffer.append(processed_frame.copy())
                
            # Handle Face Match Decisions
            if len(detected_names) > 0:
                last_active_time = time.time() # Reset sleep timer
                current_time = time.time()
                
                if current_time - last_ring_time > cooldown_seconds:
                    # Filter and categorize detected names
                    residents = [n for n in detected_names if n != "Unknown"]
                    unknowns_count = detected_names.count("Unknown")
                    
                    if len(residents) > 0:
                        # At least one resident is recognized: Auto-unlock
                        residents_str = ", ".join(residents)
                        if unknowns_count > 0:
                            log_name = f"{residents_str} (accompanied by {unknowns_count} Unknown)"
                        else:
                            log_name = residents_str
                    else:
                        # ONLY unknown faces are present
                        log_name = "Unknown"
                        if unknowns_count > 1:
                            log_name = f"Unknown x{unknowns_count}"
                            
                    # Local deduplication: check if same visitor name was triggered recently
                    if log_name == last_triggered_visitor and (current_time - last_triggered_time < 60.0):
                        print(f"[Main] Deduplicating ring for '{log_name}' (already triggered {(current_time - last_triggered_time):.1f}s ago)")
                    else:
                        last_triggered_visitor = log_name
                        last_triggered_time = current_time
                        last_ring_time = current_time
                        last_visitor_name = log_name
                        
                        # Extract rolling buffer frames for video clip
                        video_frames = list(frame_buffer)
                        frame_buffer.clear() # Reset for next sequence
                        
                        if len(residents) > 0:
                            trigger_automatic_unlock(residents[0], log_name, processed_frame, video_frames)
                        else:
                            trigger_unknown_alert(log_name, processed_frame, video_frames)
            
            # Handle Sleep timeout (10 seconds without IR/Face trigger)
            if time.time() - last_active_time > 10.0:
                print("[Main] Inactivity limit reached. Putting system into sleep mode.")
                system_state = "SLEEPING"
                device_ctrl.display_oled("SYSTEM STANDBY", "")
                time.sleep(1.0)
                device_ctrl.set_display_power(False) # Turn off SSD1306 OLED panel
                frame_buffer.clear()
                
                if cap is not None:
                    cap.release()
                    cap = None
                with frame_lock:
                    latest_frame = None # Release memory
        else:
            # Sleeping: low frequency polling to save Pi CPU
            time.sleep(0.2)

def log_visitor_event_async(recognition_result, decision, approved_by, frame, video_frames):
    def run():
        try:
            # 1. Save snapshot image
            temp_img_path = f"temp_snap_{int(time.time())}.jpg"
            cv2.imwrite(temp_img_path, frame)
            
            # 2. Save video clip if frames exist
            temp_vid_path = None
            if video_frames:
                raw_vid_path = f"temp_vid_raw_{int(time.time())}.mp4"
                temp_vid_path = f"temp_vid_{int(time.time())}.mp4"
                height, width, _ = video_frames[0].shape
                # Use standard 'mp4v' codec to write a temporary raw file quickly
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(raw_vid_path, fourcc, 20.0, (width, height))
                for f in video_frames:
                    out.write(f)
                out.release()
                
                # Transcode using ffmpeg to standard H.264 for HTML5 browser compatibility
                try:
                    import subprocess
                    subprocess.run([
                        'ffmpeg', '-y', '-i', raw_vid_path,
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-preset', 'ultrafast', '-crf', '28',
                        temp_vid_path
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    # Clean up the raw file
                    if os.path.exists(raw_vid_path):
                        os.remove(raw_vid_path)
                except Exception as ex:
                    print(f"[Main Async Log] ffmpeg transcoding failed: {ex}. Falling back to raw file.")
                    # Fallback to the raw file if ffmpeg fails
                    if os.path.exists(temp_vid_path):
                        try:
                            os.remove(temp_vid_path)
                        except Exception:
                            pass
                    try:
                        os.rename(raw_vid_path, temp_vid_path)
                    except Exception:
                        temp_vid_path = raw_vid_path
            
            # 3. Build multipart request
            files = {}
            f_img = open(temp_img_path, 'rb')
            files['image'] = (temp_img_path, f_img, 'image/jpeg')
            
            f_vid = None
            if temp_vid_path and os.path.exists(temp_vid_path):
                f_vid = open(temp_vid_path, 'rb')
                files['video'] = (temp_vid_path, f_vid, 'video/mp4')
                
            data = {
                'recognitionResult': recognition_result,
                'decision': decision,
                'approvedBy': approved_by
            }
            
            print(f"[Main Async Log] Posting log for {recognition_result}...")
            res = requests.post(f"{BACKEND_HTTP_URL}/visitors/ring", data=data, files=files)
            print(f"[Main Async Log] Completed. Status: {res.status_code}")
            
            # Close files and clean up
            f_img.close()
            os.remove(temp_img_path)
            
            if f_vid:
                f_vid.close()
                os.remove(temp_vid_path)
                
        except Exception as e:
            print(f"[Main Async Log] Error in async log: {e}")
            
    threading.Thread(target=run, daemon=True).start()

def trigger_automatic_unlock(first_resident_name, full_log_name, frame, video_frames):
    global is_locked
    print(f"[Main] Authorized resident(s) '{full_log_name}' detected! Access granted.")
    device_ctrl.display_oled("ACCESS GRANTED", f"WELCOME {first_resident_name.upper()}")
    device_ctrl.set_lock_state(False) # Unlock door (GPIO 18)
    is_locked = False
    
    # Send Blynk Event Notification
    log_blynk_event("authorized_entry", f"Authorized entry for {first_resident_name}")
    
    # Save snapshot, record log, and video asynchronously
    log_visitor_event_async(full_log_name, 'APPROVED', 'AUTOMATIC', frame, video_frames)
        
    # Schedule automatic locking
    threading.Thread(target=auto_relock_timer).start()

def trigger_unknown_alert(name, frame, video_frames):
    print(f"[Main] Unknown face(s) '{name}' detected. Dispatching alert to Web dashboard and Blynk.")
    device_ctrl.display_oled("UNKNOWN VISIT", "WAITING FOR ADMIN")
    
    # Send Blynk Event Notification
    log_blynk_event("visitor_detected", "Unknown visitor detected at the door!")
    
    # Save snapshot, record log, and video asynchronously
    log_visitor_event_async(name, 'PENDING', 'PENDING', frame, video_frames)

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

def log_blynk_event(event_code, description=""):
    if not BLYNK_AUTH_TOKEN:
        return
    def run():
        try:
            import urllib.parse
            url = f"https://blynk.cloud/external/api/logEvent?token={BLYNK_AUTH_TOKEN}&code={event_code}&description={urllib.parse.quote(description)}"
            requests.get(url, timeout=3)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()

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
    global is_locked, system_state, last_active_time
    try:
        data = json.loads(message)
        print("[WS Client] Received message from Backend:", data)
        
        if data.get("type") == "LOCK_CONTROL":
            action = data.get("action")
            if action == "UNLOCK":
                device_ctrl.set_lock_state(False)
                is_locked = False
                system_state = "AWAKE"
                last_active_time = time.time()
            elif action == "LOCK":
                device_ctrl.set_lock_state(True)
                is_locked = True
                
        elif data.get("type") == "VISITOR_ALERT":
            print("[WS Client] Visitor/Simulation trigger detected. Waking up system.")
            system_state = "AWAKE"
            last_active_time = time.time()

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
        frame_to_send = None
        with frame_lock:
            if latest_frame is not None:
                frame_to_send = latest_frame.copy()
                
        if frame_to_send is None:
            frame_to_send = get_standby_frame()
            
        ret, buffer = cv2.imencode('.jpg', frame_to_send)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.06)

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
