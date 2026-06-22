package com.doorbell.backend.controller;

import com.doorbell.backend.model.AccessLog;
import com.doorbell.backend.model.User;
import com.doorbell.backend.repository.AccessLogRepository;
import com.doorbell.backend.repository.UserRepository;
import com.doorbell.backend.websocket.DoorbellWebSocketHandler;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/api/users")
@CrossOrigin(origins = "*")
public class UserController {

    private final UserRepository userRepository;
    private final AccessLogRepository accessLogRepository;
    private final DoorbellWebSocketHandler webSocketHandler;
    
    // Shared directory for face images
    private static final String UPLOAD_DIR = "../stored_faces/";

    public UserController(UserRepository userRepository, 
                          AccessLogRepository accessLogRepository, 
                          DoorbellWebSocketHandler webSocketHandler) {
        this.userRepository = userRepository;
        this.accessLogRepository = accessLogRepository;
        this.webSocketHandler = webSocketHandler;
        
        // Ensure upload directory exists
        File uploadDir = new File(UPLOAD_DIR);
        if (!uploadDir.exists()) {
            boolean created = uploadDir.mkdirs();
            System.out.println("Upload directory created: " + created);
        }
    }

    @GetMapping
    public ResponseEntity<List<User>> getAllUsers() {
        return ResponseEntity.ok(userRepository.findAll());
    }

    @PostMapping
    public ResponseEntity<?> createUser(
            @RequestParam("name") String name,
            @RequestParam("role") String role,
            @RequestParam("image") MultipartFile file) {
        
        if (file.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("error", "Image file is required"));
        }

        try {
            // Clean the name to create a safe file name
            String fileExtension = "";
            String originalFilename = file.getOriginalFilename();
            if (originalFilename != null && originalFilename.contains(".")) {
                fileExtension = originalFilename.substring(originalFilename.lastIndexOf("."));
            }
            String fileName = name.toLowerCase().replaceAll("[^a-z0-9]", "_") + "_" + System.currentTimeMillis() + fileExtension;
            
            Path path = Paths.get(UPLOAD_DIR + fileName);
            Files.write(path, file.getBytes());

            User user = User.builder()
                    .name(name)
                    .role(role)
                    .imagePath(fileName)
                    .build();

            User savedUser = userRepository.save(user);

            // Notify Python agent to reload faces
            webSocketHandler.broadcast("{\"type\": \"RELOAD_FACES\"}");

            return ResponseEntity.status(HttpStatus.CREATED).body(savedUser);
        } catch (IOException e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "Could not save file: " + e.getMessage()));
        }
    }

    @PostMapping("/add-from-visitor")
    public ResponseEntity<?> createUserFromVisitor(
            @RequestParam("name") String name,
            @RequestParam("role") String role,
            @RequestParam("visitorLogId") Long visitorLogId) {
        
        Optional<AccessLog> logOptional = accessLogRepository.findById(visitorLogId);
        if (logOptional.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("error", "Visitor log not found"));
        }
        
        AccessLog log = logOptional.get();
        if (log.getImagePath() == null || log.getImagePath().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("error", "No snapshot available for this visitor"));
        }
        
        try {
            // Clean the name to create a safe file name
            String fileExtension = ".jpg";
            String originalFilename = log.getImagePath();
            if (originalFilename.contains(".")) {
                fileExtension = originalFilename.substring(originalFilename.lastIndexOf("."));
            }
            String fileName = name.toLowerCase().replaceAll("[^a-z0-9]", "_") + "_" + System.currentTimeMillis() + fileExtension;
            
            // Paths
            Path sourcePath = Paths.get("../visitor_snapshots/" + log.getImagePath());
            Path targetPath = Paths.get(UPLOAD_DIR + fileName);
            
            if (!Files.exists(sourcePath)) {
                return ResponseEntity.badRequest().body(Map.of("error", "Visitor snapshot file not found on server"));
            }
            
            // Copy file from snapshots to stored_faces
            Files.copy(sourcePath, targetPath, StandardCopyOption.REPLACE_EXISTING);
            
            // Create user
            User user = User.builder()
                    .name(name)
                    .role(role)
                    .imagePath(fileName)
                    .build();
            
            User savedUser = userRepository.save(user);
            
            // Update the access log
            log.setRecognitionResult(name);
            log.setDecision("APPROVED");
            log.setApprovedBy("DASHBOARD_ALLOW_LIST");
            accessLogRepository.save(log);
            
            // Notify Python agent to reload faces
            webSocketHandler.broadcast("{\"type\": \"RELOAD_FACES\"}");
            
            // Notify frontend that visitor log is approved
            String wsMessage = String.format(
                "{\"type\": \"VISITOR_DECISION\", \"logId\": %d, \"decision\": \"APPROVED\"}", 
                visitorLogId
            );
            webSocketHandler.broadcast(wsMessage);
            
            // Unlock the door since they are now approved
            String unlockMessage = "{\"type\": \"LOCK_CONTROL\", \"action\": \"UNLOCK\", \"source\": \"ALLOW_LIST_APPROVAL\"}";
            webSocketHandler.broadcast(unlockMessage);
            
            return ResponseEntity.status(HttpStatus.CREATED).body(Map.of(
                "user", savedUser,
                "log", log
            ));
        } catch (IOException e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "Could not copy snapshot to user directory: " + e.getMessage()));
        }
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<?> deleteUser(@PathVariable Long id) {
        Optional<User> userOptional = userRepository.findById(id);
        if (userOptional.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        User user = userOptional.get();
        
        // Delete the image file
        try {
            Path path = Paths.get(UPLOAD_DIR + user.getImagePath());
            Files.deleteIfExists(path);
        } catch (IOException e) {
            System.err.println("Could not delete image file: " + e.getMessage());
        }

        userRepository.delete(user);

        // Notify Python agent to reload faces
        webSocketHandler.broadcast("{\"type\": \"RELOAD_FACES\"}");

        return ResponseEntity.ok(Map.of("message", "User deleted successfully"));
    }
}
