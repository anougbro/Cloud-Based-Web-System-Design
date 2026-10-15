import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

// Flat config. The rules that matter here are the React Hooks ones: this
// codebase holds async loads behind sequence guards, and a stale closure or
// a missing dependency is the kind of defect that only shows up as a
// duplicated request under load.
export default [
  { ignores: ["dist/**", "node_modules/**"] },

  js.configs.recommended,

  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2024,
      globals: { ...globals.browser },
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // Only components may export components. api.js exports helpers, and
      // mixing the two is what makes fast-refresh unreliable.
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // An unused binding is dead weight, not style: it signals a refactor
      // that stopped halfway.
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],

      // Catches the typo class of bug that has no runtime symptom.
      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-console": ["error", { allow: ["warn", "error"] }],
    },
  },

  {
    files: ["**/*.config.js", "vite.config.js"],
    languageOptions: { globals: { ...globals.node } },
  },

  {
    files: ["**/*.test.js"],
    languageOptions: { globals: { ...globals.node } },
    rules: { "no-console": "off" },
  },
];
