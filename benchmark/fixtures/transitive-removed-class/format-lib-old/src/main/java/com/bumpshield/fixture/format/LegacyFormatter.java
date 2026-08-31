package com.bumpshield.fixture.format;

public final class LegacyFormatter {
    public String normalize(String value) {
        return value.trim().replaceAll("\\s+", " ");
    }
}
