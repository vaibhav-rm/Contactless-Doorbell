package com.doorbell.backend.service;

import com.doorbell.backend.model.AccessLog;
import com.doorbell.backend.repository.AccessLogRepository;
import com.doorbell.backend.websocket.DoorbellWebSocketHandler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;

import java.io.File;
import java.util.Optional;

@Service
public class TelegramBotService {

    private final AccessLogRepository accessLogRepository;
    private final DoorbellWebSocketHandler webSocketHandler;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;

    @Value("${telegram.bot.token:}")
    private String botToken;

    @Value("${telegram.chat.id:}")
    private String chatId;

    private boolean active = false;
    private Thread pollingThread;

    public TelegramBotService(AccessLogRepository accessLogRepository,
                              DoorbellWebSocketHandler webSocketHandler,
                              ObjectMapper objectMapper) {
        this.accessLogRepository = accessLogRepository;
        this.webSocketHandler = webSocketHandler;
        this.objectMapper = objectMapper;
        
        org.springframework.http.client.SimpleClientHttpRequestFactory factory = new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(5000);
        this.restTemplate = new RestTemplate(factory);
    }

    @PostConstruct
    public void init() {
        if (botToken == null || botToken.trim().isEmpty() || chatId == null || chatId.trim().isEmpty()) {
            System.out.println("[TelegramBot] Token or Chat ID not configured. Bot integration disabled.");
            return;
        }
        active = true;
        System.out.println("[TelegramBot] Initialized. Starting updates long polling thread...");
        pollingThread = new Thread(this::pollUpdates);
        pollingThread.setDaemon(true);
        pollingThread.start();
    }

    @PreDestroy
    public void stop() {
        active = false;
        if (pollingThread != null) {
            pollingThread.interrupt();
        }
    }

    private void pollUpdates() {
        int offset = 0;
        while (active) {
            try {
                String url = String.format("https://api.telegram.org/bot%s/getUpdates?offset=%d&timeout=10", botToken, offset);
                String responseStr = restTemplate.getForObject(url, String.class);
                if (responseStr != null) {
                    JsonNode root = objectMapper.readTree(responseStr);
                    if (root.path("ok").asBoolean()) {
                        JsonNode result = root.path("result");
                        for (JsonNode update : result) {
                            int updateId = update.path("update_id").asInt();
                            offset = updateId + 1;

                            if (update.has("callback_query")) {
                                handleCallbackQuery(update.path("callback_query"));
                            }
                        }
                    }
                }
            } catch (Exception e) {
                System.err.println("[TelegramBot] Error polling updates: " + e.getMessage());
            }
            try {
                Thread.sleep(1500);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    private void handleCallbackQuery(JsonNode callbackQuery) {
        try {
            String callbackQueryId = callbackQuery.path("id").asText();
            String data = callbackQuery.path("data").asText();
            JsonNode message = callbackQuery.path("message");
            long messageId = message.path("message_id").asLong();
            long chatRoomId = message.path("chat").path("id").asLong();

            JsonNode from = callbackQuery.path("from");
            String senderName = from.path("first_name").asText();
            String username = from.path("username").asText("");
            String approver = username.isEmpty() ? senderName : String.format("%s (@%s)", senderName, username);

            if (data.startsWith("APPROVE_") || data.startsWith("DENY_")) {
                boolean approve = data.startsWith("APPROVE_");
                long logId = Long.parseLong(data.substring(approve ? 8 : 5));

                Optional<AccessLog> logOpt = accessLogRepository.findById(logId);
                if (logOpt.isPresent()) {
                    AccessLog log = logOpt.get();

                    if ("PENDING".equals(log.getDecision())) {
                        String decision = approve ? "APPROVED" : "REJECTED";
                        log.setDecision(decision);
                        log.setApprovedBy("TELEGRAM: " + approver);
                        accessLogRepository.save(log);

                        // Broadcast to python agent and frontend clients
                        String wsMessage = String.format(
                                "{\"type\": \"VISITOR_DECISION\", \"logId\": %d, \"decision\": \"%s\"}",
                                logId, decision
                        );
                        webSocketHandler.broadcast(wsMessage);

                        if (approve) {
                            String unlockMessage = "{\"type\": \"LOCK_CONTROL\", \"action\": \"UNLOCK\", \"source\": \"TELEGRAM_APPROVAL\"}";
                            webSocketHandler.broadcast(unlockMessage);
                        }

                        answerCallback(callbackQueryId, "Visitor " + (approve ? "approved" : "denied") + " successfully!");
                        updateTelegramMessage(chatRoomId, messageId, log, approve, approver);
                    } else {
                        answerCallback(callbackQueryId, "This visitor log has already been processed!");
                    }
                } else {
                    answerCallback(callbackQueryId, "Visitor log not found!");
                }
            }
        } catch (Exception e) {
            System.err.println("[TelegramBot] Error handling callback: " + e.getMessage());
        }
    }

    private void answerCallback(String callbackQueryId, String text) {
        try {
            String url = String.format("https://api.telegram.org/bot%s/answerCallbackQuery", botToken);
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_FORM_URLENCODED);
            MultiValueMap<String, String> map = new LinkedMultiValueMap<>();
            map.add("callback_query_id", callbackQueryId);
            map.add("text", text);
            HttpEntity<MultiValueMap<String, String>> request = new HttpEntity<>(map, headers);
            restTemplate.postForObject(url, request, String.class);
        } catch (Exception e) {
            System.err.println("[TelegramBot] Fail answer callback: " + e.getMessage());
        }
    }

    private void updateTelegramMessage(long chatId, long messageId, AccessLog log, boolean approved, String approver) {
        try {
            String url = String.format("https://api.telegram.org/bot%s/editMessageCaption", botToken);
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_FORM_URLENCODED);

            String statusEmoji = approved ? "✅ APPROVED" : "❌ REJECTED";
            String newCaption = String.format(
                    "🔔 *Unknown Visitor processed!*\nTime: *%s*\nStatus: *%s*\nAction by: *%s*",
                    log.getTimestamp().toString(),
                    statusEmoji,
                    approver
            );

            MultiValueMap<String, String> map = new LinkedMultiValueMap<>();
            map.add("chat_id", String.valueOf(chatId));
            map.add("message_id", String.valueOf(messageId));
            map.add("caption", newCaption);
            map.add("parse_mode", "Markdown");
            map.add("reply_markup", "{\"inline_keyboard\": []}");

            HttpEntity<MultiValueMap<String, String>> request = new HttpEntity<>(map, headers);
            restTemplate.postForObject(url, request, String.class);
        } catch (Exception e) {
            System.err.println("[TelegramBot] Fail edit message: " + e.getMessage());
        }
    }

    public void sendVisitorNotification(AccessLog log) {
        if (!active) return;
        java.util.concurrent.CompletableFuture.runAsync(() -> {
            try {
                String url = String.format("https://api.telegram.org/bot%s/sendPhoto", botToken);
                HttpHeaders headers = new HttpHeaders();
                headers.setContentType(MediaType.MULTIPART_FORM_DATA);

                MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
                body.add("chat_id", chatId);

                File imageFile = new File("../visitor_snapshots/" + log.getImagePath());
                if (imageFile.exists()) {
                    body.add("photo", new FileSystemResource(imageFile));
                } else {
                    System.out.println("[TelegramBot] Snapshot file not found: " + imageFile.getAbsolutePath());
                    return;
                }

                String caption = String.format(
                        "🔔 *Unknown Visitor Detected!*\nTime: *%s*\nStatus: *PENDING APPROVAL*",
                        log.getTimestamp().toString()
                );
                body.add("caption", caption);
                body.add("parse_mode", "Markdown");

                String replyMarkup = String.format(
                        "{\"inline_keyboard\": [[{\"text\":\"Approve ✅\",\"callback_data\":\"APPROVE_%d\"},{\"text\":\"Deny ❌\",\"callback_data\":\"DENY_%d\"}]]}",
                        log.getId(), log.getId()
                );
                body.add("reply_markup", replyMarkup);

                HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);
                String response = restTemplate.postForObject(url, requestEntity, String.class);
                System.out.println("[TelegramBot] Notification sent successfully! Response: " + response);
            } catch (Exception e) {
                System.err.println("[TelegramBot] Error sending notification: " + e.getMessage());
            }
        });
    }
}
