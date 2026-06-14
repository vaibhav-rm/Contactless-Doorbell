import os
import cv2
import numpy as np

# Try to import advanced face_recognition, fallback if missing
try:
    import face_recognition
    HAS_FACE_REC = True
    print("[FaceEngine] Advanced face_recognition library loaded successfully.")
except ImportError:
    HAS_FACE_REC = False
    print("[FaceEngine] face_recognition library not found. Falling back to OpenCV-only mode.")

class FaceEngine:
    def __init__(self, faces_dir="../stored_faces"):
        self.faces_dir = faces_dir
        self.known_face_encodings = []
        self.known_face_names = []
        
        # For OpenCV fallback
        self.face_cascade = None
        if not HAS_FACE_REC:
            # Load standard OpenCV Haar Cascade
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            
        self.load_known_faces()

    def load_known_faces(self):
        self.known_face_encodings = []
        self.known_face_names = []
        
        if not os.path.exists(self.faces_dir):
            os.makedirs(self.faces_dir)
            print(f"[FaceEngine] Created faces directory: {self.faces_dir}")
            return

        print(f"[FaceEngine] Loading known faces from {self.faces_dir}...")
        
        for file_name in os.listdir(self.faces_dir):
            if file_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                name = file_name.split('_')[0].capitalize() # Get name from file (e.g. vaibhav_123.jpg -> Vaibhav)
                image_path = os.path.join(self.faces_dir, file_name)
                
                if HAS_FACE_REC:
                    try:
                        img = face_recognition.load_image_file(image_path)
                        encodings = face_recognition.face_encodings(img)
                        if len(encodings) > 0:
                            self.known_face_encodings.append(encodings[0])
                            self.known_face_names.append(name)
                            print(f"[FaceEngine] Loaded face for: {name}")
                        else:
                            print(f"[FaceEngine] WARNING: No face found in {file_name}")
                    except Exception as e:
                        print(f"[FaceEngine] Error loading {file_name} with face_recognition: {e}")
                else:
                    # In OpenCV fallback, we just store the names
                    self.known_face_names.append(name)
                    print(f"[FaceEngine] Registered fallback name: {name}")

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
        
        if HAS_FACE_REC:
            # Convert to RGB
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            
            # Find all face locations and encodings
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
            
            for face_encoding, face_location in zip(face_encodings, face_locations):
                # See if face matches known faces
                matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding, tolerance=0.6)
                name = "Unknown"
                
                if len(self.known_face_encodings) > 0:
                    face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)
                    best_match_index = np.argmin(face_distances)
                    if matches[best_match_index]:
                        name = self.known_face_names[best_match_index]
                
                detected_names.append(name)
                
                # Scale back up face locations since the frame we detected in was scaled to 1/4
                top, right, bottom, left = face_location
                top *= 4
                right *= 4
                bottom *= 4
                left *= 4
                
                # Draw box
                color = (46, 204, 113) if name != "Unknown" else (52, 152, 219) # Green for known, Blue for unknown
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                
                # Draw label
                cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
                cv2.putText(frame, name, (left + 6, bottom - 10), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 1)
        else:
            # OpenCV Fallback Mode
            gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
            
            for (x, y, w, h) in faces:
                # In simulation/fallback, if there are known users, we match the face to the first known user for demo,
                # else we label it "Unknown"
                name = "Unknown"
                if len(self.known_face_names) > 0:
                    name = self.known_face_names[0] # Match first registered user for demo
                
                detected_names.append(name)
                
                # Scale back up
                top, left, bottom, right = y * 4, x * 4, (y + h) * 4, (x + w) * 4
                
                color = (46, 204, 113) if name != "Unknown" else (52, 152, 219)
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
                cv2.putText(frame, name, (left + 6, bottom - 10), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 1)

        return frame, detected_names
