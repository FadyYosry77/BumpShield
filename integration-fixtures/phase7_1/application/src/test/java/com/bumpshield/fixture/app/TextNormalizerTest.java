package com.bumpshield.fixture.app;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class TextNormalizerTest {
    private final TextNormalizer normalizer = new TextNormalizer();

    @Test
    public void trimsOuterWhitespace() {
        assertEquals("hello", normalizer.normalize(" hello "));
    }

    @Test
    public void preservesInnerWhitespace() {
        assertEquals("hello  world", normalizer.normalize(" hello  world "));
    }

    @Test
    public void supportsWhitespaceOnlyInput() {
        assertEquals("", normalizer.normalize("   "));
    }
}
