package com.doorbell.backend.model;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Entity
@Table(name = "access_logs")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AccessLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private LocalDateTime timestamp;

    @Column(name = "image_path")
    private String imagePath; // Path to visitor snapshot

    @Column(name = "recognition_result", nullable = false)
    private String recognitionResult; // E.g., "Unknown" or the visitor's matched name

    @Column(nullable = false)
    private String decision; // "PENDING", "APPROVED", "REJECTED"

    @Column(name = "approved_by")
    private String approvedBy; // "AUTOMATIC" (face matched), "DASHBOARD" (manual button click), "SYSTEM"

    @Column(name = "video_path")
    private String videoPath; // Path to visitor video clip

    @PrePersist
    protected void onCreate() {
        if (timestamp == null) {
            timestamp = LocalDateTime.now();
        }
    }
}
