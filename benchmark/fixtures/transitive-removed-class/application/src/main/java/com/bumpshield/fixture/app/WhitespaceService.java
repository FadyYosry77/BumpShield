package com.bumpshield.fixture.app;

import com.bumpshield.fixture.format.LegacyFormatter;

public final class WhitespaceService {
    private final LegacyFormatter formatter = new LegacyFormatter();

    public String normalize(String value) {
        return formatter.normalize(value);
    }
}
