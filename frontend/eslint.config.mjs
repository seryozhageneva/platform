import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "src/api.generated.ts"] },
  { files: ["**/*.ts", "**/*.tsx"], extends: [js.configs.recommended, ...tseslint.configs.recommended] },
  {
    files: ["src/**/*.tsx"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
  {
    files: ["generate-api.mjs"],
    ...js.configs.recommended,
    languageOptions: { globals: { console: "readonly", process: "readonly", URL: "readonly" } },
  },
);
