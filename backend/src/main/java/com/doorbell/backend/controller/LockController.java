package com.doorbell.backend.controller;

import com.doorbell.backend.websocket.DoorbellWebSocketHandler;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/lock")
@CrossOrigin(origins = "*")
public class LockController {

    private final DoorbellWebSocketHandler webSocketHandler;
    private boolean isLocked = true; // Default state

    public LockController(DoorbellWebSocketHandler webSocketHandler) {
        this.webSocketHandler = webSocketHandler;
    }

    @GetMapping("/status")
    public ResponseEntity<Map<String, Object>> getStatus() {
        return ResponseEntity.ok(Map.of("locked", isLocked));
    }

    @PostMapping("/unlock")
    public ResponseEntity<Map<String, Object>> unlockDoor(@RequestParam(required = false, defaultValue = "DASHBOARD") String source) {
        isLocked = false;
        
        // Broadcast WebSocket message to the python agent and frontend clients
        String message = String.format("{\"type\": \"LOCK_CONTROL\", \"action\": \"UNLOCK\", \"source\": \"%s\"}", source);
        webSocketHandler.broadcast(message);
        
        System.out.println("Door unlocked by: " + source);
        return ResponseEntity.ok(Map.of("locked", false, "message", "Unlock command broadcasted."));
    }

    @PostMapping("/lock")
    public ResponseEntity<Map<String, Object>> lockDoor(@RequestParam(required = false, defaultValue = "DASHBOARD") String source) {
        isLocked = true;
        
        // Broadcast WebSocket message
        String message = String.format("{\"type\": \"LOCK_CONTROL\", \"action\": \"LOCK\", \"source\": \"%s\"}", source);
        webSocketHandler.broadcast(message);
        
        System.out.println("Door locked by: " + source);
        return ResponseEntity.ok(Map.of("locked", true, "message", "Lock command broadcasted."));
    }
}
