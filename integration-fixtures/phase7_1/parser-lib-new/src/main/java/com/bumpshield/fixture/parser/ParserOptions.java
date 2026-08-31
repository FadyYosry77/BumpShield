package com.bumpshield.fixture.parser;

public final class ParserOptions {
    public static final ParserOptions DEFAULT = new ParserOptions();

    private ParserOptions() {
    }

    String normalize(String value) {
        return value.trim();
    }
}
