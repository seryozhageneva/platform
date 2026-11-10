import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const schema = execFileSync("uv", ["run", "--locked", "--no-sync", "python", "-m", "backend.api.export_openapi"], {
  cwd: fileURLToPath(new URL("..", import.meta.url)),
  encoding: "utf8",
});
const output = new URL("./src/api.generated.ts", import.meta.url);
const generated = astToString(await openapiTS(JSON.parse(schema), { alphabetize: true }));

if (process.argv.includes("--check")) {
  if (readFileSync(output, "utf8") !== generated) {
    console.error("Клиент устарел. Выполните pnpm --dir frontend api:generate.");
    process.exitCode = 1;
  }
} else {
  writeFileSync(output, generated);
}
