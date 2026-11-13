import { expect, test } from "@playwright/test";

// Provenance values returned by the fake adapter in e2e/api_launcher.py.
const FAKE_MODEL_ID = "e2e-fake-model";
const FAKE_CONFIGURATION_VERSION = "E2E-FAKE/v1";

test("creates a project and saves a fake-model synthetic analysis", async ({
  page,
}) => {
  const projectName = `E2E synthetic project ${Date.now()}`;
  const syntheticText = "Checkout must reject a blank cart ID.";

  await page.goto("/");

  await page.getByLabel("Project name").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByText(`Created ${projectName}.`)).toBeVisible();

  const detail = page.getByRole("region", { name: "Project detail" });
  await expect(detail.getByText(projectName, { exact: true })).toBeVisible();

  await detail.getByLabel("Synthetic text only").fill(syntheticText);
  await detail.getByRole("button", { name: "Run and save analysis" }).click();
  await expect(
    page.getByText(`Saved synthetic analysis for ${projectName}.`),
  ).toBeVisible();

  const runs = detail.getByRole("region", { name: "Saved analysis runs" });
  const run = runs.getByRole("listitem");
  await expect(run).toHaveCount(1);
  await expect(run.getByText(syntheticText, { exact: true })).toBeVisible();
  await expect(run).toContainText(`"summary": "Synthetic: ${syntheticText}"`);
  await expect(run).toContainText(
    `${FAKE_MODEL_ID} · ${FAKE_CONFIGURATION_VERSION} · 7 tokens`,
  );
});
