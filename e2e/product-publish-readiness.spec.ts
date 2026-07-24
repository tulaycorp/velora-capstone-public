import { expect, test } from "@playwright/test";

test("blocks publish while required saved media is missing and focuses the blocker", async ({ page }) => {
  await page.goto("/products/incomplete-product");

  await expect(page.getByRole("button", { name: "Send to Etsy" })).toBeDisabled();
  await page.getByRole("button", { name: "Product image uploaded" }).click();
  await expect(page.locator("#publish-mockups")).toBeFocused();
});

test("focuses a structured server readiness failure", async ({ page }) => {
  await page.goto("/products/server-reject-product");

  await page.getByRole("button", { name: "Send to Etsy" }).click();

  await expect(page.getByText("This product is not ready to send.")).toBeVisible();
  await expect(page.locator("#publish-mockups")).toBeFocused();
});

test("shows the stale saved-revision path without enabling a no-op save", async ({ page }) => {
  await page.goto("/products/stale-product");

  await page.getByRole("button", { name: "Send to Etsy" }).click();

  await expect(page.getByText(/This product changed after the page loaded/)).toBeVisible();
  await expect(page.locator("#publish-save")).toBeDisabled();
});

test("submits the exact saved revision and shows its immutable job context", async ({ page }) => {
  await page.goto("/products/ready-product");

  await page.getByRole("button", { name: "Send to Etsy" }).click();

  await expect(page.getByText(/Submitted revision 7/)).toBeVisible();
  await expect(page.getByText("Your product was sent to Etsy.")).toBeVisible({ timeout: 10_000 });
  await expect(page).toHaveURL(/\/products\/ready-product$/);
});

test("disables no-op sends and keeps existing Etsy edits in Velora", async ({ page }) => {
  await page.goto("/products/published-edit-product");

  const saveButton = page.getByRole("button", { name: "Save changes" });
  const publishButton = page.getByRole("button", { name: "Send to Etsy" });
  await expect(saveButton).toBeDisabled();
  await expect(publishButton).toBeDisabled();

  await page.locator("#publish-title").fill("Updated Etsy listing title");
  await expect(saveButton).toBeEnabled();
  await expect(publishButton).toBeDisabled();

  await saveButton.click();
  await expect(page.getByText("Changes saved.")).toBeVisible();
  await expect(saveButton).toBeDisabled();
  await expect(publishButton).toBeEnabled();

  await publishButton.click();
  await expect(page.getByText("Your product was sent to Etsy.")).toBeVisible({ timeout: 10_000 });
  await expect(page).toHaveURL(/\/products\/published-edit-product$/);
  await expect(publishButton).toBeDisabled();
});
