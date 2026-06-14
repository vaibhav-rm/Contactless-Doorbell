package com.doorbell.backend.controller;

import com.doorbell.backend.model.User;
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
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/api/users")
@CrossOrigin(origins = "*")
public class UserController {

    private final UserRepository userRepository;
    private final DoorbellWebSocketHandler webSocketHandler;
    
    // Shared directory for face images
    private static final String UPLOAD_DIR = "../stored_faces/";

    public UserController(UserRepository userRepository, DoorbellWebSocketHandler webSocketHandler) {
        this.userRepository = userRepository;
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
