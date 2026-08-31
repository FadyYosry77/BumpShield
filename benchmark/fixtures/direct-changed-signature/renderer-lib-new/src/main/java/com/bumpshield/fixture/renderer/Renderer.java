package com.bumpshield.fixture.renderer;

public final class Renderer {
    public String render(String value, RenderMode mode) {
        String trimmed = value.trim();
        return mode == RenderMode.UPPERCASE
            ? trimmed.toUpperCase()
            : trimmed.toLowerCase();
    }
}
