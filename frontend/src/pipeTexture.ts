type PipeMaterial = "oil" | "gas" | "sea";

const coatings: Record<PipeMaterial, [number, number, number]> = {
  oil: [229, 162, 110],
  gas: [78, 190, 145],
  sea: [103, 200, 240],
};

// Tiny, repeatable map material: cylindrical shading, brushed coating and a weld.
// The weld spacing is decorative screen styling, not surveyed pipe segments.
export function createPipeTexture(material: PipeMaterial) {
  const width = 128;
  const height = 16;
  const data = new Uint8Array(width * height * 4);
  const base = coatings[material];
  for (let y = 0; y < height; y++) {
    const t = y / (height - 1);
    const roundness = Math.sin(t * Math.PI);
    const sheen = 0.26 * Math.exp(-Math.pow((t - 0.3) / 0.13, 2));
    const shade = 0.5 + 0.45 * roundness;
    for (let x = 0; x < width; x++) {
      const offset = (y * width + x) * 4;
      // The sea material retains visible gaps, including along the shaded edges.
      if (material === "sea" && x >= 72) continue;
      const weld = material === "sea" ? 35 : 63;
      const grain = Math.sin((x * 17 + y * 31) * 0.73) * 1.6;
      const seamShade = x >= weld && x <= weld + 2 ? 0.58 : 1;
      const seamSheen = x === weld - 1 || x === weld + 3 ? 15 : 0;
      for (let channel = 0; channel < 3; channel++) {
        const color = base[channel] * shade * (1 - sheen) + 255 * sheen;
        data[offset + channel] = Math.round(
          Math.min(255, Math.max(0, color * seamShade + seamSheen + grain)),
        );
      }
      data[offset + 3] = 255;
    }
  }
  return { width, height, data };
}
