#version 330 core

in vec2 vUV;
out vec4 FragColor;

// Input textures
uniform sampler2D uOriginal;  // sharp, unblurred frame
uniform sampler2D uBlurred;   // fully blurred frame

// Gaze position in normalized screen coordinates [0,1] x [0,1]
uniform vec2 uGazePos;

// Foveal region parameters (in normalized screen coordinates)
// uFovealRadius: radius where image is completely sharp (no blur)
// uTransitionWidth: width of transition zone from sharp to full blur
uniform float uFovealRadius;
uniform float uTransitionWidth;

void main() {
    // Calculate distance from current pixel to gaze position
    // Since screen may not be square, we should consider aspect ratio
    // But for simplicity, we'll use Euclidean distance in normalized coords
    vec2 diff = vUV - uGazePos;
    float distance = length(diff);
    
    // Calculate blend factor: 0.0 = sharp (fovea), 1.0 = blurred (periphery)
    // Within foveal radius: completely sharp
    // Beyond foveal radius + transition: completely blurred
    // In between: smooth transition using smoothstep
    
    float innerRadius = uFovealRadius;
    float outerRadius = uFovealRadius + uTransitionWidth;
    
    float blendFactor = smoothstep(innerRadius, outerRadius, distance);
    
    // Sample both textures
    vec3 sharp = texture(uOriginal, vUV).rgb;
    vec3 blurred = texture(uBlurred, vUV).rgb;
    
    // Blend between sharp and blurred
    vec3 result = mix(sharp, blurred, blendFactor);
    
    FragColor = vec4(result, 1.0);
}
