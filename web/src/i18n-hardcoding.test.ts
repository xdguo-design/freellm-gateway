import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function sourceFiles(): string[] {
  const root = fileURLToPath(new URL(".", import.meta.url));
  const pages = fileURLToPath(new URL("./pages/", import.meta.url));
  const components = fileURLToPath(new URL("./components/", import.meta.url));
  return [
    `${root}/App.tsx`,
    ...readdirSync(pages).filter((name) => name.endsWith(".tsx")).map((name) => `${pages}/${name}`),
    ...readdirSync(components).filter((name) => name.endsWith(".tsx")).map((name) => `${components}/${name}`),
  ];
}

describe("i18n source hygiene", () => {
  it("keeps user-facing Chinese text inside the translation catalog", () => {
    const violations = sourceFiles()
      .map((path) => ({ path, source: readFileSync(path, "utf8") }))
      .filter(({ source }) => /[\u3400-\u9fff]/.test(source))
      .map(({ path }) => path);
    expect(violations).toEqual([]);
  });

  it("keeps shared technical labels behind translation keys", () => {
    const forbidden = [
      /<label>Provider(?: ID)?/,
      /<label>Base URL/,
      /<label>Reasoning Effort/,
      /<label>API Key/,
      /<th>Provider<\/th>/,
      /<th>Token<\/th>/,
      /<span>API Base<\/span>/,
    ];
    const violations = sourceFiles().flatMap((path) => {
      const source = readFileSync(path, "utf8");
      return forbidden.filter((pattern) => pattern.test(source)).map((pattern) => `${path}: ${pattern}`);
    });
    expect(violations).toEqual([]);
  });
});
