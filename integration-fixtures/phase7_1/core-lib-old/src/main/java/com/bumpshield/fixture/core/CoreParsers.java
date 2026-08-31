package com.bumpshield.fixture.core;

import com.bumpshield.fixture.parser.Parser;

public final class CoreParsers {
    private CoreParsers() {
    }

    public static Parser create() {
        return new Parser();
    }
}
