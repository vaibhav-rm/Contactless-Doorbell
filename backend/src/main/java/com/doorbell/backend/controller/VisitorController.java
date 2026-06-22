package com.doorbell.backend.controller;

import com.doorbell.backend.model.AccessLog;
import com.doorbell.backend.repository.AccessLogRepository;
import com.doorbell.backend.websocket.DoorbellWebSocketHandler;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/api/visitors")
@CrossOrigin(origins = "*")
public class VisitorController {

    private final AccessLogRepository accessLogRepository;
    private final DoorbellWebSocketHandler webSocketHandler;
    private final ObjectMapper objectMapper;
    private final com.doorbell.backend.service.TelegramBotService telegramBotService;

    private static final String SNAPSHOT_DIR = "../visitor_snapshots/";

    public VisitorController(AccessLogRepository accessLogRepository, 
                             DoorbellWebSocketHandler webSocketHandler,
                             ObjectMapper objectMapper,
                             com.doorbell.backend.service.TelegramBotService telegramBotService) {
        this.accessLogRepository = accessLogRepository;
        this.webSocketHandler = webSocketHandler;
        this.objectMapper = objectMapper;
        this.telegramBotService = telegramBotService;

        // Ensure snapshot directory exists
        File dir = new File(SNAPSHOT_DIR);
        if (!dir.exists()) {
            boolean created = dir.mkdirs();
            System.out.println("Snapshot directory created: " + created);
        }
    }

    @GetMapping("/logs")
    public ResponseEntity<List<AccessLog>> getAllLogs() {
        return ResponseEntity.ok(accessLogRepository.findAll());
    }

    @GetMapping("/logs/recent")
    public ResponseEntity<List<AccessLog>> getRecentLogs() {
        return ResponseEntity.ok(accessLogRepository.findTop10ByOrderByTimestampDesc());
    }

    @PostMapping("/ring")
    public ResponseEntity<?> visitorRing(
            @RequestParam("recognitionResult") String recognitionResult,
            @RequestParam("decision") String decision,
            @RequestParam("approvedBy") String approvedBy,
            @RequestParam(value = "image", required = false) MultipartFile file,
            @RequestParam(value = "video", required = false) MultipartFile videoFile) {

        if ("PENDING".equals(decision)) {
            java.time.LocalDateTime cutoff = java.time.LocalDateTime.now().minusSeconds(60);
            List<AccessLog> existingPending = accessLogRepository.findByDecisionAndRecognitionResultAndTimestampAfter(
                "PENDING", 
                recognitionResult, 
                cutoff
            );
            if (!existingPending.isEmpty()) {
                System.out.println("[VisitorController] Deduplicated duplicate ring request for: " + recognitionResult);
                return ResponseEntity.ok(existingPending.get(0));
            }
        }

        String fileName = null;
        if (file != null && !file.isEmpty()) {
            try {
                String fileExtension = ".jpg";
                String originalFilename = file.getOriginalFilename();
                if (originalFilename != null && originalFilename.contains(".")) {
                    fileExtension = originalFilename.substring(originalFilename.lastIndexOf("."));
                }
                fileName = "visitor_" + System.currentTimeMillis() + fileExtension;
                Path path = Paths.get(SNAPSHOT_DIR + fileName);
                Files.write(path, file.getBytes());
            } catch (IOException e) {
                System.err.println("Could not save visitor snapshot: " + e.getMessage());
            }
        }

        String videoName = null;
        if (videoFile != null && !videoFile.isEmpty()) {
            try {
                String fileExtension = ".mp4";
                String originalFilename = videoFile.getOriginalFilename();
                if (originalFilename != null && originalFilename.contains(".")) {
                    fileExtension = originalFilename.substring(originalFilename.lastIndexOf("."));
                }
                videoName = "video_" + System.currentTimeMillis() + fileExtension;
                Path path = Paths.get(SNAPSHOT_DIR + videoName);
                Files.write(path, videoFile.getBytes());
            } catch (IOException e) {
                System.err.println("Could not save visitor video clip: " + e.getMessage());
            }
        }

        AccessLog log = AccessLog.builder()
                .timestamp(LocalDateTime.now())
                .recognitionResult(recognitionResult)
                .decision(decision)
                .approvedBy(approvedBy)
                .imagePath(fileName)
                .videoPath(videoName)
                .build();

        AccessLog savedLog = accessLogRepository.save(log);

        // Broadcast to all WS clients
        try {
            String logJson = objectMapper.writeValueAsString(savedLog);
            String wsMessage = String.format("{\"type\": \"VISITOR_ALERT\", \"log\": %s}", logJson);
            webSocketHandler.broadcast(wsMessage);
        } catch (Exception e) {
            System.err.println("Could not broadcast WS visitor alert: " + e.getMessage());
        }

        // Notify Telegram if visitor is pending approval
        if ("PENDING".equals(savedLog.getDecision())) {
            telegramBotService.sendVisitorNotification(savedLog);
        }

        return ResponseEntity.status(HttpStatus.CREATED).body(savedLog);
    }

    @PostMapping("/{id}/approve")
    public ResponseEntity<?> approveVisitor(@PathVariable Long id) {
        Optional<AccessLog> logOptional = accessLogRepository.findById(id);
        if (logOptional.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        AccessLog log = logOptional.get();
        log.setDecision("APPROVED");
        log.setApprovedBy("DASHBOARD");
        AccessLog updatedLog = accessLogRepository.save(log);

        // Notify Python agent (to unlock door) and Frontend clients
        String wsMessage = String.format(
            "{\"type\": \"VISITOR_DECISION\", \"logId\": %d, \"decision\": \"APPROVED\"}", 
            id
        );
        webSocketHandler.broadcast(wsMessage);
        
        // Also send a direct LOCK_CONTROL message to unlock the door
        String unlockMessage = "{\"type\": \"LOCK_CONTROL\", \"action\": \"UNLOCK\", \"source\": \"DASHBOARD_APPROVAL\"}";
        webSocketHandler.broadcast(unlockMessage);

        return ResponseEntity.ok(updatedLog);
    }

    @PostMapping("/{id}/reject")
    public ResponseEntity<?> rejectVisitor(@PathVariable Long id) {
        Optional<AccessLog> logOptional = accessLogRepository.findById(id);
        if (logOptional.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        AccessLog log = logOptional.get();
        log.setDecision("REJECTED");
        log.setApprovedBy("DASHBOARD");
        AccessLog updatedLog = accessLogRepository.save(log);

        // Notify Python agent and Frontend clients
        String wsMessage = String.format(
            "{\"type\": \"VISITOR_DECISION\", \"logId\": %d, \"decision\": \"REJECTED\"}", 
            id
        );
        webSocketHandler.broadcast(wsMessage);

        return ResponseEntity.ok(updatedLog);
    }
}
