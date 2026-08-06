import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = 'http://localhost:8000';
const SHOTS = '/Users/YOUR_USERNAME/household-finance-tracker/web/verify-screens';
mkdirSync(SHOTS, { recursive: true });

const results = [];
function record(id, name, pass, detail) {
  results.push({ id, name, pass, detail });
  console.log(`${pass ? 'PASS' : 'FAIL'}  [${id}] ${name} — ${detail}`);
}

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
page.setDefaultTimeout(15000);

async function login(user, pass) {
  await page.goto(`${BASE}/login`);
  await page.fill('#username', user);
  await page.fill('#password', pass);
  await page.getByRole('button', { name: 'Sign In' }).click();
}

async function pickCategory(name) {
  // Focusing the combobox opens the full option list; typing triggers a blur that
  // closes it, so just focus and click the option directly.
  const input = page.getByPlaceholder('Category').first();
  for (let attempt = 0; attempt < 3; attempt++) {
    await input.click();
    // wait for the option list to actually populate (categories load async)
    try { await page.locator('#category-listbox button').first().waitFor({ timeout: 4000 }); }
    catch { await page.waitForTimeout(500); continue; }
    const opt = page.locator('#category-listbox button', { hasText: name }).first();
    if (await opt.isVisible().catch(() => false)) { await opt.click(); return; }
    await page.waitForTimeout(500);
  }
  throw new Error(`category option "${name}" never appeared`);
}

async function addExpense({ amount, currency, category, merchant }) {
  await page.getByPlaceholder('0.00').fill(amount);
  if (currency) await page.locator('form select').first().selectOption(currency);
  await pickCategory(category);
  if (merchant) await page.getByPlaceholder('Merchant (optional)').fill(merchant);
  await page.getByRole('button', { name: 'Add Expense' }).click();
}

try {
  // ── Check 1: Auth / isolation ────────────────────────────────────────────
  try {
    await ctx.clearCookies();
    await page.goto(`${BASE}/dashboard`);
    await page.waitForURL(/\/login/, { timeout: 10000 });
    const redirected = page.url().includes('/login');

    // wrong password
    await page.fill('#username', 'alice');
    await page.fill('#password', 'wrongpass');
    await page.getByRole('button', { name: 'Sign In' }).click();
    const alert = page.getByRole('alert');
    await alert.waitFor({ timeout: 10000 });
    const errText = (await alert.textContent())?.trim() ?? '';
    const errOk = errText.startsWith('Invalid username or password');

    // correct login
    await login('alice', 'changeme');
    await page.waitForURL(/\/dashboard/, { timeout: 10000 });
    const loggedIn = page.url().includes('/dashboard');
    await page.screenshot({ path: `${SHOTS}/01-dashboard-after-login.png` });

    record('1', 'Auth & isolation', redirected && errOk && loggedIn,
      `guard redirect=${redirected}, error="${errText}" (${errOk}), login→dashboard=${loggedIn}`);
  } catch (e) { record('1', 'Auth & isolation', false, `threw: ${e.message}`); }

  // ── Check 2: Fast entry ─────────────────────────────────────────
  try {
    await page.goto(`${BASE}/expenses`);
    await page.getByPlaceholder('0.00').waitFor();
    await addExpense({ amount: '12.50', currency: 'SGD', category: 'Food & Dining', merchant: 'Kopitiam' });
    const toast1 = page.getByText('Expense added');
    await toast1.waitFor({ timeout: 10000 });
    // form cleared (amount empty) and focused
    await page.waitForTimeout(500);
    const amountVal = await page.getByPlaceholder('0.00').inputValue();
    const focused = await page.evaluate(() => document.activeElement?.getAttribute('placeholder') === '0.00');
    // add a second one to prove clear-and-stay
    await addExpense({ amount: '8.00', currency: 'SGD', category: 'Transport', merchant: 'MRT' });
    await page.getByText('Expense added').waitFor({ timeout: 10000 });
    await page.screenshot({ path: `${SHOTS}/02-expenses-after-add.png` });
    record('2', 'Fast entry clear-and-stay + toast', amountVal === '' && focused,
      `toast shown, amount cleared=${amountVal === ''}, amount re-focused=${focused}`);
  } catch (e) { record('2', 'Fast entry', false, `threw: ${e.message}`); }

  // ── Check 3: Foreign currency ───────────────────────────────
  try {
    await page.goto(`${BASE}/expenses`);
    await page.getByPlaceholder('0.00').waitFor();
    await addExpense({ amount: '1500', currency: 'JPY', category: 'Travel', merchant: 'Tokyo Lunch' });
    await page.getByText('Expense added').waitFor({ timeout: 15000 });
    await page.waitForTimeout(800);
    // find the row that contains the JPY amount
    const jpyShown = await page.getByText('¥1,500').first().isVisible().catch(() => false);
    // the row should also show an SGD conversion (S$..) in the SGD column
    const row = page.locator('div.grid', { hasText: 'Tokyo Lunch' }).first();
    const rowText = (await row.textContent().catch(() => '')) ?? '';
    const sgdMatch = rowText.match(/S\$[\d,]+\.\d{2}/);
    const sgdShown = !!sgdMatch;
    // sanity: not 100x inflated — conversion should be a small SGD number (< 100) for ¥1500
    let notInflated = false;
    if (sgdMatch) {
      const v = parseFloat(sgdMatch[0].replace(/[S$,]/g, ''));
      notInflated = v > 0 && v < 100;
    }
    await page.screenshot({ path: `${SHOTS}/03-jpy-expense.png` });
    record('3', 'Foreign currency dual display', jpyShown && sgdShown && notInflated,
      `¥1,500 shown=${jpyShown}, SGD conv=${sgdMatch?.[0] ?? 'none'} (present=${sgdShown}, sane=${notInflated})`);
  } catch (e) { record('3', 'Foreign currency', false, `threw: ${e.message}`); }

  // ── Check 4: Edit + delete ───────────────────────────────────
  try {
    await page.goto(`${BASE}/expenses`);
    // Edit the Kopitiam (Food & Dining) row → amount 99.99
    const kopRow = page.locator('div.grid').filter({ hasText: 'Kopitiam' }).first();
    await kopRow.getByRole('button', { name: 'Edit expense', exact: true }).click();
    await page.locator('input[inputmode="decimal"]:not([placeholder])').fill('99.99');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await page.waitForTimeout(800);
    const edited = await page.getByText('S$99.99').first().isVisible().catch(() => false);

    // Delete the Tokyo Lunch (Travel) row, leaving Food&Dining + Transport with expenses
    const rowsBefore = await page.getByRole('button', { name: 'Delete expense', exact: true }).count();
    const tokyoRow = page.locator('div.grid').filter({ hasText: 'Tokyo Lunch' }).first();
    await tokyoRow.getByRole('button', { name: 'Delete expense', exact: true }).click();
    await page.getByText('Delete expense?').waitFor();
    const dlgCopyOk = await page.getByText('This cannot be undone.').first().isVisible();
    await page.getByRole('button', { name: 'Delete Expense', exact: true }).click();
    await page.waitForTimeout(800);
    const rowsAfter = await page.getByRole('button', { name: 'Delete expense', exact: true }).count();
    const tokyoGone = !(await page.getByText('Tokyo Lunch').first().isVisible().catch(() => false));
    await page.screenshot({ path: `${SHOTS}/04-after-edit-delete.png` });
    record('4', 'Inline edit + delete dialog', edited && dlgCopyOk && rowsAfter === rowsBefore - 1 && tokyoGone,
      `edit→S$99.99=${edited}, dialog copy ok=${dlgCopyOk}, rows ${rowsBefore}→${rowsAfter}, Tokyo Lunch removed=${tokyoGone}`);
  } catch (e) { record('4', 'Edit + delete', false, `threw: ${e.message}`); }

  // ── Check 5: Categories ─────────────────────────────────────────
  try {
    await page.goto(`${BASE}/categories`);
    await page.getByRole('button', { name: 'Add Category' }).first().waitFor();

    // 5a: add a category
    await page.getByRole('button', { name: 'Add Category' }).first().click();
    await page.locator('#cat-name').fill('Subscriptions');
    await page.getByRole('button', { name: 'Select color #06B6D4' }).click();
    await page.getByRole('button', { name: 'Select icon Tv2' }).click();
    await page.locator('form').getByRole('button', { name: 'Add Category' }).click();
    await page.waitForTimeout(800);
    const added = await page.getByText('Subscriptions', { exact: true }).first().isVisible().catch(() => false);

    // 5b: rename inline (rename Subscriptions → Streaming)
    await page.getByRole('button', { name: 'Rename Subscriptions' }).click();
    const renameInput = page.locator('input').filter({ hasText: '' }).first();
    // the rename input has the current value; locate the visible textbox
    const rn = page.getByRole('textbox').first();
    await rn.fill('Streaming');
    await rn.press('Enter');
    await page.waitForTimeout(800);
    const renamed = await page.getByText('Streaming', { exact: true }).first().isVisible().catch(() => false);

    // 5c: protected Other has no edit/delete
    const otherRow = page.locator('div.grid', { hasText: 'Other' }).filter({ hasText: '(protected)' }).first();
    const protectedShown = await otherRow.isVisible().catch(() => false);
    const otherDeleteCount = await page.getByRole('button', { name: 'Delete Other' }).count();

    // 5d: delete a category that has expenses → its expenses move to Other.
    // "Transport" holds the MRT expense added in check 2. Confirm the reassignment copy.
    let reassignCopyOk = false, deletedCat = false;
    const trDelete = page.getByRole('button', { name: 'Delete Transport', exact: true });
    if (await trDelete.count()) {
      await trDelete.first().click();
      await page.getByText("Delete 'Transport'?").waitFor();
      reassignCopyOk = await page.getByText('Expenses in this category will be moved to Other.').isVisible().catch(() => false);
      await page.getByRole('button', { name: 'Delete Category', exact: true }).click();
      await page.waitForTimeout(800);
      deletedCat = !(await page.getByText('Transport', { exact: true }).first().isVisible().catch(() => false));
    }
    await page.screenshot({ path: `${SHOTS}/05-categories.png` });
    record('5', 'Category add/rename/delete-reassign + Other protected',
      added && renamed && protectedShown && otherDeleteCount === 0 && reassignCopyOk && deletedCat,
      `add=${added}, rename=${renamed}, Other protected=${protectedShown} (no delete btn=${otherDeleteCount === 0}), reassign copy=${reassignCopyOk}, deleted=${deletedCat}`);
  } catch (e) { record('5', 'Categories', false, `threw: ${e.message}`); }

  // ── Check 6: Reports ────────────────────────────────────────
  try {
    await page.goto(`${BASE}/dashboard`);
    await page.waitForTimeout(1500);
    const totalSpend = await page.getByText('Total Spend').first().isVisible().catch(() => false);
    const canvases = await page.locator('canvas').count();
    // user toggle present
    const toggle = await page.getByText('Both', { exact: true }).first().isVisible().catch(() => false)
      || await page.getByRole('button', { name: /both/i }).first().isVisible().catch(() => false);
    // new "This month" summary rail (adapted from reference)
    const railHeading = await page.getByRole('heading', { name: 'This month' }).isVisible().catch(() => false);
    const railPartner = await page.getByText('Bob', { exact: true }).first().isVisible().catch(() => false);
    const addExpenseCta = await page.getByRole('link', { name: /add expense/i }).isVisible().catch(() => false);
    await page.screenshot({ path: `${SHOTS}/06-dashboard.png`, fullPage: true });

    await page.goto(`${BASE}/reports`);
    await page.waitForTimeout(1200);
    const monthlyTab = await page.getByRole('tab', { name: /monthly/i }).first().isVisible().catch(() => false)
      || await page.getByText('Monthly', { exact: true }).first().isVisible().catch(() => false);
    const yearlyTab = await page.getByText('Yearly', { exact: true }).first().isVisible().catch(() => false);
    // breakdown table footing: look for "Total" row
    const breakdownTotal = await page.getByText('Total', { exact: false }).first().isVisible().catch(() => false);
    await page.screenshot({ path: `${SHOTS}/07-reports.png` });
    record('6', 'Dashboard + Reports + summary rail',
      totalSpend && canvases >= 1 && monthlyTab && yearlyTab && railHeading && railPartner && addExpenseCta,
      `Total Spend=${totalSpend}, charts=${canvases}, toggle=${toggle}, Monthly=${monthlyTab}, Yearly=${yearlyTab}, breakdown total=${breakdownTotal}, rail "This month"=${railHeading}, rail Partner=${railPartner}, Add expense CTA=${addExpenseCta}`);
  } catch (e) { record('6', 'Reports', false, `threw: ${e.message}`); }

  // ── Check 7: FX stability ──────────────────────────────────────
  try {
    await page.goto(`${BASE}/expenses`);
    await page.getByPlaceholder('0.00').waitFor();
    // Self-contained: add a JPY expense (original "¥…" contains no "S$", so the only S$
    // match is the converted SGD column), then confirm that value is identical after reload.
    await addExpense({ amount: '2000', currency: 'JPY', category: 'Groceries', merchant: 'FX Stability Check' });
    await page.getByText('Expense added').waitFor({ timeout: 15000 });
    await page.waitForTimeout(800);
    const row = page.locator('div.grid').filter({ hasText: 'FX Stability Check' }).first();
    const before = ((await row.textContent().catch(() => '')) ?? '').match(/S\$[\d,]+\.\d{2}/)?.[0] ?? null;
    await page.reload();
    await page.waitForTimeout(1200);
    const row2 = page.locator('div.grid').filter({ hasText: 'FX Stability Check' }).first();
    const after = ((await row2.textContent().catch(() => '')) ?? '').match(/S\$[\d,]+\.\d{2}/)?.[0] ?? null;
    record('7', 'FX historical stability', before !== null && before === after,
      `¥2,000 → converted SGD before=${before}, after reload=${after}, stable=${before === after}`);
  } catch (e) { record('7', 'FX stability', false, `threw: ${e.message}`); }

} finally {
  await browser.close();
}

const passed = results.filter(r => r.pass).length;
console.log(`\n==== SUMMARY: ${passed}/${results.length} checks passed ====`);
process.exit(passed === results.length ? 0 : 1);
