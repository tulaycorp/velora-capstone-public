import { expect, test } from "@playwright/test";

test("loads analytics once and ignores fresh focus revalidation", async ({ page }) => {
  await page.context().addCookies([
    {
      name: "velora-selected-store-id",
      value: "store-1",
      domain: "localhost",
      path: "/"
    }
  ]);
  let analyticsRequestCount = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/backend/analytics") {
      analyticsRequestCount += 1;
    }
  });

  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Performance trend" })).toBeVisible();
  await expect(page.getByText("₱128,450.00").first()).toBeVisible();
  await expect.poll(() => analyticsRequestCount).toBe(1);

  await page.evaluate(() => {
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("focus"));
  });

  await page.waitForTimeout(500);
  expect(analyticsRequestCount).toBe(1);
});

test("keeps analytics visible while filters refresh and uses themed dropdown borders", async ({ page }) => {
  await page.route("**/api/backend/analytics/business?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("currency") === "USD" || url.searchParams.get("preset") === "7d") {
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    await route.continue();
  });

  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Performance trend" })).toBeVisible();

  const timeframeTrigger = page.getByRole("combobox").filter({ hasText: "Last 30 days" });
  await timeframeTrigger.click();
  const timeframeListbox = page.getByRole("listbox");
  await expect(timeframeListbox).toBeVisible();
  const contentBorder = await timeframeListbox.evaluate(
    (element) => getComputedStyle(element).borderTopColor
  );
  expect(contentBorder).not.toBe("rgb(229, 231, 235)");
  await page.getByRole("option", { name: "Last 7 days" }).click();
  await expect(page.getByRole("button", { name: "Refreshing" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Performance trend" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();

  await page.getByRole("combobox").filter({ hasText: "PHP" }).click();
  await page.getByRole("option", { name: "USD" }).click();
  await expect(page.getByRole("button", { name: "Refreshing" })).toBeVisible();
  await expect(page.getByText("₱128,450.00").first()).toBeVisible();
  await expect(page.getByText("$128,450.00").first()).toBeVisible();
});

test("exposes product, expense, SEO, and unmatched mapping workspaces", async ({ page }) => {
  await page.goto("/analytics");

  await page.getByRole("tab", { name: "Products" }).click();
  await expect(page.getByRole("heading", { name: "Product performance" })).toBeVisible();
  await expect(page.getByText("Coastal Wildflower Gallery Print")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^velora-product-analytics-\d{4}-\d{2}-\d{2}\.csv$/);
  await expect(page.getByRole("status")).toHaveText(
    "Product analytics CSV download started."
  );
  const stream = await download.createReadStream();
  let csv = "";
  for await (const chunk of stream) {
    csv += chunk.toString();
  }
  expect(csv).toContain('"Product","Store","Units"');
  expect(csv).toContain('"Coastal Wildflower Gallery Print","E2E Print Shop","42"');

  await page.getByRole("tab", { name: "Stores" }).click();
  await expect(page.getByRole("heading", { name: "Printify" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gelato" })).toBeVisible();
  await expect(page.getByRole("tabpanel").locator("h3")).toHaveText([
    "Gelato",
    "Printify",
  ]);
  await expect(page.getByText("Peddlex", { exact: true })).toBeVisible();
  await expect(page.getByText("Craftarriane", { exact: true })).toBeVisible();
  await expect(page.getByText("Peddlex -> shopify")).toHaveCount(0);
  const storeDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const storeDownload = await storeDownloadPromise;
  expect(storeDownload.suggestedFilename()).toMatch(
    /^velora-store-analytics-\d{4}-\d{2}-\d{2}\.csv$/
  );
  await expect(page.getByRole("status")).toHaveText(
    "Store analytics CSV download started."
  );

  await page.getByRole("tab", { name: "Expenses" }).click();
  await expect(page.getByRole("heading", { name: "Expense ledger" })).toBeVisible();
  await expect(page.getByText("Marketplace campaign")).toBeVisible();
  await expect(page.getByText("1–25 of 52")).toBeVisible();
  const secondExpensePage = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname.endsWith("/analytics/business/details") &&
      url.searchParams.get("resource") === "expenses" &&
      url.searchParams.get("page") === "2" &&
      url.searchParams.get("page_size") === "25"
    );
  });
  await page.getByRole("link", { name: "Go to next page" }).click();
  await secondExpensePage;
  await expect(page.getByText("Page 2 of 3")).toBeVisible();
  await expect(page.getByText("Paged expense 26")).toBeVisible();
  await page.getByRole("button", { name: "Add expense" }).click();
  await expect(page.getByRole("dialog", { name: "Add expense" })).toBeVisible();
  await page.getByLabel("Date").click();
  const expenseCalendar = page.getByRole("grid");
  await expect(expenseCalendar).toBeVisible();
  await expenseCalendar.locator('button[data-day]').filter({ hasText: /^15$/ }).first().click();
  await expect(page.getByLabel("Date")).toContainText("15");
  await expect(page.getByRole("grid")).toBeHidden();
  await expect(page.getByRole("dialog", { name: "Add expense" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("dialog", { name: "Add expense" })).toBeHidden();

  await page.getByRole("tab", { name: "SEO" }).click();
  await expect(page.getByText("authoritative keyword rank")).toBeVisible();

  await page.getByRole("tab", { name: /Operations/ }).click();
  await page.getByRole("button", { name: "Map product" }).click();
  await expect(page.getByRole("dialog", { name: "Map unmatched item" })).toBeVisible();
});
