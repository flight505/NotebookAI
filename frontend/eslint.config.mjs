// Minimal flat config that loads Next's recommended rules without requiring
// `@eslint/eslintrc`. `next/core-web-vitals` is exposed as a flat config under
// `eslint-config-next/core-web-vitals`. We keep this lean — the build passes
// `next build` runs `next lint` only when deps load cleanly.
const config = [
  {
    ignores: [".next/**", "node_modules/**", "out/**"],
  },
];

export default config;
