//A fragment shader applying chromatic filtering

#version 330 core
in vec2 vUV;
out vec4 FragColor;

uniform sampler2D uFrame;

// Gaze + frame info
uniform vec2  uResolution;   // (width, height) in pixels
uniform vec2  uGazePx;        // gaze in pixels (same coordinate space as frame)
uniform int   uMaskMode;      // 0=full-frame, 1=circle hard, 2=gaussian feather

// Mask params
uniform float uRadiusPx;      // foveal radius (no filter) in pixels
uniform float uFeatherPx;     // transition width in pixels (for gaussian-ish edge)

// Filter params
uniform float uFilterStrength; // 0..1
uniform float uChromaOffsetPx;  // channel offset magnitude in pixels

// --- Helpers ---
vec2 pxToUV(vec2 px) { return px / uResolution; }

// Distance from this fragment to gaze in *pixels*
float gazeDistancePx(vec2 fragUV) {
    vec2 fragPx = fragUV * uResolution;
    return length(fragPx - uGazePx);
}

// Mask weight: 0 near gaze, 1 in periphery
float peripheralWeight(float distPx) {
    if (uMaskMode == 0) {
        return 1.0; // full-frame filtering
    }

    // Hard circle: step outside radius
    if (uMaskMode == 1) {
        return step(uRadiusPx, distPx);
    }

    //Gaussian blur: 0 inside
    if (uMaskMode == 2) {
        return 1.0- exp(-3.0 * t * t);
    }
}

// Simple chromatic filter: channel-dependent UV offsets away/toward gaze
vec3 chromaticFilter(vec2 uv) {
    // Direction from gaze to current fragment (in UV space)
    vec2 gazeUV = pxToUV(uGazePx);
    vec2 dir = uv - gazeUV;
    float lenDir = length(dir);
    vec2 n = (lenDir > 1e-6) ? (dir / lenDir) : vec2(0.0, 0.0);

    // Convert pixel offsets to UV
    vec2 offUV = (uChromaOffsetPx / uResolution) * n;

    // Sample with different offsets per channel.
    // This creates a chromatic separation effect that increases with radius.
    float r = texture(uFrame, uv + offUV).r;
    float g = texture(uFrame, uv).g;
    float b = texture(uFrame, uv - offUV).b;

    return vec3(r, g, b);
}

void main() {
    vec3 original = texture(uFrame, vUV).rgb;

    float distPx = gazeDistancePx(vUV);
    float w = peripheralWeight(distPx); // 0..1
    w *= clamp(uFilterStrength, 0.0, 1.0);

    vec3 filtered = chromaticFilter(vUV);

    vec3 outRgb = mix(original, filtered, w);
    FragColor = vec4(outRgb, 1.0);
}
