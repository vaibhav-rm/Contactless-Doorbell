package com.doorbell.backend.repository;

import com.doorbell.backend.model.AccessLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AccessLogRepository extends JpaRepository<AccessLog, Long> {
    List<AccessLog> findTop10ByOrderByTimestampDesc();

    List<AccessLog> findByDecisionAndRecognitionResultAndTimestampAfter(
        String decision, 
        String recognitionResult, 
        java.time.LocalDateTime timestamp
    );
}
