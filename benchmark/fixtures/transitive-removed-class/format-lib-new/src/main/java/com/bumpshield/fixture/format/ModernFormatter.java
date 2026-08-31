package com.bumpshield.fixture.format;

public final class ModernFormatter {
    public String normalize(String value) {
        return value.trim().replaceAll("\\s+", " ");
    }
}
