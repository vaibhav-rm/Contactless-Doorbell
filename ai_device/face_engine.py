import os
import cv2
import numpy as np
import requests

YUNET_MODEL = "face_detection_yunet.onnx"
SFACE_MODEL = "face_recognition_sface.onnx"

YUNET_URL = "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"

def download_file(url, local_filename):
    print(f"[FaceEngine] Downloading {local_filename} from {url}...")
    try:
        r = requests.get(url, stream=True, timeout=15)
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"[FaceEngine] Downloaded {local_filename} successfully.")
    except Exception as e:
        print(f"[FaceEngine] Error downloading {local_filename}: {e}")

class FaceEngine:
    def __init__(self, faces_dir="../stored_faces"):
        self.faces_dir = faces_dir
        self.known_face_encodings = []
        self.known_face_names = []
        
        # Paths for DNN models (placed in the same folder as face_engine.py)
        dir_path = os.path.dirname(os.path.abspath(__file__))
        self.yunet_path = os.path.join(dir_path, YUNET_MODEL)
        self.sface_path = os.path.join(dir_path, SFACE_MODEL)
        
        # Ensure models exist
        self.ensure_models_exist()
        
        # For OpenCV Haar Cascade Fallback
        self.face_cascade = None
        self.known_face_images = []  # List of tuples: (name, gray_face_128x128)
        
        # Initialize DNN engines
        self.use_dnn = False
        try:
            # We initialize YuNet with size (1, 1) and will scale it dynamically per frame
            self.detector = cv2.FaceDetectorYN.create(self.yunet_path, "", (1, 1), score_threshold=0.6)
            self.recognizer = cv2.FaceRecognizerSF.create(self.sface_path, "")
            self.use_dnn = True
            print("[FaceEngine] OpenCV DNN Face models loaded successfully.")
        except Exception as e:
            print(f"[FaceEngine] Failed to load OpenCV DNN models: {e}")
            print("[FaceEngine] Falling back to OpenCV Haar Cascade mode.")
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            
        self.load_known_faces()

    def ensure_models_exist(self):
        if not os.path.exists(self.yunet_path):
            download_file(YUNET_URL, self.yunet_path)
        if not os.path.exists(self.sface_path):
            download_file(SFACE_URL, self.sface_path)

    def load_known_faces(self):
        self.known_face_encodings = []
        self.known_face_names = []
        self.known_face_images = []
        
        if not os.path.exists(self.faces_dir):
            os.makedirs(self.faces_dir)
            print(f"[FaceEngine] Created faces directory: {self.faces_dir}")
            return

        print(f"[FaceEngine] Loading known faces from {self.faces_dir}...")
        
        # Try fetching user name mapping from Spring Boot API first
        api_names_map = {}
        try:
            r = requests.get("http://localhost:8080/api/users", timeout=2)
            if r.status_code == 200:
                for user in r.json():
                    api_names_map[user['imagePath']] = user['name']
                print(f"[FaceEngine] Synchronized {len(api_names_map)} registered user names from database.")
        except Exception as e:
            print(f"[FaceEngine] Could not sync user names from API ({e}). Falling back to filename parsing.")

        for file_name in os.listdir(self.faces_dir):
            if file_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                # Get the formatted name
                if file_name in api_names_map:
                    name = api_names_map[file_name]
                else:
                    parts = file_name.split('_')
                    if len(parts) > 1:
                        name_parts = parts[:-1]
                        name = " ".join(name_parts).title()
                    else:
                        name = os.path.splitext(file_name)[0].capitalize()

                image_path = os.path.join(self.faces_dir, file_name)
                
                if self.use_dnn:
                    try:
                        img = cv2.imread(image_path)
                        if img is not None:
                            height, width = img.shape[:2]
                            self.detector.setInputSize((width, height))
                            retval, faces = self.detector.detect(img)
                            if faces is not None and len(faces) > 0:
                                aligned = self.recognizer.alignCrop(img, faces[0])
                                feat = self.recognizer.feature(aligned)
                                self.known_face_encodings.append(feat)
                                self.known_face_names.append(name)
                                print(f"[FaceEngine] Loaded DNN face embedding for: {name}")
                            else:
                                print(f"[FaceEngine] WARNING: No face detected in {file_name} using YuNet. Skipping.")
                    except Exception as e:
                        print(f"[FaceEngine] Error loading {file_name} with DNN FaceEngine: {e}")
                else:
                    # OpenCV fallback mode
                    try:
                        img = cv2.imread(image_path)
                        if img is not None:
                            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                            faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
                            if len(faces) > 0:
                                (x, y, w, h) = faces[0]
                                face_crop = gray[y:y+h, x:x+w]
                                face_resized = cv2.resize(face_crop, (128, 128))
                                self.known_face_images.append((name, face_resized))
                                self.known_face_names.append(name)
                                print(f"[FaceEngine] Registered fallback template for: {name}")
                            else:
                                # Fallback to resizing whole image if no face detected in profile pic
                                face_resized = cv2.resize(gray, (128, 128))
                                self.known_face_images.append((name, face_resized))
                                self.known_face_names.append(name)
                                print(f"[FaceEngine] Registered fallback template (whole image) for: {name}")
                    except Exception as e:
                        print(f"[FaceEngine] Error registering fallback template for {file_name}: {e}")

        print(f"[FaceEngine] Total registered faces: {len(self.known_face_names)}")

    def process_frame(self, frame):
        """
        Processes a camera frame.
        Returns:
            processed_frame: Frame with bounding boxes drawn.
            detected_names: List of recognized names (empty if no faces).
        """
        detected_names = []
        
        if frame is None:
            return None, detected_names

        # Resize frame for faster processing (1/4 size)
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        
        if self.use_dnn:
            try:
                height, width = small_frame.shape[:2]
                self.detector.setInputSize((width, height))
                retval, faces = self.detector.detect(small_frame)
                
                if faces is not None:
                    cosine_mode = getattr(cv2, 'FaceRecognizerSF_FR_COSINE', 0)
                    for face in faces:
                        bbox = face[0:4].astype(np.int32)
                        x, y, w, h = bbox
                        
                        name = "Unknown"
                        best_score = -1.0
                        best_name = "Unknown"
                        
                        if len(self.known_face_encodings) > 0:
                            aligned = self.recognizer.alignCrop(small_frame, face)
                            feat = self.recognizer.feature(aligned)
                            
                            for k_name, k_feat in zip(self.known_face_names, self.known_face_encodings):
                                score = self.recognizer.match(feat, k_feat, cosine_mode)
                                if score > best_score:
                                    best_score = score
                                    best_name = k_name
                            
                            # SFace threshold for match (0.363 cosine similarity)
                            if best_score >= 0.363:
                                name = best_name
                                print(f"[FaceEngine] Matched {name} with cosine score {best_score:.3f}")
                            else:
                                print(f"[FaceEngine] Unmatched face. Best score was {best_score:.3f} for {best_name}")
                                
                        detected_names.append(name)
                        
                        # Scale back up
                        top, left, bottom, right = y * 4, x * 4, (y + h) * 4, (x + w) * 4
                        
                        # Green for known, Blue for unknown
                        color = (46, 204, 113) if name != "Unknown" else (219, 152, 52)
                        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                        
                        # Draw label
                        label_text = name
                        if name == "Unknown" and best_score > -1.0:
                            label_text = f"Unknown ({best_score:.2f})"
                        elif name != "Unknown":
                            label_text = f"{name} ({best_score:.2f})"
                            
                        cv2.rectangle(frame, (left, bottom - 30), (right, bottom), color, cv2.FILLED)
                        cv2.putText(frame, label_text, (left + 6, bottom - 8), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)
            except Exception as e:
                print(f"[FaceEngine] Error processing frame with DNN FaceEngine: {e}")
        else:
            # OpenCV Fallback Mode
            gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
            
            for (x, y, w, h) in faces:
                name = "Unknown"
                
                # Check match against known templates
                if len(self.known_face_images) > 0:
                    face_crop = gray[y:y+h, x:x+w]
                    face_resized = cv2.resize(face_crop, (128, 128))
                    
                    best_score = -1.0
                    best_name = "Unknown"
                    
                    for k_name, k_img in self.known_face_images:
                        res = cv2.matchTemplate(face_resized, k_img, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, _ = cv2.minMaxLoc(res)
                        
                        if max_val > best_score:
                            best_score = max_val
                            best_name = k_name
                    
                    if best_score > 0.65:
                        name = best_name
                        print(f"[FaceEngine] Fallback matched {name} with score {best_score:.2f}")
                    else:
                        print(f"[FaceEngine] Fallback unmatched face. Best score was {best_score:.2f} for {best_name}")
                
                detected_names.append(name)
                
                # Scale back up
                top, left, bottom, right = y * 4, x * 4, (y + h) * 4, (x + w) * 4
                
                color = (46, 204, 113) if name != "Unknown" else (219, 152, 52)
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv2.rectangle(frame, (left, bottom - 30), (right, bottom), color, cv2.FILLED)
                cv2.putText(frame, name, (left + 6, bottom - 8), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)

        return frame, detected_names
