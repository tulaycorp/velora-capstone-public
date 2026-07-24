import { expect, test, type Page } from "@playwright/test";

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64"
);

function velSection(page: Page) {
  return page.locator('[aria-labelledby="generate-with-vel-title"]');
}

test("creates a saved Product Studio draft, reviews Vel output, edits it, and applies selected fields", async ({
  page
}) => {
  await page.goto("/product-studio");

  await page.locator("#product-studio-design-input").setInputFiles({
    name: "studio-design.png",
    mimeType: "image/png",
    buffer: PNG_1X1
  });
  await page
    .getByPlaceholder(/Describe the artwork itself/)
    .fill("A calm botanical garden illustration in teal and coral.");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page).toHaveURL(/\/products\/studio-ai-product$/);

  const assistant = velSection(page);
  await assistant.getByRole("button", { name: "Generate listing" }).click();
  await expect(assistant.getByText("Review suggestions")).toBeVisible();

  const suggestedTitle = assistant.getByRole("textbox").first();
  await suggestedTitle.fill("Seller-edited botanical canvas title");
  await assistant
    .getByRole("button", { name: "Apply selected fields" })
    .click();

  await expect(page.locator("#publish-title")).toHaveValue(
    "Seller-edited botanical canvas title"
  );
  await expect(assistant.getByText("Review suggestions")).toBeHidden();
});

test("rate-limit failure preserves manual content and allows a retry", async ({
  page
}) => {
  await page.goto("/products/ai-rate-limit-product");
  const assistant = velSection(page);

  await assistant.getByRole("button", { name: "Generate listing" }).click();
  await expect(
    assistant.getByText("AI generation limit reached. Try again later.")
  ).toBeVisible();
  await expect(page.locator("#publish-title")).toHaveValue(
    "Architecture Review Canvas"
  );

  await assistant.getByRole("button", { name: "Generate listing" }).click();
  await expect(assistant.getByText("Review suggestions")).toBeVisible();
  await expect(page.locator("#publish-title")).toHaveValue(
    "Architecture Review Canvas"
  );
});

test("generates again and replaces the prior suggestion", async ({ page }) => {
  await page.goto("/products/ai-regenerate-product");
  const assistant = velSection(page);

  await page.locator("#publish-title").fill("Unsaved manual title");
  await assistant.getByRole("button", { name: "Generate listing" }).click();
  await expect(assistant.getByText("Review suggestions")).toBeVisible();

  await assistant.getByRole("textbox").first().fill("Discard this suggestion");
  await assistant.getByRole("button", { name: "Generate again" }).click();
  await expect(assistant.getByRole("textbox").first()).toHaveValue(
    "Vel Generated Botanical Canvas Title"
  );
  await expect(page.locator("#publish-title")).toHaveValue("Unsaved manual title");
});

test("stale apply preserves the saved product and asks for refresh or regeneration", async ({
  page
}) => {
  await page.goto("/products/ai-stale-product");
  const assistant = velSection(page);

  await assistant.getByRole("button", { name: "Generate listing" }).click();
  await expect(assistant.getByText("Review suggestions")).toBeVisible();
  await assistant
    .getByRole("button", { name: "Apply selected fields" })
    .click();

  await expect(
    assistant.getByText(/This product changed.*Refresh and regenerate/i)
  ).toBeVisible();
  await expect(page.locator("#publish-title")).toHaveValue(
    "Architecture Review Canvas"
  );
  await expect(assistant.getByText("Review suggestions")).toBeVisible();
});
