#version 330 core

in vec2 vUV;
out vec4 FragColor;

uniform sampler2D uInput;

//Texel size
uniform vec2 uTexelSize;

//Per channel blur radii (R=0, G=2, B=6) from Schaeffel
uniform ivec3 uRadiusRGB;

//Gaussian sigma per channel in pixels
uniform vec3 uSigmaRGB;

//Compile time direction, horizontal is vec2(1,0), vertical is vec2(0,1)
#ifndef BLUR_DIR
  #error "BLUR_DIR not defined. Define BLUR_DIR as vec2(1,0) or vec2(0,1) before compiling"
#endif

//Max blur radius, any larger and the sampling size becomes too large
const int MAX_RADIUS = 10;



//Gaussian helpers
//Gauss weighting for distance x and sigma
float gaussWeight(float x, float sigma) {
    // sigma must be > 0
    float s = max(sigma, 1e-6);
    return exp(-0.5 * (x * x) / (s * s));
}

//Normalize factor for 1D gaussian
// Computes: w0 + 2*sum_{i=1..radius} w(i)
float gaussNorm(int radius, float sigma) {
    float sum = gaussWeight(0.0, sigma);
    for (int i = 1; i <= MAX_RADIUS; ++i) {
        if (i > radius) break;
        float w = gaussWeight(float(i), sigma);
        sum += 2.0 * w;
    }
    return max(sum, 1e-12);
}

//Sample RGB values of the pixel
vec3 sampleRGB(vec2 uv){
  return texture(uInput, uv).rgb;
}





//Blur logic
//-----------------

//perform 1D separable gaussian blur in the BLUR_DIR direction
//use radii and sigma per channel
//channels are weighted separably
//only one texture fetch, just use the RGB values from the same sample
vec3 blurSeparableGaussian(vec2 uv){
  int rR=clamp(u.RadiusRGB.r, 0, MAX_RADIUS);

  //clamp to avoid unsafe values
  int radiusR = clamp(uRadiusRGB.r, 0, MAX_RADIUS);
  int radiusG = clamp(uRadiusRGB.g, 0, MAX_RADIUS);
  int radiusB = clamp(uRadiusRGB.r, 0, MAX_RADIUS);

  //separate sigma to each channel
  float sigmaR = uSigmaRGB.R;
  float sigmaG = uSigmaRGB.G;
  float sigmaB = uSigmaRGB.B;

  //if radius 0 then go thru unaffected
  float nR = (radiusR == 0) ? 1.0 : gaussNorm(rR, sR);
  float nG = (radiusG == 0) ? 1.0 : gaussNorm(rG, sG);
  float nB = (radiusB == 0) ? 1.0 : gaussNorm(rB, sB);

  //accumulator for the three colour values
  vec3 accumulator = vec3(0.0);

  //Center tap, the pixel itself. get w value 
  {
    vec3 c = sampleRGB(uv);
    float wR = (radiusR == 0) ? 1.0 : gaussWeight(0.0, sigmaR) / nR;
    float wG = (radiusG == 0) ? 1.0 : gaussWeight(0.0, sigmaG) / nG;
    float wB = (radiusB == 0) ? 1.0 : gaussWeight(0.0, sigmaB) / nB;

    //Use weighting to accumulate colour value
    accumulator += vec3(c.r * wR, c.g * wG, c.b * wB);
  }


//Symmetric taps in 1d to either side
for (int i=1; i<=MAX_RADIUS; i++){
    //if i exceeds radii for the channel, break
    if (i > radiusR && i>radiusG && i>radiusB) break;

    //Which pixels are we going to?
    vec2 offset = float(i)*(uTexelSize * BLUR_BIR);

    //Sample the points
    vec3 c1 = sampleRGB(uv+offset);
    vec3 c2 = sampleRGB(uv-offset);

    //Apply weighting, 0 if outside channel radius
    float wR = (i <= radiusR && radiusR != 0) ? (gaussWeight(float(i), sigmaR) / nR) : 0.0;
    float wG = (i <= radiusG && radiusG != 0) ? (gaussWeight(float(i), sigmaG) / nG) : 0.0;
    float wB = (i <= radiusB && radiusB != 0) ? (gaussWeight(float(i), sigmaB) / nB) : 0.0;


    //Accumulate in a loop to the accumulator values for RGB channels
    accumulator += vec3((c1.r+c2.r) * wR,
                        (c1.g+c2.g) *wG,
                        (c1.b+c2.b) *wB);

    }

    return accumulator;
}



void main(){
  vec3 outRGB = blurSeparableGaussian(vUV);
  FragColor = vec4(outRGB, 1.0);
}
