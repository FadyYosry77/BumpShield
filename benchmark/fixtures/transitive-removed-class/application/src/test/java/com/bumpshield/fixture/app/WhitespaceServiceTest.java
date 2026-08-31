package com.bumpshield.fixture.app;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public class WhitespaceServiceTest {
    @Test
    public void trimsAndCollapsesWhitespace() {
        assertEquals("hello world", new WhitespaceService().normalize("  hello   world  "));
    }

    @Test
    public void retainsVisibleCharacters() {
        assertEquals("alpha beta", new WhitespaceService().normalize("alpha  beta"));
    }
}
