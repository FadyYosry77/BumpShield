package com.bumpshield.fixture.app;

import com.bumpshield.fixture.core.CoreParsers;
import com.bumpshield.fixture.parser.Parser;

public final class TextNormalizer {
    public String normalize(String value) {
        Parser parser = CoreParsers.create();
        return parser.parseValue(value);
    }
}
