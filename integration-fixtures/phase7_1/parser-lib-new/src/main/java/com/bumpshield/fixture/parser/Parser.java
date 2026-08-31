package com.bumpshield.fixture.parser;

public final class Parser {
    public String parse(String value, ParserOptions options) {
        return options.normalize(value);
    }
}
