const { test, expect } = require("@playwright/test");

const baseUrl = process.env.CW2_WEB_BASE_URL || "http://127.0.0.1:8011";

test.describe("CW2 web workbench smoke flow", () => {
  test("loads navigation and opens Report Studio", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });

    await expect(page.getByText("Report Studio")).toBeVisible();
    await page.getByText("Report Studio").click();

    await expect(page.getByText("LLM Connector")).toBeVisible();
    await expect(page.getByText("AI Report Output")).toBeVisible();
  });

  test("opens scenario selector modal", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });

    await page.getByText("Scenario").first().click();

    await expect(page.getByText("Choose Active Scenario")).toBeVisible();
    await expect(page.getByText("Create New Scenario")).toBeVisible();
  });

  test("covers scenario to runner to report studio review flow", async ({ page }) => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });

    await page.getByText("Scenario Builder").click();
    await expect(page.getByText("Parameter Bar")).toBeVisible();
    await page.getByRole("button", { name: /^Save/ }).click();
    await expect(page.getByText(/saved|No setup changes/i)).toBeVisible();

    await page.getByText("Backtest Runner").click();
    await expect(page.getByText("Run Queue")).toBeVisible();
    await page.getByRole("button", { name: /Run|Queue|Schedule/ }).first().click();
    await expect(page.getByText(/Queued|Scheduled|Running|saved/i)).toBeVisible();

    await page.getByText("Run History").click();
    await expect(page.getByText(/Recent jobs|Execution logs|Generated outputs/i)).toBeVisible();

    await page.getByText("Report Studio").click();
    await expect(page.getByText("AI Report Output")).toBeVisible();
    await expect(page.getByText("Report Sections")).toBeVisible();
  });
});
