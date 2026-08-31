package com.bumpshield.fixture.app;

import com.bumpshield.fixture.parser.Parser;

public final class TextNormalizer {
    private final Parser parser = new Parser();

    public String normalize(String value) {
        return parser.parseValue(value);
    }
}
