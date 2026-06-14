package com.doorbell.backend.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.File;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                .allowedOrigins("*")
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .maxAge(3600);
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        // Expose stored faces
        String storedFacesPath = new File("../stored_faces/").getAbsolutePath();
        registry.addResourceHandler("/stored_faces/**")
                .addResourceLocations("file:" + storedFacesPath + "/");

        // Expose visitor snapshots
        String snapshotsPath = new File("../visitor_snapshots/").getAbsolutePath();
        registry.addResourceHandler("/visitor_snapshots/**")
                .addResourceLocations("file:" + snapshotsPath + "/");
    }
}
