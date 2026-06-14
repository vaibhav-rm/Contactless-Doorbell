package com.doorbell.backend.websocket;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

@Component
public class DoorbellWebSocketHandler extends TextWebSocketHandler {

    private final Set<WebSocketSession> sessions = Collections.synchronizedSet(new HashSet<>());

    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        sessions.add(session);
        System.out.println("New WebSocket connection established: " + session.getId());
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
        String payload = message.getPayload();
        System.out.println("Received WS payload: " + payload);
        
        // Broadcast incoming messages to all OTHER sessions (or all sessions for simplicity)
        broadcast(payload, session);
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) throws Exception {
        sessions.remove(session);
        System.out.println("WebSocket connection closed: " + session.getId() + " Status: " + status);
    }

    public void broadcast(String message) {
        broadcast(message, null);
    }

    public void broadcast(String message, WebSocketSession senderSession) {
        synchronized (sessions) {
            for (WebSocketSession session : sessions) {
                if (session.isOpen() && (senderSession == null || !session.getId().equals(senderSession.getId()))) {
                    try {
                        session.sendMessage(new TextMessage(message));
                    } catch (IOException e) {
                        System.err.println("Error sending WebSocket message: " + e.getMessage());
                    }
                }
            }
        }
    }
}
