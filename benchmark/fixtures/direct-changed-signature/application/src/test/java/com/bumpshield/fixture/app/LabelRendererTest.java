package com.bumpshield.fixture.app;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public class LabelRendererTest {
    @Test
    public void trimsAndUppercasesLabel() {
        assertEquals("HELLO WORLD", new LabelRenderer().label(" hello world "));
    }
}
