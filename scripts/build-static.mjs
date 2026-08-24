import {cp, mkdir, rm, writeFile} from "node:fs/promises";
import {resolve} from "node:path";

const root = resolve(import.meta.dirname, "..");
const output = resolve(root, "web-dist");
const paths = ["index.html", "css", "js", "wasm", "vendor"];

await rm(output, {recursive: true, force: true});
await mkdir(output, {recursive: true});
for (const path of paths) {
  await cp(resolve(root, path), resolve(output, path), {recursive: true});
}
await writeFile(resolve(output, ".nojekyll"), "", "utf8");
console.log(`Static site built at ${output}`);
