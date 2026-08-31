package com.bumpshield.fixture.app;

import com.bumpshield.fixture.renderer.Renderer;

public final class LabelRenderer {
    private final Renderer renderer = new Renderer();

    public String label(String value) {
        return renderer.render(value);
    }
}
