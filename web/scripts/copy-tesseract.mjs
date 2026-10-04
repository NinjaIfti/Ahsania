// Copies Tesseract.js worker, WASM cores and English data into public/tesseract so nothing loads from a CDN.
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dest = fileURLToPath(new URL("../public/tesseract/", import.meta.url));

let tesseractDir;
try {
  tesseractDir = dirname(require.resolve("tesseract.js/package.json"));
} catch {
  console.log("tesseract.js not installed yet — skipping asset copy");
  process.exit(0);
}
const coreDir = dirname(require.resolve("tesseract.js-core/package.json"));
const langFile = join(dirname(require.resolve("@tesseract.js-data/eng/package.json")), "4.0.0", "eng.traineddata.gz");
if (!existsSync(langFile)) throw new Error(`missing ${langFile}`);

mkdirSync(join(dest, "core"), { recursive: true });
mkdirSync(join(dest, "lang"), { recursive: true });
cpSync(join(tesseractDir, "dist", "worker.min.js"), join(dest, "worker.min.js"));
for (const file of readdirSync(coreDir).filter((f) => f.endsWith(".wasm.js"))) {
  cpSync(join(coreDir, file), join(dest, "core", file));
}
cpSync(langFile, join(dest, "lang", "eng.traineddata.gz"));
console.log(`tesseract assets copied to ${dest}`);
